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
        
        # Підрахунок загальної кількості кроків для прогрес-бару
        self.app.current_queue_step = 0
        
        # Скидаємо правильний прогрес-бар залежно від типу черги
        if is_rewrite:
            self.app.rewrite_progress_var.set(0)
        else:
            self.app.progress_var.set(0)
            
        total_steps = 0
        
        # Основні фази обробки
        if is_rewrite:
            total_steps += 1  # Phase 0: Transcription
        total_steps += 1  # Phase 1: Text processing
        total_steps += 1  # Phase 2: Media generation
        if self.config.get("ui_settings", {}).get("image_control_enabled", False):
            total_steps += 1  # Phase 3: Image control
        total_steps += 1  # Phase 4: Final montage
        
        self.app.total_queue_steps = total_steps
        logger.info(f"Запланованих кроків для прогрес-бару: {total_steps}")

        try:
            queue_to_process = list(queue_to_process_list)
            # НЕ очищуємо черги тут - вони будуть очищені після завершення
            # if is_rewrite:
            #     self.app.rewrite_task_queue.clear()
            #     self.app.update_rewrite_queue_display()
            # else:
            #     self.app.task_queue.clear()
            #     self.app.update_queue_display()
            
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
                self.app.update_progress(self.app._t('phase_0_transcription'), increment_step=True, queue_type=queue_type)
                logger.info("Hybrid mode -> Phase 0: Sequential transcription of local files.")
                
                # Встановлюємо статус "в процесі" для транскрипції всіх завдань
                step_name_key = self.app._t('step_name_transcribe')
                for task_index, task in enumerate(queue_to_process):
                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status:
                            # Встановлюємо статус транскрипції
                            if step_name_key in self.app.task_completion_status[status_key]['steps']:
                                self.app.task_completion_status[status_key]['steps'][step_name_key] = "В процесі"
                            
                            # Ініціалізуємо всі інші кроки як "Очікує" якщо вони не встановлені
                            for step_name, step_status in self.app.task_completion_status[status_key]['steps'].items():
                                if step_status == "Очікує" and step_name != step_name_key:
                                    # Залишаємо як "Очікує", але оновлюємо відображення
                                    pass
                
                # Ініціалізуємо лічільники для транскрипції рерайту
                unique_files = set(task['mp3_path'] for task in queue_to_process)
                total_files_count = len(unique_files)
                for task_index, task in enumerate(queue_to_process):
                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status:
                            self.app.task_completion_status[status_key]['total_files'] = total_files_count
                            self.app.task_completion_status[status_key]['transcribed_files'] = 0
                
                # Оновлюємо відображення
                self.app.root.after(0, self.app.update_rewrite_task_status_display)
                
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
                        
                        # Оновлюємо лічільник транскрибованих файлів для всіх завдань з цим файлом
                        for task_check in queue_to_process:
                            if task_check['mp3_path'] == mp3_path:
                                task_idx_check = task_check['task_index']
                                for lang_code_check in task_check['selected_langs']:
                                    status_key_check = self._get_status_key(task_idx_check, lang_code_check, is_rewrite)
                                    if status_key_check in self.app.task_completion_status:
                                        self.app.task_completion_status[status_key_check]['transcribed_files'] += 1
                        
                        # Оновлюємо відображення після кожного файлу
                        self.app.root.after(0, self.app.update_rewrite_task_status_display)

                for task in queue_to_process:
                    if task['mp3_path'] in transcribed_texts:
                        task['transcribed_text'] = transcribed_texts[task['mp3_path']]['text']
                        task['video_title'] = transcribed_texts[task['mp3_path']]['title']
                        
                        # Оновлюємо статус транскрипції для всіх мов у цьому завданні
                        task_idx_str = task['task_index']
                        step_name_key = self.app._t('step_name_transcribe')
                        for lang_code in task['selected_langs']:
                            status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                            if status_key in self.app.task_completion_status and step_name_key in self.app.task_completion_status[status_key]['steps']:
                                self.app.task_completion_status[status_key]['steps'][step_name_key] = "Готово"
                
                # Оновлюємо відображення після завершення транскрипції
                if is_rewrite:
                    self.app.root.after(0, self.app.update_rewrite_task_status_display)
                else:
                    self.app.root.after(0, self.app.update_task_status_display)


            # Phase 1: Parallel text processing
            self.app.update_progress(self.app._t('phase_1_text_processing'), increment_step=True, queue_type=queue_type)
            logger.info(f"Hybrid mode -> Phase 1: Parallel text processing for {len(queue_to_process)} tasks.")
            
            # Встановлюємо статус "в процесі" для обробки тексту
            text_step_names = ['rewrite_text', 'gen_text'] if is_rewrite else ['gen_text']
            for step_name in text_step_names:
                step_name_key = self.app._t('step_name_' + step_name)
                for task_index, task in enumerate(queue_to_process):
                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status and step_name_key in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key] = "В процесі"
            
            # Оновлюємо відображення
            if is_rewrite:
                self.app.root.after(0, self.app.update_rewrite_task_status_display)
            else:
                self.app.root.after(0, self.app.update_task_status_display)
            
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
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)

                if status_key in self.app.task_completion_status:
                    if data.get('text_results'):
                        # Відмічаємо успішність текстових етапів
                        if is_rewrite:
                            steps_to_mark = ['rewrite_text', 'gen_text', 'cta', 'gen_prompts']
                        else:
                            steps_to_mark = ['gen_text', 'cta', 'gen_prompts']
                        for step in steps_to_mark:
                            step_name_key = self.app._t('step_name_' + step)
                            if step_name_key in self.app.task_completion_status[status_key]['steps']:
                                self.app.task_completion_status[status_key]['steps'][step_name_key] = "Готово"
                        
                        # Зберігаємо загальну кількість запланованих зображень
                        num_prompts = len(data['text_results'].get("prompts", []))
                        self.app.task_completion_status[status_key]["total_images"] = num_prompts
                    else:
                        # Якщо текстовий етап провалився, відмічаємо всі наступні як провалені
                        for step_name in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"

            # Оновлюємо відображення після завершення обробки тексту
            if is_rewrite:
                self.app.root.after(0, self.app.update_rewrite_task_status_display)
            else:
                self.app.root.after(0, self.app.update_task_status_display)


            # --- ЕТАП 2: ОДНОЧАСНА ГЕНЕРАЦІЯ МЕДІА ---
            self.app.update_progress(self.app._t('phase_2_media_generation'), increment_step=True, queue_type=queue_type)
            logger.info("Гібридний режим -> Етап 2: Одночасна генерація медіа.")
            
            self.app.root.after(0, self.app.setup_empty_gallery, queue_type, queue_to_process)
            
            should_gen_images = any(
                data.get('text_results') and data['task']['steps'][key[1]].get('gen_images')
                for key, data in processing_data.items()
            )

            if should_gen_images:
                image_master_thread = threading.Thread(target=self._sequential_image_master, args=(processing_data, queue_to_process, queue_type, is_rewrite))
                image_master_thread.start()
            else:
                image_master_thread = None
                logger.info("Hybrid mode -> Image generation disabled for all tasks. Skipping.")

            audio_subs_master_thread = threading.Thread(target=self._audio_subs_pipeline_master, args=(processing_data, is_rewrite, queue_type))
            audio_subs_master_thread.start()
            
            if image_master_thread:
                image_master_thread.join()
            audio_subs_master_thread.join()
            
            logger.info("Гібридний режим -> Етап 2: Генерацію всіх медіафайлів завершено.")
            
            # --- ЕТАП 3: ОПЦІОНАЛЬНА ПАУЗА ---
            if self.config.get("ui_settings", {}).get("image_control_enabled", False):
                self.app.update_progress(self.app._t('phase_3_image_control'), increment_step=True, queue_type=queue_type)
                
                def show_pause_notification():
                    messagebox.showinfo(
                        "Процес призупинено",
                        "Всі підготовчі етапи завершено!\n\n"
                        "Будь ласка, перегляньте галерею зображень та внесіть правки.\n\n"
                        "Натисніть 'Продовжити монтаж', щоб зібрати фінальні відео."
                    )
                self.app.root.after(0, show_pause_notification)

                if should_gen_images:
                    logger.info("Гібридний режим -> Етап 3: Пауза для налаштування зображень користувачем.")
                    message_text = "🎨 *Контроль зображень*\n\nВсі зображення згенеровано\\. Будь ласка, перегляньте та відредагуйте їх у програмі, перш ніж продовжити монтаж\\."
                else:
                    logger.info("Гібридний режим -> Етап 3: Пауза для контролю перед монтажем (без генерації зображень).")
                    message_text = "🎬 *Готовність до монтажу*\n\nВсі підготовчі етапи завершено\\. Натисніть кнопку для продовження монтажу\\."
                
                logger.info("WORKFLOW PAUSED. Waiting for user to press 'Continue Montage' button...")
                
                # Відправляємо статус готовності до монтажу в Firebase
                if self.firebase_api and self.firebase_api.is_initialized:
                    self.firebase_api.send_montage_ready_status()
                
                # Надсилаємо повідомлення в Telegram
                if self.tg_api and self.tg_api.enabled:
                    self.tg_api.send_message_with_buttons(
                        message=message_text,
                        buttons=[
                            {"text": "✅ Продовжити монтаж", "callback_data": "continue_montage_action"}
                        ]
                    )

                logger.info("Starting wait for user confirmation on 'Continue Montage' button...")
                self.app.image_control_active.wait() # Чекаємо на команду
                logger.info("WORKFLOW RESUMED after user confirmation.")
            else:
                logger.info("Гібридний режим -> Етап 3: Пауза вимкнена, перехід до монтажу.")

            # Phase 4: Final montage and language reports
            self.app.update_progress(self.app._t('phase_4_final_montage'), increment_step=True, queue_type=queue_type)
            logger.info("Hybrid mode -> Phase 4: Starting final montage and language reports.")
            logger.info(f"Processing data keys for montage: {list(processing_data.keys())}")

            for task_key, data in sorted(processing_data.items()):
                lang_code = task_key[1]
                task_idx_str = task_key[0]
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                
                logger.info(f"Checking montage requirements for task {task_key}:")
                logger.info(f"  - has task: {bool(data.get('task'))}")
                logger.info(f"  - has text_results: {bool(data.get('text_results'))}")
                logger.info(f"  - create_video enabled: {data.get('task', {}).get('steps', {}).get(lang_code, {}).get('create_video', False) if data.get('task') else False}")
                
                if data.get('task') and data.get('text_results') and data['task']['steps'][lang_code].get('create_video'):
                    
                    images_folder = data['text_results']['images_folder']
                    all_images = sorted([os.path.join(images_folder, f) for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                    
                    # Детальне логування для діагностики
                    logger.info(f"Video montage detailed check for task {task_key}:")
                    logger.info(f"  - audio_chunks present: {bool(data.get('audio_chunks'))}")
                    logger.info(f"  - audio_chunks count: {len(data.get('audio_chunks', []))}")
                    logger.info(f"  - subs_chunks present: {bool(data.get('subs_chunks'))}")
                    logger.info(f"  - subs_chunks count: {len(data.get('subs_chunks', []))}")
                    logger.info(f"  - images_folder: {images_folder}")
                    logger.info(f"  - images found: {len(all_images)}")
                    
                    if not data.get('audio_chunks') or not data.get('subs_chunks'):
                        logger.error(f"ПРОБЛЕМА: Audio або subtitles відсутні для завдання {task_key}. Пропускаємо монтаж відео.")
                        logger.error(f"  - audio_chunks: {data.get('audio_chunks')}")
                        logger.error(f"  - subs_chunks: {data.get('subs_chunks')}")
                        if status_key in self.app.task_completion_status:
                            step_name = self.app._t('step_name_create_video')
                            self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"
                        continue
                else:
                    logger.warning(f"Завдання {task_key} не відповідає умовам для монтажу:")
                    logger.warning(f"  - має task: {bool(data.get('task'))}")
                    logger.warning(f"  - має text_results: {bool(data.get('text_results'))}")
                    if data.get('task'):
                        logger.warning(f"  - create_video enabled: {data['task']['steps'][lang_code].get('create_video', False)}")
                    continue

                # Перевірка наявності зображень (має бути після основного if, не в else!)
                if not all_images:
                    logger.error(f"Зображення не знайдено для завдання {task_key}. Пропускаємо монтаж відео.")
                    if status_key in self.app.task_completion_status:
                        step_name = self.app._t('step_name_create_video')
                        self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"

                # Встановлюємо статус "в процесі" для створення відео
                if status_key in self.app.task_completion_status:
                    step_name = self.app._t('step_name_create_video')
                    if step_name in self.app.task_completion_status[status_key]['steps']:
                        self.app.task_completion_status[status_key]['steps'][step_name] = "В процесі"
                        if is_rewrite:
                            self.app.root.after(0, self.app.update_rewrite_task_status_display)
                        else:
                            self.app.root.after(0, self.app.update_task_status_display)

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
                            os.path.join(data['temp_dir'], f"video_chunk_{i:02d}.mp4"),  # zfill для правильного сортування
                            i + 1, len(data['audio_chunks'])
                        ): i for i in range(len(data['audio_chunks']))
                    }
                    
                    # Збираємо результати з правильним індексом для гарантованого порядку
                    video_results = {}
                    for f in concurrent.futures.as_completed(video_futures):
                        chunk_index = video_futures[f]
                        result = f.result()
                        if result: 
                            video_results[chunk_index] = result
                            
                    # Формуємо список в правильному хронологічному порядку
                    video_chunk_paths = [video_results[i] for i in range(len(data['audio_chunks'])) if i in video_results]

                if len(video_chunk_paths) == len(data['audio_chunks']):
                    if 'video_title' in data['text_results']:
                        base_name = sanitize_filename(data['text_results']['video_title'])
                    else:
                        base_name = sanitize_filename(data['text_results'].get('task_name', f"Task_{task_key[0]}"))
                    
                    final_video_path = os.path.join(data['text_results']['output_path'], f"video_{base_name}_{lang_code}.mp4")
                    if self._concatenate_videos(self.app, video_chunk_paths, final_video_path):  # Вже в правильному порядку
                        logger.info(f"УСПІХ: Створено фінальне відео: {final_video_path}")
                        if status_key in self.app.task_completion_status:
                            step_name = self.app._t('step_name_create_video')
                            self.app.task_completion_status[status_key]['steps'][step_name] = "Готово"
                            if is_rewrite:
                                self.app.root.after(0, self.app.update_rewrite_task_status_display)
                            else:
                                self.app.root.after(0, self.app.update_task_status_display)
                        if is_rewrite:
                            self.app.save_processed_link(data['task']['original_filename'])
                    else:
                         if status_key in self.app.task_completion_status:
                            step_name = self.app._t('step_name_create_video')
                            self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"
                            if is_rewrite:
                                self.app.root.after(0, self.app.update_rewrite_task_status_display)
                            else:
                                self.app.root.after(0, self.app.update_task_status_display)
                else:
                    logger.error(f"ПОМИЛКА: Не вдалося створити всі частини відео для завдання {task_key}.")
                    if status_key in self.app.task_completion_status:
                        step_name = self.app._t('step_name_create_video')
                        self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"
                
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
            
            # Встановлюємо прогрес-бар на 100% після завершення
            if is_rewrite:
                self.app.root.after(0, lambda: self.app.rewrite_progress_var.set(100))
            else:
                self.app.root.after(0, lambda: self.app.progress_var.set(100))
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

    def _text_processing_worker(self, task, lang_code):
        """Execute all text operations for a single language task."""
        try:
            # Встановлюємо статус "В процесі" для генерації тексту
            task_index = task['task_index']
            status_key = f"{task_index}_{lang_code}"
            if status_key in self.app.task_completion_status:
                step_name_key = self.app._t('step_name_gen_text')
                if step_name_key in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name_key] = "В процесі"
                    self.app.root.after(0, self.app.update_task_status_display)
            
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
            # Встановлюємо статус "В процесі" для рерайту тексту
            task_index = task['task_index']
            status_key = f"rewrite_{task_index}_{lang_code}"
            if status_key in self.app.task_completion_status:
                step_name_key = self.app._t('step_name_rewrite_text')
                if step_name_key in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name_key] = "В процесі"
                    self.app.root.after(0, self.app.update_rewrite_task_status_display)
            
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
            
            # Динамічно оновлюємо статус рерайту
            task_index = task['task_index']
            status_key = f"rewrite_{task_index}_{lang_code}"
            if status_key in self.app.task_completion_status:
                step_name_key = self.app._t('step_name_rewrite_text')
                if step_name_key in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name_key] = "Готово"
                    self.app.root.after(0, self.app.update_rewrite_task_status_display)
            
            # CTA та промти
            cta_path = os.path.join(lang_output_path, "call_to_action.txt")
            prompts_path = os.path.join(lang_output_path, "image_prompts.txt")

            # Генерація CTA або читання з файлу
            if task['steps'][lang_code]['cta']:
                cta_text = self.or_api.generate_call_to_action(rewritten_text, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"])
                if cta_text:
                    with open(cta_path, 'w', encoding='utf-8') as f: f.write(cta_text)
                    
                    # Динамічно оновлюємо статус CTA
                    if status_key in self.app.task_completion_status:
                        step_name_key = self.app._t('step_name_cta')
                        if step_name_key in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key] = "Готово"
                            self.app.root.after(0, self.app.update_rewrite_task_status_display)

            # Генерація промтів або читання з файлу
            raw_prompts = None
            if task['steps'][lang_code]['gen_prompts']:
                raw_prompts = self.or_api.generate_image_prompts(rewritten_text, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"])
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
                    
                    # Динамічно оновлюємо статус генерації промптів
                    if status_key in self.app.task_completion_status:
                        step_name_key = self.app._t('step_name_gen_prompts')
                        if step_name_key in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key] = "Готово"
                            self.app.root.after(0, self.app.update_rewrite_task_status_display)
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
                    # Тепер ми перевіряємо, чи були згенеровані якісь зображення
                    if self.app.task_completion_status[status_key]["images_generated"] > 0:
                        self.app.task_completion_status[status_key]['steps'][step_name] = "Готово"
                    else:
                        # Якщо жодного зображення не згенеровано, вважаємо крок проваленим
                        self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"
            else:
                if status_key in self.app.task_completion_status and step_name in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name] = "Пропущено" # Mark as skipped, not failed

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
        
        # Встановлюємо статус "в процесі" для аудіо та субтитрів
        for task_key, data in processing_data.items():
            if data.get('text_results'):
                task_idx_str, lang_code = task_key
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                if status_key in self.app.task_completion_status:
                    # Встановлюємо статус "в процесі" для аудіо
                    audio_step = self.app._t('step_name_audio')
                    if audio_step in self.app.task_completion_status[status_key]['steps']:
                        self.app.task_completion_status[status_key]['steps'][audio_step] = "В процесі"
                    
                    # Встановлюємо статус "в процесі" для субтитрів
                    subs_step = self.app._t('step_name_create_subtitles')
                    if subs_step in self.app.task_completion_status[status_key]['steps']:
                        self.app.task_completion_status[status_key]['steps'][subs_step] = "В процесі"
                    
                    # Ініціалізуємо лічільники для аудіо файлів
                    num_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)
                    self.app.task_completion_status[status_key]['audio_generated'] = 0
                    self.app.task_completion_status[status_key]['total_audio'] = num_chunks
                    # Ініціалізуємо лічільники для субтитрів (прив'язані до аудіо)
                    self.app.task_completion_status[status_key]['subs_generated'] = 0
                    self.app.task_completion_status[status_key]['total_subs'] = num_chunks
        
        # Оновлюємо відображення
        if is_rewrite:
            self.app.root.after(0, self.app.update_rewrite_task_status_display)
        else:
            self.app.root.after(0, self.app.update_task_status_display)
        
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
                else: # ElevenLabs та короткі тексти
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
            while completed_audio_count < total_audio_chunks_expected and not self.app.shutdown_event.is_set():
                try:
                    result = self.audio_worker_pool.audio_results_queue.get(timeout=1.0)
                    completed_audio_count += 1
                    
                    if not result.success:
                        logger.error(f"Помилка генерації аудіо для {result.item.task_key}, фрагмент {result.item.chunk_index}. Пропускаємо.")
                        continue

                    task_key = result.item.task_key
                    task_info = tasks_info[task_key]
                    task_info['completed_audio_items'].append(result.item)

                    self.app.update_progress(f"Озвучка: {completed_audio_count}/{total_audio_chunks_expected}", queue_type=queue_type)

                    if task_info['tts_service'] != 'voicemaker':
                        # Всі інші сервіси відправляємо на транскрипцію відразу
                        trans_item = TranscriptionPipelineItem(
                            audio_path=result.item.output_path, output_dir=os.path.dirname(result.item.output_path),
                            chunk_index=result.item.chunk_index, lang_code=result.item.lang_code, task_key=task_key
                        )
                        self.audio_worker_pool.add_transcription_task(trans_item)
                    elif len(task_info['completed_audio_items']) == task_info['total_chunks']:
                        # Voicemaker: чекаємо, поки зберуться всі частини
                        logger.info(f"Всі {task_info['total_chunks']} частин для {task_key} (Voicemaker) готові. Починаю об'єднання.")
                        
                        sorted_items = sorted(task_info['completed_audio_items'], key=lambda x: x.chunk_index)
                        audio_paths_to_merge = [item.output_path for item in sorted_items]
                        groups = np.array_split(audio_paths_to_merge, num_parallel_chunks)
                        
                        # Нова логіка, щоб залишок йшов в останню групу
                        n = len(audio_paths_to_merge)
                        k = num_parallel_chunks
                        
                        groups = []
                        if n > 0 and k > 0:
                            base_size = n // k
                            
                            start_index = 0
                            # Перші k-1 груп
                            for _ in range(k - 1):
                                end_index = start_index + base_size
                                group = audio_paths_to_merge[start_index:end_index]
                                if group: groups.append(group)
                                start_index = end_index
                            
                            # Остання група отримує все, що залишилось
                            last_group = audio_paths_to_merge[start_index:]
                            if last_group: groups.append(last_group)
                        
                        for i, group in enumerate(groups):
                            if not group.any(): continue
                            
                            merged_path = os.path.join(task_info['data']['temp_dir'], f"merged_chunk_{i}.mp3")
                            if len(group) > 1:
                                if not concatenate_audio_files(list(group), merged_path):
                                    logger.error(f"Не вдалося об'єднати групу {i} для {task_key}")
                                    continue
                            else:
                                shutil.copy(group[0], merged_path)
                            
                            trans_item = TranscriptionPipelineItem(
                                audio_path=merged_path, output_dir=os.path.dirname(merged_path),
                                chunk_index=i, lang_code=result.item.lang_code,
                                task_key=task_key, is_merged_group=True
                            )
                            self.audio_worker_pool.add_transcription_task(trans_item)
                except queue.Empty:
                    continue
            
            # 3. Збираємо результати транскрипції
            total_transcriptions_expected = 0
            for tk, info in tasks_info.items():
                if info['tts_service'] == 'voicemaker':
                    total_transcriptions_expected += min(info['total_chunks'], num_parallel_chunks)
                else:
                    total_transcriptions_expected += info['total_chunks']
            
            logger.info(f"Очікується {total_transcriptions_expected} результатів транскрипції.")
            completed_transcriptions = 0
            while completed_transcriptions < total_transcriptions_expected and not self.app.shutdown_event.is_set():
                try:
                    result_item = self.transcription_results_queue.get(timeout=1.0)
                    task_key = result_item.task_key
                    info = tasks_info[task_key]

                    if 'subs_chunks' not in info['data']: info['data']['subs_chunks'] = []
                    if 'audio_chunks' not in info['data']: info['data']['audio_chunks'] = []

                    if result_item.subs_path:
                        info['data']['subs_chunks'].append(result_item.subs_path)
                        info['data']['audio_chunks'].append(result_item.audio_path)
                        
                        # Динамічно оновлюємо лічільники аудіо та субтитрів файлів
                        task_key = result_item.task_key
                        if isinstance(task_key, tuple) and len(task_key) >= 2:
                            task_idx_str, lang_code = task_key[0], task_key[1]
                        else:
                            continue  # Пропускаємо якщо структура незрозуміла
                        
                        status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status:
                            # Оновлюємо лічільники
                            self.app.task_completion_status[status_key]['audio_generated'] = len(info['data']['audio_chunks'])
                            self.app.task_completion_status[status_key]['subs_generated'] = len(info['data']['subs_chunks'])
                            # Оновлюємо відображення
                            if is_rewrite:
                                self.app.root.after(0, self.app.update_rewrite_task_status_display)
                            else:
                                self.app.root.after(0, self.app.update_task_status_display)
                    
                    completed_transcriptions += 1
                    self.app.update_progress(f"Транскрипція: {completed_transcriptions}/{total_transcriptions_expected}", queue_type=queue_type)

                except queue.Empty:
                    continue

            # Сортуємо результати для правильного порядку монтажу
            for tk, info in tasks_info.items():
                info['data']['subs_chunks'].sort()
                info['data']['audio_chunks'].sort()
                
                # Встановлюємо фінальний статус для аудіо та субтитрів
                task_idx_str, lang_code = eval(tk)
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                if status_key in self.app.task_completion_status:
                    # Перевіряємо чи всі аудіо та субтитри завершені успішно
                    has_audio = len(info['data'].get('audio_chunks', [])) > 0
                    has_subs = len(info['data'].get('subs_chunks', [])) > 0
                    
                    # Оновлюємо лічільник аудіо файлів
                    if has_audio:
                        self.app.task_completion_status[status_key]['audio_generated'] = len(info['data'].get('audio_chunks', []))
                    
                    # Встановлюємо статус для аудіо
                    audio_step = self.app._t('step_name_audio')
                    if audio_step in self.app.task_completion_status[status_key]['steps']:
                        self.app.task_completion_status[status_key]['steps'][audio_step] = "Готово" if has_audio else "Помилка"
                    
                    # Встановлюємо статус для субтитрів
                    subs_step = self.app._t('step_name_create_subtitles')
                    if subs_step in self.app.task_completion_status[status_key]['steps']:
                        self.app.task_completion_status[status_key]['steps'][subs_step] = "Готово" if has_subs else "Помилка"
            
            # Оновлюємо відображення
            if is_rewrite:
                self.app.root.after(0, self.app.update_rewrite_task_status_display)
            else:
                self.app.root.after(0, self.app.update_task_status_display)

        finally:
            if self.audio_worker_pool:
                self.audio_worker_pool.stop()

    def _concatenate_videos(self, app_instance, video_chunks, output_path):
        """Об'єднання відеофрагментів."""
        return concatenate_videos(app_instance, video_chunks, output_path)

    def _video_chunk_worker(self, app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks):
        """Створення одного відеофрагменту."""
        from utils.media_utils import video_chunk_worker
        return video_chunk_worker(app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks)
