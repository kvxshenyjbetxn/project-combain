# core/workflow.py
import logging
import os
import threading
import concurrent.futures
import shutil
import numpy as np
import time
import re
from tkinter import messagebox

# Імпортуємо необхідні утиліти та функції
from utils.file_utils import sanitize_filename, chunk_text, chunk_text_voicemaker, chunk_text_speechify
from utils.media_utils import concatenate_audio_files, concatenate_videos
from core.audio_pipeline import AudioWorkerPool, AudioPipelineItem

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
        
    def shutdown(self):
        """Зупиняє всі активні процеси WorkflowManager."""
        if hasattr(self, 'audio_worker_pool') and self.audio_worker_pool:
            logger.info("Зупинка аудіо воркер пулу...")
            self.audio_worker_pool.stop()
            self.audio_worker_pool = None

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

        try:
            queue_to_process = list(queue_to_process_list)
            if is_rewrite:
                self.app.rewrite_task_queue.clear()
                self.app.update_rewrite_queue_display()
            else:
                self.app.task_queue.clear()
                self.app.update_queue_display()
            
            # Ініціалізація статусу для всіх завдань у черзі
            self.app.task_completion_status = {}
            for i, task in enumerate(queue_to_process):
                task['task_index'] = i
                for lang_code in task['selected_langs']:
                    task_key = f"{i}_{lang_code}"
                    self.app.task_completion_status[task_key] = {
                        "task_name": task.get('task_name'),
                        "steps": {self.app._t('step_name_' + step_name): "⚪️" for step_name, enabled in task['steps'][lang_code].items() if enabled},
                        "images_generated": 0, # Лічильник успішних зображень
                        "total_images": 0      # Загальна кількість зображень для генерації
                    }

            processing_data = {}

            # Phase 0: Transcription (only for rewrite mode)
            if is_rewrite:
                self.app.update_progress(self.app._t('phase_0_transcription'))
                logger.info("Hybrid mode -> Phase 0: Sequential transcription of local files.")
                
                transcribed_texts = {}
                rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']
                
                for task in queue_to_process:
                    mp3_path = task['mp3_path']
                    original_filename = task['original_filename']
                    
                    if mp3_path not in transcribed_texts:
                        # Clean filename and sanitize for directory creation
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

                for task in queue_to_process:
                    if task['mp3_path'] in transcribed_texts:
                        task['transcribed_text'] = transcribed_texts[task['mp3_path']]['text']
                        task['video_title'] = transcribed_texts[task['mp3_path']]['title']
                        
                        # Оновлюємо статус транскрипції для всіх мов у цьому завданні
                        task_idx_str = task['task_index']
                        step_name_key = self.app._t('step_name_transcribe')
                        for lang_code in task['selected_langs']:
                            status_key = f"{task_idx_str}_{lang_code}"
                            if status_key in self.app.task_completion_status and step_name_key in self.app.task_completion_status[status_key]['steps']:
                                self.app.task_completion_status[status_key]['steps'][step_name_key] = "✅"


            # Phase 1: Parallel text processing
            self.app.update_progress(self.app._t('phase_1_text_processing'))
            logger.info(f"Hybrid mode -> Phase 1: Parallel text processing for {len(queue_to_process)} tasks.")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                text_futures = {}
                worker = self._rewrite_text_processing_worker if is_rewrite else self._text_processing_worker

                for task_index, task in enumerate(queue_to_process):
                    if is_rewrite and 'transcribed_text' not in task:
                        continue
                    
                    for lang_code in task['selected_langs']:
                        task_key = (task_index, lang_code)
                        processing_data[task_key] = {'task': task} 
                        future = executor.submit(worker, task, lang_code)
                        text_futures[future] = task_key
                
                for future in concurrent.futures.as_completed(text_futures):
                    task_key = text_futures[future]
                    processing_data[task_key]['text_results'] = future.result()

            logger.info("Гібридний режим -> Етап 1: Обробку тексту завершено.")
            
            # --- ОНОВЛЕНИЙ БЛОК ПІСЛЯ ОБРОБКИ ТЕКСТУ ---
            for task_key, data in processing_data.items():
                task_idx_str, lang_code = task_key
                status_key = f"{task_idx_str}_{lang_code}"

                if status_key in self.app.task_completion_status:
                    if data.get('text_results'):
                        # Відмічаємо успішність текстових етапів
                        steps_to_mark = ['translate', 'rewrite', 'cta', 'gen_prompts']
                        for step in steps_to_mark:
                            step_name_key = self.app._t('step_name_' + step)
                            if step_name_key in self.app.task_completion_status[status_key]['steps']:
                                self.app.task_completion_status[status_key]['steps'][step_name_key] = "✅"
                        
                        # Зберігаємо загальну кількість запланованих зображень
                        num_prompts = len(data['text_results'].get("prompts", []))
                        self.app.task_completion_status[status_key]["total_images"] = num_prompts
                    else:
                        # Якщо текстовий етап провалився, відмічаємо всі наступні як провалені
                        for step_name in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name] = "❌"


            # --- ЕТАП 2: ОДНОЧАСНА ГЕНЕРАЦІЯ МЕДІА ---
            self.app.update_progress(self.app._t('phase_2_media_generation'))
            logger.info("Гібридний режим -> Етап 2: Одночасна генерація медіа.")
            
            self.app.root.after(0, self.app.setup_empty_gallery, queue_type, queue_to_process)
            
            should_gen_images = any(
                data.get('text_results') and data['task']['steps'][key[1]].get('gen_images')
                for key, data in processing_data.items()
            )

            if should_gen_images:
                image_master_thread = threading.Thread(target=self._sequential_image_master, args=(processing_data, queue_to_process))
                image_master_thread.start()
            else:
                image_master_thread = None
                logger.info("Hybrid mode -> Image generation disabled for all tasks. Skipping.")

            audio_subs_master_thread = threading.Thread(target=self._audio_subs_pipeline_master, args=(processing_data, is_rewrite))
            audio_subs_master_thread.start()
            
            if image_master_thread:
                image_master_thread.join()
            audio_subs_master_thread.join()
            
            logger.info("Гібридний режим -> Етап 2: Генерацію всіх медіафайлів завершено.")
            
            # --- ЕТАП 3: ОПЦІОНАЛЬНА ПАУЗА ---
            if self.config.get("ui_settings", {}).get("image_control_enabled", False) and should_gen_images:
                self.app.update_progress(self.app._t('phase_3_image_control'))
                logger.info("Гібридний режим -> Етап 3: Пауза для налаштування зображень користувачем.")
                
                # Відправляємо статус готовності до монтажу в Firebase
                self.firebase_api.send_montage_ready_status()
                
                # Надсилаємо повідомлення в Telegram
                self.tg_api.send_message_with_buttons(
                    message="🎨 *Контроль зображень*\n\nВсі зображення згенеровано\\. Будь ласка, перегляньте та відредагуйте їх у програмі, перш ніж продовжити монтаж\\.",
                    buttons=[
                        {"text": "✅ Продовжити монтаж", "callback_data": "continue_montage_action"}
                    ]
                )

                self.app.image_control_active.wait()
            else:
                logger.info("Гібридний режим -> Етап 3: Пауза вимкнена або не потрібна, перехід до монтажу.")

            # Phase 4: Final montage and language reports
            self.app.update_progress(self.app._t('phase_4_final_montage'))
            logger.info("Hybrid mode -> Phase 4: Starting final montage and language reports.")

            for task_key, data in sorted(processing_data.items()):
                lang_code = task_key[1]
                task_idx_str = task_key[0]
                status_key = f"{task_idx_str}_{lang_code}"
                
                if data.get('task') and data.get('text_results') and data['task']['steps'][lang_code].get('create_video'):
                    
                    images_folder = data['text_results']['images_folder']
                    all_images = sorted([os.path.join(images_folder, f) for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                    
                    if not data.get('audio_chunks') or not data.get('subs_chunks'):
                        logger.error(f"Audio or subtitles missing for task {task_key}. Skipping video montage.")
                        if status_key in self.app.task_completion_status:
                            step_name = self.app._t('step_name_create_video')
                            self.app.task_completion_status[status_key]['steps'][step_name] = "❌"
                        continue
                        
                    if not all_images:
                        logger.error(f"Зображення не знайдено для завдання {task_key}. Пропускаємо монтаж відео.")
                        if status_key in self.app.task_completion_status:
                            step_name = self.app._t('step_name_create_video')
                            self.app.task_completion_status[status_key]['steps'][step_name] = "❌"
                        continue

                    image_chunks = np.array_split(all_images, len(data['audio_chunks']))
                    
                    video_chunk_paths = []
                    num_montage_threads = self.config.get('parallel_processing', {}).get('num_chunks', 3)

                    with concurrent.futures.ThreadPoolExecutor(max_workers=num_montage_threads) as executor:
                        video_futures = {
                            executor.submit(
                                self._video_chunk_worker, 
                                self.app,
                                list(image_chunks[i]), 
                                data['audio_chunks'][i], 
                                data['subs_chunks'][i],
                                os.path.join(data['temp_dir'], f"video_chunk_{i}.mp4"),
                                i + 1, len(data['audio_chunks'])
                            ): i for i in range(len(data['audio_chunks']))
                        }
                        for f in concurrent.futures.as_completed(video_futures):
                            result = f.result()
                            if result: video_chunk_paths.append(result)

                    if len(video_chunk_paths) == len(data['audio_chunks']):
                        if 'video_title' in data['text_results']:
                            base_name = sanitize_filename(data['text_results']['video_title'])
                        else:
                            base_name = sanitize_filename(data['text_results'].get('task_name', f"Task_{task_key[0]}"))
                        
                        final_video_path = os.path.join(data['text_results']['output_path'], f"video_{base_name}_{lang_code}.mp4")
                        if self._concatenate_videos(self.app, sorted(video_chunk_paths), final_video_path):
                            logger.info(f"УСПІХ: Створено фінальне відео: {final_video_path}")
                            if status_key in self.app.task_completion_status:
                                step_name = self.app._t('step_name_create_video')
                                self.app.task_completion_status[status_key]['steps'][step_name] = "✅"
                            if is_rewrite:
                                self.app.save_processed_link(data['task']['original_filename'])
                        else:
                             if status_key in self.app.task_completion_status:
                                step_name = self.app._t('step_name_create_video')
                                self.app.task_completion_status[status_key]['steps'][step_name] = "❌"
                    else:
                        logger.error(f"ПОМИЛКА: Не вдалося створити всі частини відео для завдання {task_key}.")
                        if status_key in self.app.task_completion_status:
                            step_name = self.app._t('step_name_create_video')
                            self.app.task_completion_status[status_key]['steps'][step_name] = "❌"
                
                # Відправка звіту після завершення обробки однієї мови
                report_timing = self.config.get("telegram", {}).get("report_timing", "per_task")
                if report_timing == "per_language":
                    self.app.send_task_completion_report(data['task'], single_lang_code=lang_code)

            # --- ФІНАЛЬНИЙ КРОК: ВІДПРАВКА ЗВІТІВ ДЛЯ ВСЬОГО ЗАВДАННЯ ---
            logger.info("Гібридний режим -> Всі завдання завершено. Відправка фінальних звітів...")
            report_timing = self.config.get("telegram", {}).get("report_timing", "per_task")
            if report_timing == "per_task":
                for task_config in queue_to_process:
                    self.app.send_task_completion_report(task_config)
            
            self.app.root.after(0, lambda: self.app.progress_label.config(text=self.app._t('status_complete')))
            self.app.root.after(0, lambda: messagebox.showinfo(self.app._t('queue_title'), self.app._t('info_queue_complete')))

        except Exception as e:
            logger.exception(f"CRITICAL ERROR: Unexpected error in hybrid queue processing: {e}")
        finally:
            # Cleanup temporary files
            keep_temp_files = self.config.get('parallel_processing', {}).get('keep_temp_files', False)
            if not keep_temp_files:
                self.app.update_progress(self.app._t('phase_cleaning_up'))
                for task_key, data in processing_data.items():
                    if 'temp_dir' in data and os.path.exists(data['temp_dir']):
                        try:
                            shutil.rmtree(data['temp_dir'])
                            logger.info(f"Cleaned temporary directory: {data['temp_dir']}")
                        except Exception as e:
                            logger.error(f"Failed to delete temporary directory {data['temp_dir']}: {e}")

            self.app.stop_telegram_polling.set()
            self.app._update_button_states(is_processing=False, is_image_stuck=False)
            if is_rewrite:
                self.app.is_processing_rewrite_queue = False
                self.app.root.after(0, self.app.update_rewrite_queue_display)
            else:
                self.app.is_processing_queue = False
                self.app.root.after(0, self.app.update_queue_display)
            
            if hasattr(self.app, 'pause_resume_button'):
                 self.app.root.after(0, lambda: self.app.pause_resume_button.config(text=self.app._t('pause_button'), state="disabled"))
            self.app.pause_event.set()

    def _text_processing_worker(self, task, lang_code):
        """Execute all text operations for a single language task."""
        try:
            lang_name = lang_code.upper()
            lang_config = self.config["languages"][lang_code]
            lang_steps = task['steps'][lang_code]
            output_cfg = self.config.get("output_settings", {})
            use_default_dir = output_cfg.get("use_default_dir", False)

            # Визначення шляху для збереження
            if use_default_dir:
                task_name = sanitize_filename(task.get('task_name', f"Task_{int(time.time())}"))
                output_path = os.path.join(output_cfg.get("default_dir", ""), task_name, lang_name)
            else:
                output_path = task['lang_output_paths'].get(lang_code)
            
            if not output_path:
                logger.error(f"Немає шляху виводу для {lang_name} у завданні {task.get('task_name')}.")
                return None
            os.makedirs(output_path, exist_ok=True)

            text_to_process = task['input_text']
            translation_path = os.path.join(output_path, "translation.txt")

            # Translation logic
            if lang_steps.get('translate'):
                translated_text = self.or_api.translate_text(
                    task['input_text'], self.config["openrouter"]["translation_model"],
                    self.config["openrouter"]["translation_params"], lang_name,
                    custom_prompt_template=lang_config.get("prompt")
                )
                if translated_text:
                    text_to_process = translated_text
                    with open(translation_path, 'w', encoding='utf-8') as f:
                        f.write(translated_text)
                else:
                    logger.error(f"Translation failed for {lang_name}.")
                    return None
            elif os.path.exists(translation_path):
                 with open(translation_path, 'r', encoding='utf-8') as f:
                    text_to_process = f.read()
                 logger.info(f"Using existing translation file for {lang_name}: {translation_path}")
            else:
                logger.info(f"Translation step is disabled and no existing translation file was found for {lang_name}. Using original text.")
                text_to_process = task['input_text']

            cta_text, raw_prompts = None, None
            prompts_path = os.path.join(output_path, "image_prompts.txt")
            
            # Generate CTA (always from text_to_process)
            if lang_steps.get('cta'):
                 cta_text = self.or_api.generate_call_to_action(text_to_process, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"], lang_name)
                 if cta_text:
                     with open(os.path.join(output_path, "call_to_action.txt"), 'w', encoding='utf-8') as f: f.write(cta_text)

            # Generate or read prompts
            image_prompts = []
            if lang_steps.get('gen_prompts'):
                raw_prompts = self.or_api.generate_image_prompts(text_to_process, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"], lang_name)
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
            elif os.path.exists(prompts_path):
                logger.info(f"Using existing prompts file: {prompts_path}")
                with open(prompts_path, 'r', encoding='utf-8') as f:
                    raw_prompts = f.read()

            if raw_prompts:
                # Універсальна логіка: об'єднуємо багаторядкові промпти, а потім розділяємо за нумерацією
                # Спочатку замінюємо всі переноси рядків на пробіли
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                # Розділяємо за шаблоном "число." (наприклад, "1.", "2." і т.д.), видаляючи сам роздільник
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                # Перший елемент після розділення зазвичай порожній, тому відфільтровуємо його
                image_prompts = [block.strip() for block in prompt_blocks if block.strip()]

            images_folder = os.path.join(output_path, "images")
            os.makedirs(images_folder, exist_ok=True)

            return {
                "text_to_process": text_to_process,
                "output_path": output_path,
                "prompts": image_prompts,
                "images_folder": images_folder,
                "task_name": task.get('task_name', 'Untitled_Task')
            }
        except Exception as e:
            logger.exception(f"Error in text processing worker for {lang_code}: {e}")
            return None

    def _rewrite_text_processing_worker(self, task, lang_code):
        """Обробляє ВЖЕ транскрибований текст для одного завдання рерайту."""
        try:
            video_title = task['video_title']
            transcribed_text = task['transcribed_text']
            rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']

            if not transcribed_text.strip(): return None

            # Подальша обробка для конкретної мови
            lang_output_path = os.path.join(rewrite_base_dir, video_title, lang_code.upper())
            os.makedirs(lang_output_path, exist_ok=True)

            selected_template_name = self.app.rewrite_template_var.get()
            rewrite_prompt_template = self.config.get("rewrite_prompt_templates", {}).get(selected_template_name, {}).get(lang_code)
            
            rewritten_text = self.or_api.rewrite_text(transcribed_text, self.config["openrouter"]["rewrite_model"], self.config["openrouter"]["rewrite_params"], rewrite_prompt_template)
            if not rewritten_text: return None
            
            with open(os.path.join(lang_output_path, "rewritten_text.txt"), "w", encoding='utf-8') as f: f.write(rewritten_text)
            
            # CTA та промти
            cta_path = os.path.join(lang_output_path, "call_to_action.txt")
            prompts_path = os.path.join(lang_output_path, "image_prompts.txt")

            # Генерація CTA або читання з файлу
            if task['steps'][lang_code]['cta']:
                cta_text = self.or_api.generate_call_to_action(rewritten_text, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"])
                if cta_text:
                    with open(cta_path, 'w', encoding='utf-8') as f: f.write(cta_text)

            # Генерація промтів або читання з файлу
            raw_prompts = None
            if task['steps'][lang_code]['gen_prompts']:
                raw_prompts = self.or_api.generate_image_prompts(rewritten_text, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"])
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
            elif os.path.exists(prompts_path):
                logger.info(f"Using existing prompts file for rewrite task: {prompts_path}")
                with open(prompts_path, 'r', encoding='utf-8') as f:
                    raw_prompts = f.read()

            image_prompts = []
            if raw_prompts:
                # Універсальна логіка: об'єднуємо багаторядкові промпти, а потім розділяємо за нумерацією
                # Спочатку замінюємо всі переноси рядків на пробіли
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                # Розділяємо за шаблоном "число." (наприклад, "1.", "2." і т.д.), видаляючи сам роздільник
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                # Перший елемент після розділення зазвичай порожній, тому відфільтровуємо його
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

    def _sequential_image_master(self, processing_data, queue_to_process):
        """Головний потік, що керує послідовною генерацією всіх зображень."""
        logger.info("[Image Control] Image Master Thread: Starting sequential image generation.")
        for task_key, data in sorted(processing_data.items()):
            task_idx_str, lang_code = task_key
            status_key = f"{task_idx_str}_{lang_code}"
            step_name = self.app._t('step_name_gen_images')

            if data.get('text_results') and data['task']['steps'][lang_code].get('gen_images'):
                success = self._image_generation_worker(data, task_key, task_idx_str + 1, len(queue_to_process))
                if status_key in self.app.task_completion_status:
                    # Тепер ми перевіряємо, чи були згенеровані якісь зображення
                    if self.app.task_completion_status[status_key]["images_generated"] > 0:
                        self.app.task_completion_status[status_key]['steps'][step_name] = "✅"
                    else:
                        # Якщо жодного зображення не згенеровано, вважаємо крок проваленим
                        self.app.task_completion_status[status_key]['steps'][step_name] = "❌"
            else:
                if status_key in self.app.task_completion_status and step_name in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name] = "⚪️" # Mark as skipped, not failed

        logger.info("[Image Control] Image Master Thread: All image generation tasks complete.")

    def _image_generation_worker(self, data, task_key, task_num, total_tasks):
        prompts = data['text_results']['prompts']
        images_folder = data['text_results']['images_folder']
        lang_name = task_key[1].upper()

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
            self.app.update_progress(progress_text)

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
                    status_key = f"{task_key[0]}_{task_key[1]}"
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]["images_generated"] += 1
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

                status_key = f"{task_key[0]}_{task_key[1]}"
                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]["images_generated"] += 1
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

        return all_successful

    def _audio_subs_pipeline_master(self, processing_data, is_rewrite=False):
        """Керує новим пайплайном Аудіо -> Транскрипція з використанням воркер пулу."""
        logger.info(f"[Audio/Subs Master] Запуск нового пайплайну з воркер пулом. Режим: {'рерайт' if is_rewrite else 'переклад'}")
        
        num_parallel_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)
        
        # Ініціалізуємо та запускаємо аудіо воркер пул
        self.audio_worker_pool = AudioWorkerPool(self.app, num_parallel_chunks)
        self.audio_worker_pool.start()
        
        try:
            # Підготовка всіх аудіо завдань
            audio_tasks = []
            task_chunks_info = {}  # task_key -> {lang_code, total_chunks, temp_dir, etc.}
            
            for task_key, data in sorted(processing_data.items()):
                if not data.get('text_results'): 
                    continue
                
                task_idx_str, lang_code = task_key
                status_key = f"{task_idx_str}_{lang_code}"
                lang_steps = data['task']['steps'][lang_code]
                lang_config = self.config["languages"][lang_code]
                tts_service = lang_config.get("tts_service", "elevenlabs")
                text_to_process = data['text_results']['text_to_process']
                output_path = data['text_results']['output_path']
                
                temp_dir = os.path.join(output_path, "temp_chunks")
                os.makedirs(temp_dir, exist_ok=True)
                data['temp_dir'] = temp_dir
                
                if not lang_steps.get('audio'):
                    logger.info(f"Аудіо етап вимкнено для {lang_code}. Пропускаємо.")
                    continue
                
                # Розбиття тексту на фрагменти
                voicemaker_limit = self.config.get("voicemaker", {}).get("char_limit", 9900)
                text_chunks = []
                
                if tts_service == "voicemaker" and len(text_to_process) > voicemaker_limit:
                    text_chunks = chunk_text_voicemaker(text_to_process, voicemaker_limit)
                elif tts_service == "speechify" and len(text_to_process) > 16000:
                    text_chunks = chunk_text_speechify(text_to_process, 16000, num_parallel_chunks)
                else:
                    text_chunks = chunk_text(text_to_process, num_parallel_chunks)
                
                if not text_chunks:
                    logger.error(f"Текст для {lang_code} порожній після розбиття. Пропускаємо.")
                    continue
                
                # Зберігаємо інформацію про завдання
                task_chunks_info[str(task_key)] = {
                    'lang_code': lang_code,
                    'total_chunks': len(text_chunks),
                    'temp_dir': temp_dir,
                    'tts_service': tts_service,
                    'status_key': status_key,
                    'lang_steps': lang_steps,
                    'data': data
                }
                
                # Створюємо аудіо завдання для воркер пулу
                for i, chunk in enumerate(text_chunks):
                    audio_task = AudioPipelineItem(
                        text_chunk=chunk,
                        output_path=os.path.join(temp_dir, f"audio_chunk_{i}.mp3"),
                        lang_config=lang_config,
                        lang_code=lang_code,
                        chunk_index=i,
                        total_chunks=len(text_chunks),
                        task_key=str(task_key)
                    )
                    audio_tasks.append(audio_task)
                
                self.app.update_progress(f"{lang_code.upper()}: Додано {len(text_chunks)} аудіо завдань до черги...")
            
            # Додаємо всі аудіо завдання до воркер пулу
            for task in audio_tasks:
                self.audio_worker_pool.add_audio_task(task)
            
            logger.info(f"Додано {len(audio_tasks)} аудіо завдань до воркер пулу")
            
            # Моніторинг завершення завдань та гібридна обробка
            completed_tasks = set()
            total_tasks = len(task_chunks_info)
            last_check_time = time.time()
            
            while len(completed_tasks) < total_tasks and not self.app.shutdown_event.is_set():
                current_time = time.time()
                
                # Періодично запускаємо обробку готових груп для транскрипції
                if current_time - last_check_time >= 2.0:  # Кожні 2 секунди
                    # Визначаємо TTS сервіс для обробки груп
                    current_tts_service = self._get_current_tts_service(task_chunks_info)
                    if current_tts_service:
                        self.audio_worker_pool.process_ready_groups_for_transcription(current_tts_service)
                    last_check_time = current_time
                
                for task_key, info in task_chunks_info.items():
                    if task_key in completed_tasks:
                        continue
                    
                    # Перевіряємо чи завершено повністю (аудіо + транскрипція)
                    if self.audio_worker_pool.is_task_completed(task_key):
                        completed_tasks.add(task_key)
                        lang_code = info['lang_code']
                        status_key = info['status_key']
                        
                        # Отримуємо готові файли
                        audio_files = self.audio_worker_pool.get_completed_audio_for_task(task_key)
                        if audio_files:
                            # Обробка готових аудіо файлів (об'єднання якщо потрібно)
                            final_audio_chunks = self._process_completed_audio_chunks(
                                audio_files, info['tts_service'], info['temp_dir'], 
                                lang_code, num_parallel_chunks
                            )
                            
                            if final_audio_chunks:
                                info['data']['audio_chunks'] = sorted(final_audio_chunks)
                                
                                # Знаходимо відповідні субтитри
                                subs_dir = os.path.join(info['temp_dir'], "subs")
                                subs_files = sorted([
                                    os.path.join(subs_dir, f"subs_chunk_{i}.ass") 
                                    for i in range(len(final_audio_chunks))
                                    if os.path.exists(os.path.join(subs_dir, f"subs_chunk_{i}.ass"))
                                ])
                                
                                info['data']['subs_chunks'] = subs_files
                                
                                # Оновлюємо статус
                                if status_key in self.app.task_completion_status:
                                    audio_step_name = self.app._t('step_name_audio')
                                    subs_step_name = self.app._t('step_name_create_subtitles')
                                    
                                    if audio_step_name in self.app.task_completion_status[status_key]['steps']:
                                        self.app.task_completion_status[status_key]['steps'][audio_step_name] = "✅"
                                    
                                    if subs_step_name in self.app.task_completion_status[status_key]['steps']:
                                        if len(subs_files) == len(final_audio_chunks):
                                            self.app.task_completion_status[status_key]['steps'][subs_step_name] = "✅"
                                        else:
                                            self.app.task_completion_status[status_key]['steps'][subs_step_name] = "❌"
                                
                                logger.info(f"Завершено обробку аудіо та субтитрів для {lang_code}")
                            else:
                                logger.error(f"Помилка обробки аудіо файлів для {lang_code}")
                        
                        self.app.update_progress(f"Завершено: {len(completed_tasks)}/{total_tasks} завдань")
                
                # Перевіряємо shutdown_event частіше
                if self.app.shutdown_event.is_set():
                    logger.info("Отримано сигнал зупинки, переривання аудіо пайплайну...")
                    break
                    
                time.sleep(0.5)  # Коротка пауза перед наступною перевіркою
            
        finally:
            # Зупиняємо воркер пул
            if self.audio_worker_pool:
                self.audio_worker_pool.stop()
                self.audio_worker_pool = None
        
        logger.info("[Audio/Subs Master] Новий пайплайн завершено.")
    
    def _process_completed_audio_chunks(self, audio_files: list, tts_service: str, temp_dir: str, 
                                      lang_code: str, num_parallel_chunks: int) -> list:
        """Обробляє готові аудіо файли (об'єднання якщо потрібно)."""
        try:
            # Для voicemaker та speechify можливо потрібне об'єднання
            if (tts_service in ["voicemaker", "speechify"]) and len(audio_files) > num_parallel_chunks:
                logger.info(f"Об'єднання {len(audio_files)} {tts_service} аудіо файлів в {num_parallel_chunks} фінальних частин.")
                
                chunk_groups = np.array_split(audio_files, num_parallel_chunks)
                final_audio_chunks = []
                
                for i, group in enumerate(chunk_groups):
                    if len(group) == 0: 
                        continue
                    if len(group) == 1:
                        final_audio_chunks.append(group[0])
                    else:
                        merged_output_file = os.path.join(temp_dir, f"merged_chunk_{lang_code}_{i}.mp3")
                        if concatenate_audio_files(list(group), merged_output_file):
                            final_audio_chunks.append(merged_output_file)
                        else:
                            logger.error(f"Помилка об'єднання групи {tts_service} аудіо файлів для {lang_code}.")
                            return None
                
                return final_audio_chunks
            else:
                return sorted(audio_files)
                
        except Exception as e:
            logger.exception(f"Помилка обробки аудіо файлів: {e}")
            return None

    def _concatenate_videos(self, app_instance, video_chunks, output_path):
        """Об'єднання відеофрагментів."""
        return concatenate_videos(app_instance, video_chunks, output_path)

    def _video_chunk_worker(self, app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks):
        """Створення одного відеофрагменту."""
        from utils.media_utils import video_chunk_worker
        return video_chunk_worker(app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks)

    def _audio_worker(self, data):
        """Генерує ТІЛЬКИ аудіо для одного мовного завдання (для паралельного запуску)."""
        try:
            task = data['task']
            lang_code = data['text_results']['output_path'].split(os.sep)[-1].lower()
            lang_steps = task['steps'][lang_code]
            output_path = data['text_results']['output_path']
            text_to_process = data['text_results']['text_to_process']
            lang_config = self.app.config["languages"][lang_code]
            
            audio_path = os.path.join(output_path, "audio.mp3")

            if lang_steps.get('audio'):
                logger.info(f"[AudioWorker] Starting parallel audio generation for {lang_code}...")
                tts_service = lang_config.get("tts_service", "elevenlabs")
                if tts_service == "elevenlabs":
                    task_id = self.app.el_api.create_audio_task(text_to_process, lang_config.get("elevenlabs_template_uuid"))
                    if task_id and self.app.el_api.wait_for_elevenlabs_task(self.app, task_id, audio_path):
                        logger.info(f"[AudioWorker] ElevenLabs audio saved for {lang_code}.")
                        return audio_path
                elif tts_service == "voicemaker":
                    success, _ = self.app.vm_api.generate_audio(text_to_process, lang_config.get("voicemaker_voice_id"), lang_config.get("voicemaker_engine"), lang_code, audio_path)
                    if success:
                        return audio_path
            
            return None # Повертаємо None, якщо аудіо не створювалося або сталася помилка
        except Exception as e:
            logger.exception(f"Error in parallel audio worker: {e}")
            return None
        
    def _parallel_audio_master(self, processing_data):
        """Головний потік, що керує паралельною генерацією всіх аудіофайлів."""
        logger.info("[Image Control] Audio Master Thread: Starting parallel audio generation.")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            audio_futures = {}
            for task_key, data in processing_data.items():
                if data.get('text_results') and data['task']['steps'][task_key[1]].get('audio'):
                    future = executor.submit(self._audio_worker, data)
                    audio_futures[future] = task_key
            
            for future in concurrent.futures.as_completed(audio_futures):
                task_key = audio_futures[future]
                # Результат (шлях до аудіо) записується в загальний словник
                processing_data[task_key]['audio_path'] = future.result()
        logger.info("[Image Control] Audio Master Thread: All audio generation tasks complete.")

    def _get_current_tts_service(self, task_chunks_info: dict) -> str:
        """Визначає поточний TTS сервіс для обробки груп."""
        if not task_chunks_info:
            return "elevenlabs"  # За замовчуванням
        
        # Беремо перший доступний TTS сервіс з завдань
        for info in task_chunks_info.values():
            if 'tts_service' in info:
                return info['tts_service']
        
        return "elevenlabs"  # За замовчуванням
