# core/workflow.py
import logging
import os
import threading
import concurrent.futures
import shutil
import numpy as np
import time
import re
import queue
from tkinter import messagebox

# Імпортуємо необхідні утиліти та функції
from utils.file_utils import sanitize_filename, chunk_text, chunk_text_voicemaker, chunk_text_speechify
from utils.media_utils import concatenate_audio_files, concatenate_videos
from core.audio_pipeline import AudioWorkerPool, AudioPipelineItem, TranscriptionPipelineItem

logger = logging.getLogger("TranslationApp")

class WorkflowManager:
    def __init__(self, app_instance):
        """
        Ініціалізує менеджер робочих процесів.
        'app_instance' - це посилання на головний клас TranslationApp для доступу до його стану та API.
        """
        self.app = app_instance
        self.config = app_instance.config
        # Отримуємо доступ до всіх API через головний клас
        self.or_api = app_instance.or_api
        self.poll_api = app_instance.poll_api
        self.recraft_api = app_instance.recraft_api
        self.el_api = app_instance.el_api
        self.vm_api = app_instance.vm_api
        self.speechify_api = app_instance.speechify_api
        self.montage_api = app_instance.montage_api
        self.tg_api = app_instance.tg_api
        self.firebase_api = app_instance.firebase_api
        self.transcription_results_queue = queue.Queue()
        
    def _get_status_key(self, task_idx, lang_code, is_rewrite=False):
        """Helper функція для створення правильного ключа статусу"""
        prefix = "rewrite_" if is_rewrite else ""
        return f"{prefix}{task_idx}_{lang_code}"
    
    def shutdown(self):
        """Зупиняє всі активні процеси WorkflowManager."""
        if hasattr(self, 'audio_worker_pool') and self.audio_worker_pool:
            logger.info("Зупинка аудіо воркер пулу...")
            self.audio_worker_pool.stop()
            self.audio_worker_pool = None
            
    def process_unified_queue(self, unified_queue):
        """
        Послідовно обробляє завдання з єдиної черги, викликаючи відповідний
        воркер залежно від типу завдання.
        """
        # Створюємо копію черги для безпечної ітерації
        queue_to_process = list(unified_queue)

        for task in queue_to_process:
            if not self.app._check_app_state():
                logger.warning("Обробку черги зупинено користувачем.")
                break
            
            task_type = task.get('type')
            queue_type_arg = 'main' if task_type == 'Translate' else 'rewrite'
            
            logger.info(f"Початок обробки завдання типу '{task_type}': {task.get('task_name')}")
            # _process_hybrid_queue очікує список завдань, тому передаємо поточне завдання в списку
            self._process_hybrid_queue([task], queue_type_arg)
            logger.info(f"Завершено обробку завдання: {task.get('task_name')}")
        
        logger.info("Обробку всіх завдань у єдиній черзі завершено.")

    def _process_hybrid_queue(self, queue_to_process_list, queue_type):
        is_rewrite = queue_type == 'rewrite'
        if is_rewrite:
            self.app.is_processing_rewrite_queue = True
        else:
            self.app.is_processing_queue = True
        
        # Setup Firebase command listening and clear old data if enabled
        if self.firebase_api.is_initialized:
            self.app.stop_command_listener.clear()
            # Clear previous commands and images before starting new session
            self.firebase_api.clear_commands()
            self.firebase_api.clear_montage_ready_status()  # Clear montage ready status
            
            if self.config.get("firebase", {}).get("auto_clear_gallery", True):
                self.firebase_api.clear_images()  # Clear old gallery images
                logger.info("Auto-cleared old gallery images from Firebase for new generation session")
            
            self.app.command_listener_thread = threading.Thread(target=self.app._command_listener_worker, daemon=True)
            self.app.command_listener_thread.start()
            # Start queue processor
            self.app.root.after(100, self.app._process_command_queue)

        self.app._update_button_states(is_processing=True, is_image_stuck=False)
        
        # Очищуємо event для контролю зображень на початку обробки
        self.app.image_control_active.clear()
        
        # --- НОВА ЛОГІКА: Детальний підрахунок кроків для прогрес-бару ---
        self.app.completed_individual_steps = 0
        self.app.total_individual_steps = 0
        num_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)

        if is_rewrite:
            # Рахуємо унікальні файли для транскрипції
            unique_files_to_transcribe = set()
            for task in queue_to_process_list:
                # Припускаємо, що налаштування транскрипції однакове для всіх мов у завданні
                if task['steps'][task['selected_langs'][0]].get('transcribe'):
                    unique_files_to_transcribe.add(task['mp3_path'])
            self.app.total_individual_steps += len(unique_files_to_transcribe)

        for task in queue_to_process_list:
            for lang_code in task['selected_langs']:
                steps = task['steps'][lang_code]
                if is_rewrite:
                    if steps.get('rewrite'): self.app.total_individual_steps += 1
                else: # main queue
                    if steps.get('translate'): self.app.total_individual_steps += 1
                
                # Спільні етапи
                if steps.get('cta'): self.app.total_individual_steps += 1
                if steps.get('gen_prompts'): self.app.total_individual_steps += 1
                if steps.get('gen_images'): self.app.total_individual_steps += 1 # Вважаємо генерацію всіх зображень для однієї мови як 1 етап
                if steps.get('audio'): self.app.total_individual_steps += num_chunks
                if steps.get('create_subtitles'): self.app.total_individual_steps += num_chunks
                if steps.get('create_video'):
                    self.app.total_individual_steps += num_chunks # для відео-шматків
                    self.app.total_individual_steps += 1        # для фінального об'єднання

        logger.info(f"Детальний підрахунок прогресу: знайдено {self.app.total_individual_steps} індивідуальних етапів.")
        self.app.update_individual_progress(queue_type) # Встановлюємо початковий 0%

        try:
            queue_to_process = list(queue_to_process_list)
            
            # Ініціалізація статусу для всіх завдань у черзі
            self.app.task_completion_status = {}
            for i, task in enumerate(queue_to_process):
                task['task_index'] = i
                for lang_code in task['selected_langs']:
                    # Додаємо префікс для рерайт черги
                    task_key = f"rewrite_{i}_{lang_code}" if is_rewrite else f"{i}_{lang_code}"
                    self.app.task_completion_status[task_key] = {
                        "task_name": task.get('task_name'),
                        "steps": {self.app._t('step_name_' + step_name): "Очікує" for step_name, enabled in task['steps'][lang_code].items() if enabled},
                        "images_generated": 0, # Лічильник успішних зображень
                        "total_images": 0      # Загальна кількість зображень для генерації
                    }

            processing_data = {}

            # Phase 0: Transcription (only for rewrite mode)
            if is_rewrite:
                logger.info("Hybrid mode -> Phase 0: Sequential transcription of local files.")
                step_name_key = self.app._t('step_name_transcribe')
                for task_index, task in enumerate(queue_to_process):
                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status and step_name_key in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key] = "В процесі"
                
                self.app.root.after(0, self.app.update_rewrite_task_status_display)
                
                transcribed_texts = {}
                rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']
                
                for task in queue_to_process:
                    mp3_path = task['mp3_path']
                    original_filename = task['original_filename']
                    
                    if mp3_path not in transcribed_texts:
                        video_title = sanitize_filename(os.path.splitext(original_filename)[0])
                        task_output_dir = os.path.join(rewrite_base_dir, video_title)
                        os.makedirs(task_output_dir, exist_ok=True)
                        original_transcript_path = os.path.join(task_output_dir, "original_transcript.txt")
                        
                        if os.path.exists(original_transcript_path):
                            with open(original_transcript_path, "r", encoding='utf-8') as f:
                                transcribed_text = f.read()
                        else:
                            model = self.montage_api._load_whisper_model()
                            if not model:
                                logger.error("Не вдалося завантажити модель Whisper. Переривання.")
                                return
                            transcription_result = model.transcribe(mp3_path, verbose=False)
                            transcribed_text = transcription_result['text']
                            with open(original_transcript_path, "w", encoding='utf-8') as f:
                                f.write(transcribed_text)

                        transcribed_texts[mp3_path] = {"text": transcribed_text, "title": video_title}
                        
                        # Збільшуємо лічильник прогресу після транскрипції унікального файлу
                        self.app.increment_and_update_progress(queue_type)
                        self.app.root.after(0, self.app.update_rewrite_task_status_display)

                for task in queue_to_process:
                    if task['mp3_path'] in transcribed_texts:
                        task['transcribed_text'] = transcribed_texts[task['mp3_path']]['text']
                        task['video_title'] = transcribed_texts[task['mp3_path']]['title']
                        
                        task_idx_str = task['task_index']
                        step_name_key = self.app._t('step_name_transcribe')
                        for lang_code in task['selected_langs']:
                            status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                            if status_key in self.app.task_completion_status and step_name_key in self.app.task_completion_status[status_key]['steps']:
                                self.app.task_completion_status[status_key]['steps'][step_name_key] = "Готово"
                
                self.app.root.after(0, self.app.update_rewrite_task_status_display)

            # Phase 1: Parallel text processing
            logger.info(f"Hybrid mode -> Phase 1: Parallel text processing for {len(queue_to_process)} tasks.")
            
            # Визначаємо, які текстові кроки будуть виконуватись
            text_step_keys = ['rewrite_text'] if is_rewrite else ['translate']
            
            # Встановлюємо статус "В процесі" для основного текстового кроку
            main_text_step_key = 'step_name_rewrite_text' if is_rewrite else 'step_name_translate'
            step_name_key = self.app._t(main_text_step_key)
            
            for task_index, task in enumerate(queue_to_process):
                for lang_code in task['selected_langs']:
                    status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                    # Перевіряємо, чи крок увімкнено для цього завдання
                    step_enabled_key = 'rewrite' if is_rewrite else 'translate'
                    if task['steps'][lang_code].get(step_enabled_key):
                        if status_key in self.app.task_completion_status and step_name_key in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key] = "В процесі"
            
            if is_rewrite: self.app.root.after(0, self.app.update_rewrite_task_status_display)
            else: self.app.root.after(0, self.app.update_task_status_display)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                text_futures = {}
                worker = self._rewrite_text_processing_worker if is_rewrite else self._text_processing_worker

                for task_index, task in enumerate(queue_to_process):
                    if is_rewrite and 'transcribed_text' not in task: continue
                    
                    for lang_code in task['selected_langs']:
                        task_key = (task_index, lang_code)
                        processing_data[task_key] = {'task': task} 
                        future = executor.submit(worker, self.app, task, lang_code, queue_type)
                        text_futures[future] = task_key
                
                for future in concurrent.futures.as_completed(text_futures):
                    task_key = text_futures[future]
                    processing_data[task_key]['text_results'] = future.result()

            logger.info("Гібридний режим -> Етап 1: Обробку тексту завершено.")
            
            for task_key, data in processing_data.items():
                task_idx_str, lang_code = task_key
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)

                if status_key in self.app.task_completion_status:
                    if data.get('text_results'):
                        # Маркуємо основний текстовий крок як "Готово" - ЦЕ ВИПРАВЛЕННЯ
                        main_text_step_key = 'rewrite_text' if is_rewrite else 'translate'
                        step_name_key_main = self.app._t(f'step_name_{main_text_step_key}')
                        if step_name_key_main in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key_main] = "Готово"

                        # Маркуємо інші текстові кроки, які були успішними
                        steps_to_mark = ['cta', 'gen_prompts']
                        for step in steps_to_mark:
                            step_name_key = self.app._t('step_name_' + step)
                            if step_name_key in self.app.task_completion_status[status_key]['steps']:
                                self.app.task_completion_status[status_key]['steps'][step_name_key] = "Готово"
                        
                        num_prompts = len(data['text_results'].get("prompts", []))
                        self.app.task_completion_status[status_key]["total_images"] = num_prompts
                    else:
                        # Якщо текстова обробка впала, маркуємо всі кроки як помилку
                        for step_name in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"

            if is_rewrite: self.app.root.after(0, self.app.update_rewrite_task_status_display)
            else: self.app.root.after(0, self.app.update_task_status_display)

            # --- ЕТАП 2: ОДНОЧАСНА ГЕНЕРАЦІЯ МЕДІА ---
            logger.info("Гібридний режим -> Етап 2: Одночасна генерація медіа.")
            
            self.app.root.after(0, self.app.setup_empty_gallery, queue_type, queue_to_process)
            
            should_gen_images = any(data.get('text_results') and data['task']['steps'][key[1]].get('gen_images') for key, data in processing_data.items())

            if should_gen_images:
                image_master_thread = threading.Thread(target=self._sequential_image_master, args=(processing_data, queue_to_process, queue_type, is_rewrite))
                image_master_thread.start()
            else:
                image_master_thread = None
                logger.info("Hybrid mode -> Image generation disabled for all tasks. Skipping.")

            audio_subs_master_thread = threading.Thread(target=self._audio_subs_pipeline_master, args=(processing_data, is_rewrite, queue_type))
            audio_subs_master_thread.start()
            
            if image_master_thread: image_master_thread.join()
            audio_subs_master_thread.join()
            
            logger.info("Гібридний режим -> Етап 2: Генерацію всіх медіафайлів завершено.")
            
            # --- ЕТАП 3: ОПЦІОНАЛЬНА ПАУЗА ---
            if self.config.get("ui_settings", {}).get("image_control_enabled", False):
                def show_pause_notification():
                    messagebox.showinfo("Процес призупинено", "Всі підготовчі етапи завершено!\n\nБудь ласка, перегляньте галерею зображень та внесіть правки.\n\nНатисніть 'Продовжити монтаж', щоб зібрати фінальні відео.")
                self.app.root.after(0, show_pause_notification)

                message_text = "🎨 *Контроль зображень*\n\nВсі зображення згенеровано\\. Будь ласка, перегляньте та відредагуйте їх у програмі, перш ніж продовжити монтаж\\." if should_gen_images else "🎬 *Готовність до монтажу*\n\nВсі підготовчі етапи завершено\\. Натисніть кнопку для продовження монтажу\\."
                
                if self.firebase_api and self.firebase_api.is_initialized: self.firebase_api.send_montage_ready_status()
                if self.tg_api and self.tg_api.enabled: self.tg_api.send_message_with_buttons(message=message_text, buttons=[{"text": "✅ Продовжити монтаж", "callback_data": "continue_montage_action"}])

                logger.info("WORKFLOW PAUSED. Waiting for user to press 'Continue Montage' button...")
                self.app.image_control_active.wait()
                logger.info("WORKFLOW RESUMED after user confirmation.")
            else:
                logger.info("Гібридний режим -> Етап 3: Пауза вимкнена, перехід до монтажу.")

            # Phase 4: Final montage and language reports
            logger.info("Hybrid mode -> Phase 4: Starting final montage and language reports.")

            for task_key, data in sorted(processing_data.items()):
                lang_code = task_key[1]
                task_idx_str = task_key[0]
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                
                if not (data.get('task') and data.get('text_results') and data['task']['steps'][lang_code].get('create_video')):
                    continue

                images_folder = data['text_results']['images_folder']
                all_images = sorted([os.path.join(images_folder, f) for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                
                if not data.get('audio_chunks') or not data.get('subs_chunks') or not all_images:
                    logger.error(f"Відсутні ресурси для монтажу відео для {task_key}. Пропуск.")
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
                    continue

                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "В процесі"
                    if is_rewrite: self.app.root.after(0, self.app.update_rewrite_task_status_display)
                    else: self.app.root.after(0, self.app.update_task_status_display)

                image_chunks = np.array_split(all_images, len(data['audio_chunks']))
                video_chunk_paths = []
                num_montage_threads = self.config.get('parallel_processing', {}).get('num_chunks', 3)

                with concurrent.futures.ThreadPoolExecutor(max_workers=num_montage_threads) as executor:
                    video_futures = {executor.submit(self._video_chunk_worker, self.app, list(image_chunks[i]), data['audio_chunks'][i], data['subs_chunks'][i], os.path.join(data['temp_dir'], f"video_chunk_{i:02d}.mp4"), i + 1, len(data['audio_chunks']), task_key): i for i in range(len(data['audio_chunks']))}
                    
                    video_results = {}
                    for f in concurrent.futures.as_completed(video_futures):
                        chunk_index = video_futures[f]
                        result = f.result()
                        if result: 
                            video_results[chunk_index] = result
                            self.app.increment_and_update_progress(queue_type) # +1 за кожен шматок відео
                            
                    video_chunk_paths = [video_results[i] for i in sorted(video_results.keys())]

                if len(video_chunk_paths) == len(data['audio_chunks']):
                    base_name = sanitize_filename(data['text_results'].get('video_title', data['text_results'].get('task_name', f"Task_{task_key[0]}")))
                    final_video_path = os.path.join(data['text_results']['output_path'], f"video_{base_name}_{lang_code}.mp4")
                    
                    if self._concatenate_videos(self.app, video_chunk_paths, final_video_path):
                        self.app.increment_and_update_progress(queue_type) # +1 за фінальне відео
                        logger.info(f"УСПІХ: Створено фінальне відео: {final_video_path}")
                        if status_key in self.app.task_completion_status:
                            self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Готово"
                        if is_rewrite: self.app.save_processed_link(data['task']['original_filename'])
                    else:
                        if status_key in self.app.task_completion_status:
                            self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
                else:
                    logger.error(f"ПОМИЛКА: Не вдалося створити всі частини відео для завдання {task_key}.")
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
                
                if self.config.get("telegram", {}).get("report_timing", "per_task") == "per_language":
                    self.app.send_task_completion_report(data['task'], single_lang_code=lang_code)

            # --- ФІНАЛЬНИЙ КРОК: ВІДПРАВКА ЗВІТІВ ДЛЯ ВСЬОГО ЗАВДАННЯ ---
            logger.info("Гібридний режим -> Всі завдання завершено. Відправка фінальних звітів...")
            if self.config.get("telegram", {}).get("report_timing", "per_task") == "per_task":
                for task_config in queue_to_process_list:
                    self.app.send_task_completion_report(task_config)
            
            # Встановлюємо прогрес-бар на 100% після завершення
            self.app.completed_individual_steps = self.app.total_individual_steps
            self.app.update_individual_progress(queue_type)
            self.app.root.after(0, lambda: messagebox.showinfo(self.app._t('queue_title'), self.app._t('info_queue_complete')))

        except Exception as e:
            logger.exception(f"CRITICAL ERROR: Unexpected error in hybrid queue processing: {e}")
        finally:
            # Cleanup temporary files
            if not self.config.get('parallel_processing', {}).get('keep_temp_files', False):
                for data in processing_data.values():
                    if 'temp_dir' in data and os.path.exists(data['temp_dir']):
                        try:
                            shutil.rmtree(data['temp_dir'])
                            logger.info(f"Cleaned temporary directory: {data['temp_dir']}")
                        except Exception as e:
                            logger.error(f"Failed to delete temporary directory {data['temp_dir']}: {e}")

            self.app.stop_telegram_polling.set()
            self.app._update_button_states(is_processing=False, is_image_stuck=False)
            
            # Очищуємо черги після завершення обробки
            if is_rewrite:
                self.app.is_processing_rewrite_queue = False
                self.app.rewrite_task_queue.clear()
                self.app.root.after(0, self.app.update_rewrite_queue_display)
            else:
                self.app.is_processing_queue = False
                self.app.task_queue.clear()
                self.app.root.after(0, self.app.update_queue_display)
            
            if hasattr(self.app, 'pause_resume_button'):
                 self.app.root.after(0, lambda: self.app.pause_resume_button.config(text=self.app._t('pause_button'), state="disabled"))
            if hasattr(self.app, 'rewrite_pause_resume_button'):
                 self.app.root.after(0, lambda: self.app.rewrite_pause_resume_button.config(text=self.app._t('pause_button'), state="disabled"))
            self.app.pause_event.set()

    def _text_processing_worker(self, app, task, lang_code, queue_type):
        """Execute all text operations for a single language task."""
        try:
            task_index = task['task_index']
            status_key = f"{task_index}_{lang_code}"
            
            lang_name = lang_code.upper()
            lang_config = self.config["languages"][lang_code]
            lang_steps = task['steps'][lang_code]
            output_cfg = self.config.get("output_settings", {})
            use_default_dir = output_cfg.get("use_default_dir", False)

            if use_default_dir:
                task_name_sanitized = sanitize_filename(task.get('task_name', f"Task_{int(time.time())}"))
                output_path = os.path.join(output_cfg.get("default_dir", ""), task_name_sanitized, lang_name)
            else:
                output_path = task['lang_output_paths'].get(lang_code)
            
            if not output_path:
                logger.error(f"Немає шляху виводу для {lang_name} у завданні {task.get('task_name')}.")
                return None
            os.makedirs(output_path, exist_ok=True)

            text_to_process = task['input_text']
            translation_path = os.path.join(output_path, "translation.txt")

            # Translation logic
            step_name_key_translate = self.app._t('step_name_translate')
            if lang_steps.get('translate'):
                if status_key in app.task_completion_status and step_name_key_translate in app.task_completion_status[status_key]['steps']:
                    app.task_completion_status[status_key]['steps'][step_name_key_translate] = "В процесі"
                    app.root.after(0, app.update_task_status_display)

                translated_text = self.or_api.translate_text(task['input_text'], self.config["openrouter"]["translation_model"], self.config["openrouter"]["translation_params"], lang_name, custom_prompt_template=lang_config.get("prompt"))
                if translated_text:
                    text_to_process = translated_text
                    with open(translation_path, 'w', encoding='utf-8') as f: f.write(translated_text)
                    app.increment_and_update_progress(queue_type)
                    if status_key in app.task_completion_status: app.task_completion_status[status_key]['steps'][step_name_key_translate] = "Готово"
                else:
                    logger.error(f"Translation failed for {lang_name}.")
                    if status_key in app.task_completion_status: app.task_completion_status[status_key]['steps'][step_name_key_translate] = "Помилка"
                    return None
            elif os.path.exists(translation_path):
                 with open(translation_path, 'r', encoding='utf-8') as f: text_to_process = f.read()
                 logger.info(f"Using existing translation file for {lang_name}: {translation_path}")
            else:
                text_to_process = task['input_text']

            prompts_path = os.path.join(output_path, "image_prompts.txt")
            
            if lang_steps.get('cta'):
                 cta_text = self.or_api.generate_call_to_action(text_to_process, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"], lang_name)
                 if cta_text:
                     with open(os.path.join(output_path, "call_to_action.txt"), 'w', encoding='utf-8') as f: f.write(cta_text)
                     app.increment_and_update_progress(queue_type)

            raw_prompts = None
            if lang_steps.get('gen_prompts'):
                raw_prompts = self.or_api.generate_image_prompts(text_to_process, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"], lang_name)
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
                    app.increment_and_update_progress(queue_type)
            elif os.path.exists(prompts_path):
                with open(prompts_path, 'r', encoding='utf-8') as f: raw_prompts = f.read()

            image_prompts = []
            if raw_prompts:
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                image_prompts = [block.strip() for block in prompt_blocks if block.strip()]

            images_folder = os.path.join(output_path, "images")
            os.makedirs(images_folder, exist_ok=True)

            return {
                "text_to_process": text_to_process, "output_path": output_path,
                "prompts": image_prompts, "images_folder": images_folder,
                "task_name": task.get('task_name', 'Untitled_Task')
            }
        except Exception as e:
            logger.exception(f"Error in text processing worker for {lang_code}: {e}")
            return None

    def _rewrite_text_processing_worker(self, app, task, lang_code, queue_type):
        """Обробляє ВЖЕ транскрибований текст для одного завдання рерайту."""
        try:
            task_index = task['task_index']
            status_key = f"rewrite_{task_index}_{lang_code}"
            
            video_title = task['video_title']
            transcribed_text = task['transcribed_text']
            rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']

            if not transcribed_text.strip(): return None

            lang_output_path = os.path.join(rewrite_base_dir, video_title, lang_code.upper())
            os.makedirs(lang_output_path, exist_ok=True)

            selected_template_name = app.rewrite_template_var.get()
            rewrite_prompt_template = self.config.get("rewrite_prompt_templates", {}).get(selected_template_name, {}).get(lang_code)
            
            # Rewrite logic
            step_name_key_rewrite = self.app._t('step_name_rewrite_text')
            if status_key in app.task_completion_status and step_name_key_rewrite in app.task_completion_status[status_key]['steps']:
                app.task_completion_status[status_key]['steps'][step_name_key_rewrite] = "В процесі"
                app.root.after(0, app.update_rewrite_task_status_display)

            rewritten_text = self.or_api.rewrite_text(transcribed_text, self.config["openrouter"]["rewrite_model"], self.config["openrouter"]["rewrite_params"], rewrite_prompt_template)
            if not rewritten_text: 
                if status_key in app.task_completion_status: app.task_completion_status[status_key]['steps'][step_name_key_rewrite] = "Помилка"
                return None
            
            with open(os.path.join(lang_output_path, "rewritten_text.txt"), "w", encoding='utf-8') as f: f.write(rewritten_text)
            app.increment_and_update_progress(queue_type)
            if status_key in app.task_completion_status: app.task_completion_status[status_key]['steps'][step_name_key_rewrite] = "Готово"
            
            # CTA logic
            cta_path = os.path.join(lang_output_path, "call_to_action.txt")
            if task['steps'][lang_code]['cta']:
                step_name_key_cta = self.app._t('step_name_cta')
                if status_key in app.task_completion_status:
                    app.task_completion_status[status_key]['steps'][step_name_key_cta] = "В процесі"
                    app.root.after(0, app.update_rewrite_task_status_display)
                
                cta_text = self.or_api.generate_call_to_action(rewritten_text, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"])
                if cta_text:
                    with open(cta_path, 'w', encoding='utf-8') as f: f.write(cta_text)
                    app.increment_and_update_progress(queue_type)
                    if status_key in app.task_completion_status: app.task_completion_status[status_key]['steps'][step_name_key_cta] = "Готово"

            # Prompt gen logic
            raw_prompts = None
            prompts_path = os.path.join(lang_output_path, "image_prompts.txt")
            if task['steps'][lang_code]['gen_prompts']:
                step_name_key_prompts = self.app._t('step_name_gen_prompts')
                if status_key in app.task_completion_status:
                    app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "В процесі"
                    app.root.after(0, app.update_rewrite_task_status_display)

                raw_prompts = self.or_api.generate_image_prompts(rewritten_text, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"])
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
                    app.increment_and_update_progress(queue_type)
                    if status_key in app.task_completion_status: app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "Готово"
            elif os.path.exists(prompts_path):
                with open(prompts_path, 'r', encoding='utf-8') as f: raw_prompts = f.read()

            image_prompts = []
            if raw_prompts:
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                image_prompts = [block.strip() for block in prompt_blocks if block.strip()]

            images_folder = os.path.join(lang_output_path, "images")
            os.makedirs(images_folder, exist_ok=True)
            
            return {
                "text_to_process": rewritten_text, "output_path": lang_output_path,
                "prompts": image_prompts, "images_folder": images_folder, "video_title": video_title
            }
        except Exception as e:
            logger.exception(f"Error in rewrite text processing worker for {lang_code}: {e}")
            return None

    def _sequential_image_master(self, processing_data, queue_to_process, queue_type, is_rewrite=False):
        """Головний потік, що керує послідовною генерацією всіх зображень."""
        logger.info("[Image Control] Image Master Thread: Starting sequential image generation.")
        for task_key, data in sorted(processing_data.items()):
            task_idx_str, lang_code = task_key
            status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
            step_name = self.app._t('step_name_gen_images')

            if data.get('text_results') and data['task']['steps'][lang_code].get('gen_images'):
                success = self._image_generation_worker(data, task_key, task_idx_str + 1, len(queue_to_process), queue_type, is_rewrite)
                if status_key in self.app.task_completion_status:
                    if self.app.task_completion_status[status_key]["images_generated"] > 0:
                        self.app.task_completion_status[status_key]['steps'][step_name] = "Готово"
                        self.app.increment_and_update_progress(queue_type) # +1 за пачку картинок
                    else:
                        self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"
            elif status_key in self.app.task_completion_status and step_name in self.app.task_completion_status[status_key]['steps']:
                self.app.task_completion_status[status_key]['steps'][step_name] = "Пропущено"

        logger.info("[Image Control] Image Master Thread: All image generation tasks complete.")

    def _image_generation_worker(self, data, task_key, task_num, total_tasks, queue_type, is_rewrite=False):
        prompts = data['text_results']['prompts']
        images_folder = data['text_results']['images_folder']
        lang_name = task_key[1].upper()

        # Встановлюємо статус "в процесі" для генерації зображень
        status_key = self._get_status_key(task_key[0], task_key[1], is_rewrite)
        if status_key in self.app.task_completion_status:
            step_name = self.app._t('step_name_gen_images')
            if step_name in self.app.task_completion_status[status_key]['steps']:
                self.app.task_completion_status[status_key]['steps'][step_name] = "В процесі"
                if is_rewrite:
                    self.app.root.after(0, self.app.update_rewrite_task_status_display)
                else:
                    self.app.root.after(0, self.app.update_task_status_display)

        with self.app.image_api_lock:
            if self.app.active_image_api is None:
                self.app.active_image_api = self.app.active_image_api_var.get()

        logger.info(f"Starting generation of {len(prompts)} images for {lang_name} using {self.app.active_image_api.capitalize()}.")

        auto_switch_enabled = self.config.get("ui_settings", {}).get("auto_switch_service_on_fail", False)
        retry_limit_for_switch = self.config.get("ui_settings", {}).get("auto_switch_retry_limit", 10)
        
        consecutive_failures = 0
        all_successful = True

        i = 0
        while i < len(prompts):
            if not self.app._check_app_state():
                all_successful = False
                break

            prompt = prompts[i]
            with self.app.image_api_lock:
                current_api_for_generation = self.app.active_image_api

            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - [{current_api_for_generation.capitalize()}] {self.app._t('step_gen_images')} {i+1}/{len(prompts)}..."
            self.app.update_progress(progress_text, queue_type=queue_type)

            image_path = os.path.join(images_folder, f"image_{i+1:03d}.jpg")

            # Check for user interruption events
            if self.app.skip_image_event.is_set():
                self.app.skip_image_event.clear()
                logger.warning(f"Skipping image {i+1} by user command.")
                i += 1
                continue

            if self.app.regenerate_alt_service_event.is_set():
                self.app.regenerate_alt_service_event.clear()
                logger.warning(f"Attempting to regenerate image {i+1} with alternate service.")
                with self.app.image_api_lock:
                    alt_service = "recraft" if self.app.active_image_api == "pollinations" else "pollinations"
                
                success_alt = False
                if alt_service == "pollinations":
                    success_alt = self.poll_api.generate_image(prompt, image_path)
                elif alt_service == "recraft":
                    success_alt, _ = self.recraft_api.generate_image(prompt, image_path)

                if success_alt:
                    logger.info(f"[{alt_service.capitalize()}] Successfully regenerated image {i+1} with alternate service.")
                    # Логіка успішної генерації, як у звичайному випадку
                    consecutive_failures = 0
                    self.app.image_prompts_map[image_path] = prompt
                    self.app.root.after(0, self.app._add_image_to_gallery, image_path, task_key)
                    status_key = self._get_status_key(task_key[0], task_key[1], is_rewrite)
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]["images_generated"] += 1
                        # Оновлюємо відображення після кожного згенерованого зображення
                        if is_rewrite:
                            self.app.root.after(0, self.app.update_rewrite_task_status_display)
                        else:
                            self.app.root.after(0, self.app.update_task_status_display)
                else:
                    logger.error(f"Alternate service [{alt_service.capitalize()}] also failed to generate image {i+1}.")
                    all_successful = False
                
                i += 1
                continue
            
            # Standard image generation process
            success = False
            if current_api_for_generation == "pollinations":
                success = self.poll_api.generate_image(prompt, image_path)
            elif current_api_for_generation == "recraft":
                success, _ = self.recraft_api.generate_image(prompt, image_path)

            if success:
                consecutive_failures = 0 
                logger.info(f"[{current_api_for_generation.capitalize()}] Successfully generated image {i+1}/{len(prompts)}.")
                self.app.image_prompts_map[image_path] = prompt
                
                # Add image to local gallery and Firebase
                self.app.root.after(0, self.app._add_image_to_gallery, image_path, task_key)
                if self.firebase_api.is_initialized:
                    task_name = data['task'].get('task_name', f"Task {task_key[0]}")
                    
                    # Callback для збереження мапування після завантаження
                    def save_mapping(image_id, local_path):
                        self.app.image_id_to_path_map[image_id] = local_path
                        logger.info(f"Збережено мапування: {image_id} -> {os.path.basename(local_path)}")
                    
                    self.firebase_api.upload_and_add_image_in_thread(image_path, task_key, i, task_name, prompt, callback=save_mapping)

                status_key = self._get_status_key(task_key[0], task_key[1], is_rewrite)
                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]["images_generated"] += 1
                    # Оновлюємо відображення після кожного згенерованого зображення  
                    if is_rewrite:
                        self.app.root.after(0, self.app.update_rewrite_task_status_display)
                    else:
                        self.app.root.after(0, self.app.update_task_status_display)
                i += 1 
            else:
                consecutive_failures += 1
                logger.error(f"[{current_api_for_generation.capitalize()}] Failed to generate image {i+1}. Consecutive failures: {consecutive_failures}.")
                
                # Логіка автоматичного перемикання
                if auto_switch_enabled and consecutive_failures >= retry_limit_for_switch:
                    logger.warning(f"Reached {consecutive_failures} consecutive failures. Triggering automatic service switch.")
                    with self.app.image_api_lock:
                        new_service = "recraft" if self.app.active_image_api == "pollinations" else "pollinations"
                        self.app.active_image_api = new_service
                        self.app.active_image_api_var.set(new_service) # Оновлюємо змінну для GUI
                        logger.warning(f"Service automatically switched to: {self.app.active_image_api.capitalize()}")
                    consecutive_failures = 0
                    continue 

                # Логіка ручного втручання
                # Використовуємо ліміт з Pollinations як тригер для кнопок
                manual_intervention_limit = self.config.get("pollinations", {}).get("retries", 5)
                if consecutive_failures >= manual_intervention_limit:
                    logger.error(f"{manual_intervention_limit} consecutive failures for one image. Activating manual controls.")
                    self.app._update_button_states(is_processing=True, is_image_stuck=True)
                    self.tg_api.send_message_with_buttons(
                        message="❌ *Помилка генерації зображення*\n\nНе вдається згенерувати зображення\\. Процес очікує\\. Оберіть дію:",
                        buttons=[
                            {"text": "Пропустити", "callback_data": "skip_image_action"},
                            {"text": "Спробувати іншим", "callback_data": "regenerate_alt_action"},
                            {"text": "Перемкнути назавжди", "callback_data": "switch_service_action"}
                        ]
                    )
                    # Чекаємо на дію користувача
                    while not (self.app.skip_image_event.is_set() or self.app.regenerate_alt_service_event.is_set()):
                        if not self.app._check_app_state(): # Дозволяє паузу/продовження під час очікування
                            all_successful = False
                            break
                        time.sleep(0.5)
                    
                    self.app._update_button_states(is_processing=True, is_image_stuck=False) # Деактивуємо кнопки після дії
                    continue # Повертаємось на початок циклу, щоб обробити подію
                
                # Якщо нічого не спрацювало, просто переходимо до наступного зображення
                all_successful = False
                i += 1

        # Встановлюємо фінальний статус для генерації зображень
        status_key = self._get_status_key(task_key[0], task_key[1], is_rewrite)
        if status_key in self.app.task_completion_status:
            step_name = self.app._t('step_name_gen_images')
            if step_name in self.app.task_completion_status[status_key]['steps']:
                final_status = "Готово" if all_successful else "Помилка"
                self.app.task_completion_status[status_key]['steps'][step_name] = final_status
                if is_rewrite:
                    self.app.root.after(0, self.app.update_rewrite_task_status_display)
                else:
                    self.app.root.after(0, self.app.update_task_status_display)

        return all_successful

    def _audio_subs_pipeline_master(self, processing_data, is_rewrite=False, queue_type='main'):
        """Керує пайплайном Аудіо -> Транскрипція з централізованою логікою."""
        logger.info("[Audio/Subs Master] Запуск керованого пайплайну.")

        num_parallel_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)
        self.audio_worker_pool = AudioWorkerPool(self.app, num_parallel_chunks)
        self.audio_worker_pool.start()

        tasks_info = {}
        total_audio_chunks_expected = 0

        try:
            # 1. Створення плану та відправка всіх аудіо-завдань на виконання
            for task_key, data in sorted(processing_data.items()):
                if not data.get('text_results'): continue

                task_idx_str, lang_code = task_key
                lang_config = self.config["languages"][lang_code]
                tts_service = lang_config.get("tts_service", "elevenlabs")
                text_to_process = data['text_results']['text_to_process']
                temp_dir = os.path.join(data['text_results']['output_path'], "temp_chunks")
                os.makedirs(temp_dir, exist_ok=True)
                data['temp_dir'] = temp_dir

                voicemaker_limit = self.config.get("voicemaker", {}).get("char_limit", 2900)
                text_chunks = []
                if tts_service == "voicemaker" and len(text_to_process) > voicemaker_limit:
                    text_chunks = chunk_text_voicemaker(text_to_process, voicemaker_limit)
                else:
                    text_chunks = chunk_text(text_to_process, num_parallel_chunks)

                if not text_chunks:
                    logger.warning(f"Текст для {task_key} порожній, аудіо не буде згенеровано.")
                    continue

                total_audio_chunks_expected += len(text_chunks)
                tasks_info[str(task_key)] = {
                    'tts_service': tts_service,
                    'total_chunks': len(text_chunks),
                    'completed_audio_items': [],
                    'data': data
                }
                
                # Ініціалізація лічильників
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]['total_audio'] = len(text_chunks)
                    # Кількість субтитрів залежить від того, чи буде об'єднання
                    subs_count = num_parallel_chunks if tts_service == 'voicemaker' and len(text_chunks) > num_parallel_chunks else len(text_chunks)
                    self.app.task_completion_status[status_key]['total_subs'] = subs_count
                    self.app.task_completion_status[status_key]['audio_generated'] = 0
                    self.app.task_completion_status[status_key]['subs_generated'] = 0
                
                for i, chunk in enumerate(text_chunks):
                    audio_task = AudioPipelineItem(
                        text_chunk=chunk,
                        output_path=os.path.join(temp_dir, f"audio_chunk_{i}.mp3"),
                        lang_config=lang_config, lang_code=lang_code,
                        chunk_index=i, total_chunks=len(text_chunks),
                        task_key=str(task_key)
                    )
                    self.audio_worker_pool.add_audio_task(audio_task)

            logger.info(f"Всього відправлено на озвучку: {total_audio_chunks_expected} фрагментів.")

            # 2. Цикл збору результатів озвучки та відправки на транскрипцію
            completed_audio_count = 0
            total_transcriptions_submitted = 0

            while completed_audio_count < total_audio_chunks_expected and not self.app.shutdown_event.is_set():
                try:
                    result = self.audio_worker_pool.audio_results_queue.get(timeout=1.0)
                    completed_audio_count += 1

                    if not result.success:
                        logger.error(f"Помилка генерації аудіо для {result.item.task_key}, фрагмент {result.item.chunk_index}. Пропускаємо.")
                        continue
                    
                    self.app.increment_and_update_progress(queue_type)

                    task_key = result.item.task_key
                    task_info = tasks_info[task_key]
                    task_info['completed_audio_items'].append(result.item)
                    
                    # Оновлюємо лічильник аудіо в GUI
                    task_key_tuple = eval(task_key)
                    status_key = self._get_status_key(task_key_tuple[0], task_key_tuple[1], is_rewrite)
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['audio_generated'] += 1
                        if is_rewrite: self.app.root.after(0, self.app.update_rewrite_task_status_display)
                        else: self.app.root.after(0, self.app.update_task_status_display)

                    if task_info['tts_service'] != 'voicemaker':
                        trans_item = TranscriptionPipelineItem(result.item.output_path, os.path.dirname(result.item.output_path), result.item.chunk_index, result.item.lang_code, task_key)
                        self.audio_worker_pool.add_transcription_task(trans_item)
                        total_transcriptions_submitted += 1
                    elif len(task_info['completed_audio_items']) == task_info['total_chunks']:
                        sorted_items = sorted(task_info['completed_audio_items'], key=lambda x: x.chunk_index)
                        audio_paths_to_merge = [item.output_path for item in sorted_items]
                        
                        groups = [audio_paths_to_merge[i:i + num_parallel_chunks] for i in range(0, len(audio_paths_to_merge), num_parallel_chunks)]
                        
                        for i, group_list in enumerate(groups):
                            if not group_list: continue
                            merged_path = os.path.join(task_info['data']['temp_dir'], f"merged_chunk_{i}.mp3")
                            if len(group_list) > 1:
                                if not concatenate_audio_files(group_list, merged_path): continue
                            else:
                                shutil.copy(group_list[0], merged_path)
                            trans_item = TranscriptionPipelineItem(merged_path, os.path.dirname(merged_path), i, result.item.lang_code, task_key, is_merged_group=True)
                            self.audio_worker_pool.add_transcription_task(trans_item)
                            total_transcriptions_submitted += 1
                except queue.Empty:
                    continue

            # 3. Збираємо результати транскрипції
            logger.info(f"Очікується {total_transcriptions_submitted} результатів транскрипції.")
            completed_transcriptions = 0
            while completed_transcriptions < total_transcriptions_submitted and not self.app.shutdown_event.is_set():
                try:
                    result_item = self.transcription_results_queue.get(timeout=1.0)
                    completed_transcriptions += 1
                    
                    if result_item.subs_path:
                        self.app.increment_and_update_progress(queue_type)
                        info = tasks_info[result_item.task_key]
                        if 'subs_chunks' not in info['data']: info['data']['subs_chunks'] = []
                        if 'audio_chunks' not in info['data']: info['data']['audio_chunks'] = []
                        info['data']['subs_chunks'].append(result_item.subs_path)
                        info['data']['audio_chunks'].append(result_item.audio_path)
                        
                        # Оновлюємо лічильник субтитрів в GUI
                        task_key_tuple = eval(result_item.task_key)
                        status_key = self._get_status_key(task_key_tuple[0], task_key_tuple[1], is_rewrite)
                        if status_key in self.app.task_completion_status:
                            self.app.task_completion_status[status_key]['subs_generated'] += 1
                            if is_rewrite: self.app.root.after(0, self.app.update_rewrite_task_status_display)
                            else: self.app.root.after(0, self.app.update_task_status_display)

                except queue.Empty:
                    continue

            # Фінальне оновлення статусів
            for tk, info in tasks_info.items():
                if 'subs_chunks' in info['data']: info['data']['subs_chunks'].sort()
                if 'audio_chunks' in info['data']: info['data']['audio_chunks'].sort()
                
                task_key_tuple = eval(tk)
                status_key = self._get_status_key(task_key_tuple[0], task_key_tuple[1], is_rewrite)
                if status_key in self.app.task_completion_status:
                    total_audio = self.app.task_completion_status[status_key].get('total_audio', 0)
                    generated_audio = self.app.task_completion_status[status_key].get('audio_generated', 0)
                    total_subs = self.app.task_completion_status[status_key].get('total_subs', 0)
                    generated_subs = self.app.task_completion_status[status_key].get('subs_generated', 0)
                    
                    self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_audio')] = "Готово" if generated_audio >= total_audio and total_audio > 0 else "Помилка"
                    self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_subtitles')] = "Готово" if generated_subs >= total_subs and total_subs > 0 else "Помилка"

            if is_rewrite: self.app.root.after(0, self.app.update_rewrite_task_status_display)
            else: self.app.root.after(0, self.app.update_task_status_display)

        except Exception as e:
            logger.exception(f"CRITICAL ERROR in audio/subs master pipeline: {e}")
        finally:
            if self.audio_worker_pool:
                self.audio_worker_pool.stop()
                logger.info("[Audio/Subs Master] Пайплайн завершено, воркер пул зупинено.")

    def _concatenate_videos(self, app_instance, video_chunks, output_path):
        """Об'єднання відеофрагментів."""
        return concatenate_videos(app_instance, video_chunks, output_path)

    def _video_chunk_worker(self, app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks, task_key):
        """Створення одного відеофрагменту."""
        from utils.media_utils import video_chunk_worker
        return video_chunk_worker(app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks, task_key)
