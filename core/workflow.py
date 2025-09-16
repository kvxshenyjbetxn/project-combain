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
import shutil
import yt_dlp

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
        self.app.is_processing_queue = True
        self.app._update_button_states(is_processing=True, is_image_stuck=False)
        if hasattr(self.app, 'pause_resume_button'):
            self.app.root.after(0, lambda: self.app.pause_resume_button.config(state="normal"))

        try:
            queue_to_process = list(unified_queue)

            # Ініціалізуємо статуси для ВСІХ завдань ОДИН РАЗ на початку
            self.app.task_completion_status = {}
            for i, task in enumerate(queue_to_process):
                task['task_index'] = i  # Присвоюємо глобальний індекс
                is_rewrite = task.get('type') == 'Rewrite'
                for lang_code in task['selected_langs']:
                    task_key = self._get_status_key(i, lang_code, is_rewrite)
                    
                    # Визначаємо правильні ключі для кроків
                    step_keys = []
                    if is_rewrite:
                        # Для рерайту додаємо унікальні кроки першими
                        if task['steps'][lang_code].get('download'): step_keys.append('download')
                        if task['steps'][lang_code].get('transcribe'): step_keys.append('transcribe')
                        if task['steps'][lang_code].get('rewrite'): step_keys.append('rewrite')
                    else: # Translate
                        if task['steps'][lang_code].get('translate'): step_keys.append('translate')

                    # Додаємо спільні кроки
                    common_steps = ['cta', 'gen_prompts', 'gen_images', 'audio', 'create_subtitles', 'create_video']
                    for step in common_steps:
                        if task['steps'][lang_code].get(step):
                            step_keys.append(step)

                    # Створюємо словник статусів
                    self.app.task_completion_status[task_key] = {
                        "task_name": task.get('task_name'),
                        "steps": {self.app._t('step_name_' + step_name): "Очікує" for step_name in step_keys},
                        "images_generated": 0,
                        "total_images": 0
                    }
            
            # Оновлюємо відображення в GUI з початковими статусами "Очікує"
            self.app.root.after(0, self.app.update_queue_display)

            # НОВИЙ ПІДХІД: спочатку всі підготовчі етапи для всіх завдань, потім монтаж
            self._process_all_preparation_phases(queue_to_process)
            
            # Перевірка контролю зображень перед монтажем
            if self.config.get("ui_settings", {}).get("image_control_enabled", False):
                self.app.root.after(0, lambda: messagebox.showinfo("Процес призупинено", "Всі підготовчі етапи завершено!\n\nПерегляньте галерею та натисніть 'Продовжити монтаж'."))
                if self.firebase_api and self.firebase_api.is_initialized: 
                    self.firebase_api.send_montage_ready_status()
                logger.info("WORKFLOW PAUSED. Waiting for user to press 'Continue Montage' button...")
                self.app.image_control_active.wait()
                logger.info("WORKFLOW RESUMED after user confirmation.")
            
            # Тепер виконуємо монтаж для всіх завдань
            self._process_all_montage_phase(queue_to_process)
            
            if self.app._check_app_state():
                logger.info("Обробку всіх завдань у єдиній черзі завершено.")
                self.app.root.after(0, lambda: messagebox.showinfo(self.app._t('queue_title'), self.app._t('info_queue_complete')))

        except Exception as e:
            logger.exception(f"CRITICAL ERROR: Unexpected error in unified queue processing: {e}")
            self.app.root.after(0, lambda: messagebox.showerror(self.app._t('error_title'), self.app._t('error_unexpected_queue')))
        finally:
            self.app.is_processing_queue = False
            self.app._update_button_states(is_processing=False, is_image_stuck=False)
            self.app.root.after(0, self.app.update_queue_display)
            if hasattr(self.app, 'pause_resume_button'):
                self.app.root.after(0, lambda: self.app.pause_resume_button.config(text=self.app._t('pause_button'), state="disabled"))
            self.app.pause_event.set()

    def _process_all_preparation_phases(self, queue_to_process):
        """Виконує всі підготовчі етапи для всіх завдань (переклад, рерайт, заклик до дії, промпти, озвучка, субтитри, картинки)"""
        logger.info("Початок виконання всіх підготовчих етапів для всіх завдань...")
        
        if self.firebase_api.is_initialized:
            self.app.stop_command_listener.clear()
            self.firebase_api.clear_commands()
            self.firebase_api.clear_montage_ready_status()
            
            if self.config.get("firebase", {}).get("auto_clear_gallery", True):
                self.firebase_api.clear_images()
                logger.info("Auto-cleared old gallery images from Firebase for new generation session")
            
            self.app.command_listener_thread = threading.Thread(target=self.app._command_listener_worker, daemon=True)
            self.app.command_listener_thread.start()
            self.app.root.after(100, self.app._process_command_queue)

        self.app._update_button_states(is_processing=True, is_image_stuck=False)
        self.app.image_control_active.clear()

        # Розрахунок загальних кроків для всіх завдань
        self.app.completed_individual_steps = 0
        self.app.total_individual_steps = 0
        num_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)
        
        for task in queue_to_process:
            is_rewrite = task.get('type') == 'Rewrite'
            
            if is_rewrite:
                first_lang_steps = task['steps'][task['selected_langs'][0]]
                if task.get('source_type') == 'url' and first_lang_steps.get('download'):
                    self.app.total_individual_steps += 1
                if first_lang_steps.get('transcribe'):
                    self.app.total_individual_steps += 1

            for lang_code in task['selected_langs']:
                steps = task['steps'][lang_code]
                
                main_step = 'rewrite' if is_rewrite else 'translate'
                if steps.get(main_step): self.app.total_individual_steps += 1
                
                common_steps = ['cta', 'gen_prompts', 'gen_images', 'audio', 'create_subtitles']
                for step in common_steps:
                    if steps.get(step):
                        if step in ['audio', 'create_subtitles']:
                            # Розраховуємо фактичну кількість частин для аудіо/субтитрів
                            lang_config = self.config["languages"][lang_code]
                            tts_service = lang_config.get("tts_service", "elevenlabs")
                            
                            if tts_service == "voicemaker":
                                # Для Voicemaker потрібно розрахувати реальну кількість частин на основі тексту
                                text_to_process = task.get('input_text', '')
                                if is_rewrite and 'transcribed_text' in task:
                                    text_to_process = task['transcribed_text']
                                
                                voicemaker_limit = self.config.get("voicemaker", {}).get("char_limit", 2900)
                                if len(text_to_process) > voicemaker_limit:
                                    text_chunks = chunk_text_voicemaker(text_to_process, voicemaker_limit)
                                    actual_chunks = len(text_chunks)
                                    # Для субтитрів Voicemaker використовує num_chunks груп після злиття
                                    if step == 'create_subtitles':
                                        self.app.total_individual_steps += min(num_chunks, actual_chunks)
                                    else:  # audio
                                        self.app.total_individual_steps += actual_chunks
                                else:
                                    self.app.total_individual_steps += 1
                            else:
                                # Для інших TTS сервісів використовуємо стандартну логіку
                                self.app.total_individual_steps += num_chunks
                        else: # gen_images, cta, gen_prompts
                            self.app.total_individual_steps += 1

        logger.info(f"Загальна кількість підготовчих кроків для всіх завдань: {self.app.total_individual_steps}")
        self.app.update_individual_progress('main')

        # Обробляємо завдання послідовно для підготовчих етапів
        all_processing_data = {}
        
        for task in queue_to_process:
            is_rewrite = task.get('type') == 'Rewrite'
            queue_type = 'rewrite' if is_rewrite else 'main'
            
            try:
                # Етап 0: Завантаження та транскрипція (тільки для rewrite)
                if is_rewrite:
                    logger.info(f"Етап 0: Завантаження та транскрипція для завдання '{task.get('task_name')}'")
                    self._process_transcription_phase(task)

                # Етап 1: Обробка тексту (переклад/рерайт, CTA, промпти)
                logger.info(f"Етап 1: Обробка тексту для завдання '{task.get('task_name')}'")
                task_processing_data = self._process_text_phase(task, is_rewrite, queue_type)
                
                # Зберігаємо дані для подальшого використання в монтажі
                for task_key, data in task_processing_data.items():
                    all_processing_data[task_key] = data

            except Exception as e:
                logger.exception(f"Помилка при обробці підготовчих етапів для завдання {task.get('task_name')}: {e}")

        # Етап 2: Генерація зображень та аудіо/субтитрів для всіх завдань паралельно
        logger.info("Етап 2: Генерація зображень та аудіо/субтитрів для всіх завдань")
        self._process_media_generation_phase(all_processing_data, queue_to_process)
        
        # Зберігаємо дані для монтажу
        self.all_processing_data = all_processing_data
        logger.info("Всі підготовчі етапи завершено!")

    def _process_transcription_phase(self, task):
        """Обробляє завантаження та транскрипцію для rewrite завдань"""
        task_index = task['task_index']
        step_name_key_transcribe = self.app._t('step_name_transcribe')
        step_name_key_download = self.app._t('step_name_download')

        if task.get('source_type') == 'url':
            for lang_code in task['selected_langs']:
                status_key = self._get_status_key(task_index, lang_code, True)
                if status_key in self.app.task_completion_status and step_name_key_download in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name_key_download] = "В процесі"
            self.app.root.after(0, self.app.update_task_status_display)
            
            result_path = self._video_download_worker(task)
            task['mp3_path'] = result_path
            
            for lang_code in task['selected_langs']:
                status_key = self._get_status_key(task_index, lang_code, True)
                if status_key in self.app.task_completion_status and step_name_key_download in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name_key_download] = "Готово" if result_path else "Помилка"
            if result_path: self.app.increment_and_update_progress('rewrite')
            self.app.root.after(0, self.app.update_task_status_display)
        
        if 'mp3_path' in task and task['mp3_path']:
            for lang_code in task['selected_langs']:
                status_key = self._get_status_key(task_index, lang_code, True)
                if status_key in self.app.task_completion_status and step_name_key_transcribe in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name_key_transcribe] = "В процесі"
            self.app.root.after(0, self.app.update_task_status_display)

            mp3_path = task['mp3_path']
            original_filename = task.get('original_filename', os.path.basename(mp3_path))
            video_title = sanitize_filename(os.path.splitext(original_filename)[0])
            task_output_dir = os.path.join(self.config['output_settings']['rewrite_default_dir'], video_title)
            os.makedirs(task_output_dir, exist_ok=True)
            original_transcript_path = os.path.join(task_output_dir, "original_transcript.txt")
            
            if os.path.exists(original_transcript_path):
                with open(original_transcript_path, "r", encoding='utf-8') as f:
                    transcribed_text = f.read()
            else:
                model = self.montage_api._load_whisper_model()
                if not model: return
                transcription_result = model.transcribe(mp3_path, verbose=False)
                transcribed_text = transcription_result['text']
                with open(original_transcript_path, "w", encoding='utf-8') as f: f.write(transcribed_text)

            task['transcribed_text'] = transcribed_text
            task['video_title'] = video_title
            self.app.increment_and_update_progress('rewrite')

            for lang_code in task['selected_langs']:
                status_key = self._get_status_key(task_index, lang_code, True)
                if status_key in self.app.task_completion_status and step_name_key_transcribe in self.app.task_completion_status[status_key]['steps']:
                    self.app.task_completion_status[status_key]['steps'][step_name_key_transcribe] = "Готово"
            self.app.root.after(0, self.app.update_task_status_display)

    def _process_text_phase(self, task, is_rewrite, queue_type):
        """Обробляє текстові етапи для одного завдання (переклад/рерайт, CTA, промпти)"""
        processing_data = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
            text_futures = {}
            worker = self._rewrite_text_processing_worker if is_rewrite else self._text_processing_worker

            if is_rewrite and 'transcribed_text' not in task:
                pass
            else:
                for lang_code in task['selected_langs']:
                    task_key = (task['task_index'], lang_code)
                    processing_data[task_key] = {'task': task} 
                    future = executor.submit(worker, self.app, task, lang_code, queue_type)
                    text_futures[future] = task_key
            
            for future in concurrent.futures.as_completed(text_futures):
                task_key = text_futures[future]
                processing_data[task_key]['text_results'] = future.result()

        return processing_data

    def _process_media_generation_phase(self, all_processing_data, queue_to_process):
        """Обробляє генерацію зображень та аудіо/субтитрів для всіх завдань паралельно"""
        self.app.root.after(0, self.app.setup_empty_gallery, 'main', queue_to_process)
        should_gen_images = any(data.get('text_results') and data['task']['steps'][key[1]].get('gen_images') for key, data in all_processing_data.items())

        image_master_thread = threading.Thread(target=self._sequential_image_master, args=(all_processing_data, queue_to_process, 'main', False)) if should_gen_images else None
        audio_subs_master_thread = threading.Thread(target=self._audio_subs_pipeline_master, args=(all_processing_data, False, 'main'))
        
        if image_master_thread: image_master_thread.start()
        audio_subs_master_thread.start()
        
        if image_master_thread: image_master_thread.join()
        audio_subs_master_thread.join()

    def _process_all_montage_phase(self, queue_to_process):
        """Виконує монтаж для всіх завдань після підготовчих етапів"""
        logger.info("Початок етапу монтажу для всіх завдань...")
        
        # Додаємо кроки монтажу до загального підрахунку
        num_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)
        for task in queue_to_process:
            is_rewrite = task.get('type') == 'Rewrite'
            for lang_code in task['selected_langs']:
                steps = task['steps'][lang_code]
                if steps.get('create_video'):
                    self.app.total_individual_steps += num_chunks  # chunk videos
                    self.app.total_individual_steps += 1  # final concatenation

        for task_key, data in sorted(self.all_processing_data.items()):
            if not self.app._check_app_state():
                logger.warning("Монтаж зупинено користувачем.")
                break
                
            lang_code = task_key[1]
            task_idx_str = task_key[0]
            task = data['task']
            is_rewrite = task.get('type') == 'Rewrite'
            queue_type = 'rewrite' if is_rewrite else 'main'
            status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
            
            if not (data.get('task') and data.get('text_results') and data['task']['steps'][lang_code].get('create_video')):
                continue

            images_folder = data['text_results']['images_folder']
            all_images = sorted([os.path.join(images_folder, f) for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
            
            if not data.get('audio_chunks') or not data.get('subs_chunks') or not all_images:
                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
                continue

            if status_key in self.app.task_completion_status:
                self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "В процесі"
                self.app.root.after(0, self.app.update_task_status_display)

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
                        self.app.increment_and_update_progress(queue_type)
                        
                video_chunk_paths = [video_results[i] for i in sorted(video_results.keys())]

            if len(video_chunk_paths) == len(data['audio_chunks']):
                base_name = sanitize_filename(data['text_results'].get('video_title', data['text_results'].get('task_name', f"Task_{task_key[0]}")))
                final_video_path = os.path.join(data['text_results']['output_path'], f"video_{base_name}_{lang_code}.mp4")
                
                if self._concatenate_videos(self.app, video_chunk_paths, final_video_path):
                    self.app.increment_and_update_progress(queue_type)
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Готово"
                    if is_rewrite and 'original_filename' in data['task']:
                        self.app.save_processed_link(data['task']['original_filename'])
                else:
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
            else:
                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
            
            if self.config.get("telegram", {}).get("report_timing", "per_task") == "per_language":
                self.app.send_task_completion_report(data['task'], single_lang_code=lang_code)

        # Відправляємо звіти для завдань
        for task in queue_to_process:
            if self.config.get("telegram", {}).get("report_timing", "per_task") == "per_task":
                self.app.send_task_completion_report(task)
        
        # Очищуємо тимчасові файли
        if not self.config.get('parallel_processing', {}).get('keep_temp_files', False):
            for data in self.all_processing_data.values():
                if 'temp_dir' in data and os.path.exists(data['temp_dir']):
                    try: shutil.rmtree(data['temp_dir'])
                    except Exception as e: logger.error(f"Failed to delete temp dir {data['temp_dir']}: {e}")

        self.app.stop_command_listener.set()
        self.app.completed_individual_steps = self.app.total_individual_steps
        self.app.update_individual_progress('main')
        logger.info("Етап монтажу завершено для всіх завдань!")

    def _process_hybrid_queue(self, queue_to_process_list, queue_type):
        is_rewrite = queue_type == 'rewrite'
        
        if is_rewrite:
            self.app.is_processing_rewrite_queue = True
        else:
            # self.app.is_processing_queue = True # Цей прапор вже встановлено вище
            pass

        if self.firebase_api.is_initialized:
            self.app.stop_command_listener.clear()
            self.firebase_api.clear_commands()
            self.firebase_api.clear_montage_ready_status()
            
            if self.config.get("firebase", {}).get("auto_clear_gallery", True):
                self.firebase_api.clear_images()
                logger.info("Auto-cleared old gallery images from Firebase for new generation session")
            
            self.app.command_listener_thread = threading.Thread(target=self.app._command_listener_worker, daemon=True)
            self.app.command_listener_thread.start()
            self.app.root.after(100, self.app._process_command_queue)

        self.app._update_button_states(is_processing=True, is_image_stuck=False)
        self.app.image_control_active.clear()

        # Скидаємо лічильники прогресу для НОВОГО завдання
        self.app.completed_individual_steps = 0
        self.app.total_individual_steps = 0
        num_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)
        
        # Перераховуємо кроки ТІЛЬКИ для поточного завдання
        task = queue_to_process_list[0]
        
        if is_rewrite:
            first_lang_steps = task['steps'][task['selected_langs'][0]]
            if task.get('source_type') == 'url' and first_lang_steps.get('download'):
                self.app.total_individual_steps += 1
            if first_lang_steps.get('transcribe'):
                self.app.total_individual_steps += 1

        for lang_code in task['selected_langs']:
            steps = task['steps'][lang_code]
            
            main_step = 'rewrite' if is_rewrite else 'translate'
            if steps.get(main_step): self.app.total_individual_steps += 1
            
            common_steps = ['cta', 'gen_prompts', 'gen_images', 'audio', 'create_subtitles', 'create_video']
            for step in common_steps:
                if steps.get(step):
                    if step in ['audio', 'create_subtitles']:
                        # Розраховуємо фактичну кількість частин для аудіо/субтитрів
                        lang_config = self.config["languages"][lang_code]
                        tts_service = lang_config.get("tts_service", "elevenlabs")
                        
                        if tts_service == "voicemaker":
                            # Для Voicemaker потрібно розрахувати реальну кількість частин на основі тексту
                            text_to_process = task.get('input_text', '')
                            if is_rewrite and 'transcribed_text' in task:
                                text_to_process = task['transcribed_text']
                            
                            voicemaker_limit = self.config.get("voicemaker", {}).get("char_limit", 2900)
                            if len(text_to_process) > voicemaker_limit:
                                text_chunks = chunk_text_voicemaker(text_to_process, voicemaker_limit)
                                actual_chunks = len(text_chunks)
                                # Для субтитрів Voicemaker використовує num_chunks груп після злиття
                                if step == 'create_subtitles':
                                    self.app.total_individual_steps += min(num_chunks, actual_chunks)
                                else:  # audio
                                    self.app.total_individual_steps += actual_chunks
                            else:
                                self.app.total_individual_steps += 1
                        else:
                            # Для інших TTS сервісів використовуємо стандартну логіку
                            self.app.total_individual_steps += num_chunks
                    elif step == 'create_video':
                        self.app.total_individual_steps += num_chunks
                        self.app.total_individual_steps += 1
                    else: # gen_images, cta, gen_prompts
                        self.app.total_individual_steps += 1

        logger.info(f"Детальний підрахунок прогресу для '{task.get('task_name')}': знайдено {self.app.total_individual_steps} індивідуальних етапів.")
        self.app.update_individual_progress(queue_type)

        try:
            queue_to_process = list(queue_to_process_list)
            processing_data = {}

            # Phase 0: Transcription (only for rewrite mode)
            if is_rewrite:
                logger.info("Hybrid mode -> Phase 0: Downloading and transcription.")
                step_name_key_transcribe = self.app._t('step_name_transcribe')
                step_name_key_download = self.app._t('step_name_download')

                task = queue_to_process[0]
                task_index = task['task_index']

                if task.get('source_type') == 'url':
                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status and step_name_key_download in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key_download] = "В процесі"
                    self.app.root.after(0, self.app.update_task_status_display)
                    
                    result_path = self._video_download_worker(task)
                    task['mp3_path'] = result_path
                    
                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status and step_name_key_download in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key_download] = "Готово" if result_path else "Помилка"
                    if result_path: self.app.increment_and_update_progress(queue_type)
                    self.app.root.after(0, self.app.update_task_status_display)
                
                if 'mp3_path' in task and task['mp3_path']:
                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status and step_name_key_transcribe in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key_transcribe] = "В процесі"
                    self.app.root.after(0, self.app.update_task_status_display)

                    mp3_path = task['mp3_path']
                    original_filename = task.get('original_filename', os.path.basename(mp3_path))
                    video_title = sanitize_filename(os.path.splitext(original_filename)[0])
                    task_output_dir = os.path.join(self.config['output_settings']['rewrite_default_dir'], video_title)
                    os.makedirs(task_output_dir, exist_ok=True)
                    original_transcript_path = os.path.join(task_output_dir, "original_transcript.txt")
                    
                    if os.path.exists(original_transcript_path):
                        with open(original_transcript_path, "r", encoding='utf-8') as f:
                            transcribed_text = f.read()
                    else:
                        model = self.montage_api._load_whisper_model()
                        if not model: return
                        transcription_result = model.transcribe(mp3_path, verbose=False)
                        transcribed_text = transcription_result['text']
                        with open(original_transcript_path, "w", encoding='utf-8') as f: f.write(transcribed_text)

                    task['transcribed_text'] = transcribed_text
                    task['video_title'] = video_title
                    self.app.increment_and_update_progress(queue_type)

                    for lang_code in task['selected_langs']:
                        status_key = self._get_status_key(task_index, lang_code, is_rewrite)
                        if status_key in self.app.task_completion_status and step_name_key_transcribe in self.app.task_completion_status[status_key]['steps']:
                            self.app.task_completion_status[status_key]['steps'][step_name_key_transcribe] = "Готово"
                    self.app.root.after(0, self.app.update_task_status_display)

            logger.info(f"Hybrid mode -> Phase 1: Parallel text processing for task '{task.get('task_name')}'.")

            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                text_futures = {}
                worker = self._rewrite_text_processing_worker if is_rewrite else self._text_processing_worker

                task = queue_to_process[0]
                if is_rewrite and 'transcribed_text' not in task:
                    pass
                else:
                    for lang_code in task['selected_langs']:
                        task_key = (task['task_index'], lang_code)
                        processing_data[task_key] = {'task': task} 
                        future = executor.submit(worker, self.app, task, lang_code, queue_type)
                        text_futures[future] = task_key
                
                for future in concurrent.futures.as_completed(text_futures):
                    task_key = text_futures[future]
                    processing_data[task_key]['text_results'] = future.result()

            logger.info("Гібридний режим -> Етап 1: Обробку тексту завершено.")

            self.app.root.after(0, self.app.setup_empty_gallery, queue_type, [task])
            should_gen_images = any(data.get('text_results') and data['task']['steps'][key[1]].get('gen_images') for key, data in processing_data.items())

            image_master_thread = threading.Thread(target=self._sequential_image_master, args=(processing_data, [task], queue_type, is_rewrite)) if should_gen_images else None
            audio_subs_master_thread = threading.Thread(target=self._audio_subs_pipeline_master, args=(processing_data, is_rewrite, queue_type))
            
            if image_master_thread: image_master_thread.start()
            audio_subs_master_thread.start()
            
            if image_master_thread: image_master_thread.join()
            audio_subs_master_thread.join()
            
            logger.info("Гібридний режим -> Етап 2: Генерацію всіх медіафайлів завершено.")

            if self.config.get("ui_settings", {}).get("image_control_enabled", False):
                self.app.root.after(0, lambda: messagebox.showinfo("Процес призупинено", "Всі підготовчі етапи завершено!\n\nПерегляньте галерею та натисніть 'Продовжити монтаж'."))
                if self.firebase_api and self.firebase_api.is_initialized: self.firebase_api.send_montage_ready_status()
                logger.info("WORKFLOW PAUSED. Waiting for user to press 'Continue Montage' button...")
                self.app.image_control_active.wait()
                logger.info("WORKFLOW RESUMED after user confirmation.")

            logger.info("Hybrid mode -> Phase 4: Starting final montage.")
            
            for task_key, data in sorted(processing_data.items()):
                lang_code = task_key[1]
                task_idx_str = task_key[0]
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
                
                if not (data.get('task') and data.get('text_results') and data['task']['steps'][lang_code].get('create_video')):
                    continue

                images_folder = data['text_results']['images_folder']
                all_images = sorted([os.path.join(images_folder, f) for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                
                if not data.get('audio_chunks') or not data.get('subs_chunks') or not all_images:
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
                    continue

                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "В процесі"
                    self.app.root.after(0, self.app.update_task_status_display)

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
                            self.app.increment_and_update_progress(queue_type)
                            
                    video_chunk_paths = [video_results[i] for i in sorted(video_results.keys())]

                if len(video_chunk_paths) == len(data['audio_chunks']):
                    base_name = sanitize_filename(data['text_results'].get('video_title', data['text_results'].get('task_name', f"Task_{task_key[0]}")))
                    final_video_path = os.path.join(data['text_results']['output_path'], f"video_{base_name}_{lang_code}.mp4")
                    
                    if self._concatenate_videos(self.app, video_chunk_paths, final_video_path):
                        self.app.increment_and_update_progress(queue_type)
                        if status_key in self.app.task_completion_status:
                            self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Готово"
                        if is_rewrite and 'original_filename' in data['task']:
                            self.app.save_processed_link(data['task']['original_filename'])
                    else:
                        if status_key in self.app.task_completion_status:
                            self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
                else:
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['steps'][self.app._t('step_name_create_video')] = "Помилка"
                
                if self.config.get("telegram", {}).get("report_timing", "per_task") == "per_language":
                    self.app.send_task_completion_report(data['task'], single_lang_code=lang_code)

            if self.config.get("telegram", {}).get("report_timing", "per_task") == "per_task":
                self.app.send_task_completion_report(task)
            
            self.app.completed_individual_steps = self.app.total_individual_steps
            self.app.update_individual_progress(queue_type)

        except Exception as e:
            logger.exception(f"CRITICAL ERROR: Unexpected error in hybrid queue processing for task '{task.get('task_name')}': {e}")
        finally:
            if not self.config.get('parallel_processing', {}).get('keep_temp_files', False):
                for data in processing_data.values():
                    if 'temp_dir' in data and os.path.exists(data['temp_dir']):
                        try: shutil.rmtree(data['temp_dir'])
                        except Exception as e: logger.error(f"Failed to delete temp dir {data['temp_dir']}: {e}")

            self.app.stop_command_listener.set()
            if is_rewrite:
                self.app.is_processing_rewrite_queue = False

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
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_translate] = "Готово"
                    app.root.after(0, app.update_task_status_display)
                else:
                    logger.error(f"Translation failed for {lang_name}.")
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_translate] = "Помилка"
                    app.root.after(0, app.update_task_status_display)
                    return None
            elif os.path.exists(translation_path):
                with open(translation_path, 'r', encoding='utf-8') as f: text_to_process = f.read()
                logger.info(f"Using existing translation file for {lang_name}: {translation_path}")
            else:
                text_to_process = task['input_text']

            prompts_path = os.path.join(output_path, "image_prompts.txt")
            
            if lang_steps.get('cta'):
                step_name_key_cta = self.app._t('step_name_cta')
                if status_key in app.task_completion_status:
                    app.task_completion_status[status_key]['steps'][step_name_key_cta] = "В процесі"
                    app.root.after(0, app.update_task_status_display)
                
                cta_text = self.or_api.generate_call_to_action(text_to_process, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"], lang_name)
                if cta_text:
                    with open(os.path.join(output_path, "call_to_action.txt"), 'w', encoding='utf-8') as f: f.write(cta_text)
                    app.increment_and_update_progress(queue_type)
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_cta] = "Готово"
                else:
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_cta] = "Помилка"
                app.root.after(0, app.update_task_status_display)


            raw_prompts = None
            if lang_steps.get('gen_prompts'):
                step_name_key_prompts = self.app._t('step_name_gen_prompts')
                if status_key in app.task_completion_status:
                    app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "В процесі"
                    app.root.after(0, app.update_task_status_display)

                raw_prompts = self.or_api.generate_image_prompts(text_to_process, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"], lang_name)
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
                    app.increment_and_update_progress(queue_type)
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "Готово"
                else:
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "Помилка"
                app.root.after(0, app.update_task_status_display)
            elif os.path.exists(prompts_path):
                with open(prompts_path, 'r', encoding='utf-8') as f: raw_prompts = f.read()

            image_prompts = []
            if raw_prompts:
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                image_prompts = [block.strip() for block in prompt_blocks if block.strip()]

            images_folder = os.path.join(output_path, "images")
            os.makedirs(images_folder, exist_ok=True)
            
            if status_key in app.task_completion_status:
                app.task_completion_status[status_key]["total_images"] = len(image_prompts)
            app.root.after(0, app.update_task_status_display)

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
            
            step_name_key_rewrite = self.app._t('step_name_rewrite_text')
            if task['steps'][lang_code]['rewrite']:
                if status_key in app.task_completion_status and step_name_key_rewrite in app.task_completion_status[status_key]['steps']:
                    app.task_completion_status[status_key]['steps'][step_name_key_rewrite] = "В процесі"
                    app.root.after(0, app.update_task_status_display)

                rewritten_text = self.or_api.rewrite_text(transcribed_text, self.config["openrouter"]["rewrite_model"], self.config["openrouter"]["rewrite_params"], rewrite_prompt_template)
                
                if not rewritten_text: 
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_rewrite] = "Помилка"
                    app.root.after(0, app.update_task_status_display)
                    return None
                
                with open(os.path.join(lang_output_path, "rewritten_text.txt"), "w", encoding='utf-8') as f: f.write(rewritten_text)
                app.increment_and_update_progress(queue_type)
                if status_key in app.task_completion_status: 
                    app.task_completion_status[status_key]['steps'][step_name_key_rewrite] = "Готово"
                app.root.after(0, app.update_task_status_display)
            else:
                rewritten_text = transcribed_text
            
            cta_path = os.path.join(lang_output_path, "call_to_action.txt")
            if task['steps'][lang_code]['cta']:
                step_name_key_cta = self.app._t('step_name_cta')
                if status_key in app.task_completion_status:
                    app.task_completion_status[status_key]['steps'][step_name_key_cta] = "В процесі"
                    app.root.after(0, app.update_task_status_display)
                
                cta_text = self.or_api.generate_call_to_action(rewritten_text, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"])
                if cta_text:
                    with open(cta_path, 'w', encoding='utf-8') as f: f.write(cta_text)
                    app.increment_and_update_progress(queue_type)
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_cta] = "Готово"
                else:
                    if status_key in app.task_completion_status:
                        app.task_completion_status[status_key]['steps'][step_name_key_cta] = "Помилка"
                app.root.after(0, app.update_task_status_display)

            raw_prompts = None
            prompts_path = os.path.join(lang_output_path, "image_prompts.txt")
            if task['steps'][lang_code]['gen_prompts']:
                step_name_key_prompts = self.app._t('step_name_gen_prompts')
                if status_key in app.task_completion_status:
                    app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "В процесі"
                    app.root.after(0, app.update_task_status_display)

                raw_prompts = self.or_api.generate_image_prompts(rewritten_text, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"])
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
                    app.increment_and_update_progress(queue_type)
                    if status_key in app.task_completion_status: 
                        app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "Готово"
                else:
                    if status_key in app.task_completion_status:
                        app.task_completion_status[status_key]['steps'][step_name_key_prompts] = "Помилка"
                app.root.after(0, app.update_task_status_display)
            elif os.path.exists(prompts_path):
                with open(prompts_path, 'r', encoding='utf-8') as f: raw_prompts = f.read()

            image_prompts = []
            if raw_prompts:
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                image_prompts = [block.strip() for block in prompt_blocks if block.strip()]

            images_folder = os.path.join(lang_output_path, "images")
            os.makedirs(images_folder, exist_ok=True)
            
            if status_key in app.task_completion_status:
                app.task_completion_status[status_key]["total_images"] = len(image_prompts)
            app.root.after(0, app.update_task_status_display)
            
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
                self._image_generation_worker(data, task_key, int(task_idx_str) + 1, len(queue_to_process), queue_type, is_rewrite)
                
                if status_key in self.app.task_completion_status:
                    # Після завершення воркера, інкрементуємо загальний прогрес, якщо хоч щось згенерувалось
                    if self.app.task_completion_status[status_key]["images_generated"] > 0:
                        self.app.increment_and_update_progress(queue_type)
                    
                    # Встановлюємо фінальний статус
                    total_img = self.app.task_completion_status[status_key].get("total_images", 0)
                    generated_img = self.app.task_completion_status[status_key].get("images_generated", 0)
                    
                    if total_img > 0:
                        self.app.task_completion_status[status_key]['steps'][step_name] = f"{generated_img}/{total_img}"
                    elif self.app.task_completion_status[status_key]['steps'][step_name] != "Пропущено":
                        self.app.task_completion_status[status_key]['steps'][step_name] = "Помилка"
                    
                    if is_rewrite:
                        self.app.root.after(0, self.app.update_rewrite_task_status_display)
                    else:
                        self.app.root.after(0, self.app.update_task_status_display)
            
            elif status_key in self.app.task_completion_status and step_name in self.app.task_completion_status[status_key]['steps']:
                self.app.task_completion_status[status_key]['steps'][step_name] = "Пропущено"
                if is_rewrite:
                    self.app.root.after(0, self.app.update_rewrite_task_status_display)
                else:
                    self.app.root.after(0, self.app.update_task_status_display)

        logger.info("[Image Control] Image Master Thread: All image generation tasks complete.")

    # core/workflow.py

    def _image_generation_worker(self, data, task_key, task_num, total_tasks, queue_type, is_rewrite=False):
        prompts = data['text_results']['prompts']
        images_folder = data['text_results']['images_folder']
        lang_name = task_key[1].upper()

        status_key = self._get_status_key(task_key[0], task_key[1], is_rewrite)
        step_name = self.app._t('step_name_gen_images')

        if status_key in self.app.task_completion_status and step_name in self.app.task_completion_status[status_key]['steps']:
            total_images = self.app.task_completion_status[status_key].get("total_images", 0)
            if total_images > 0:
                self.app.task_completion_status[status_key]['steps'][step_name] = f"0/{total_images}"
            else:
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
        
        i = 0
        while i < len(prompts):
            if not self.app._check_app_state():
                break

            prompt = prompts[i]
            image_path = os.path.join(images_folder, f"image_{i+1:03d}.jpg")
            
            consecutive_failures = 0
            image_generated = False
            
            while not image_generated:
                if not self.app._check_app_state(): break
                
                with self.app.image_api_lock:
                    current_api_for_generation = self.app.active_image_api_var.get()

                progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - [{current_api_for_generation.capitalize()}] {self.app._t('step_gen_images')} {i+1}/{len(prompts)} (Спроба {consecutive_failures + 1})..."
                self.app.update_progress(progress_text, queue_type=queue_type)

                if self.app.skip_image_event.is_set():
                    self.app.skip_image_event.clear()
                    logger.warning(f"Skipping image {i+1} by user command.")
                    break

                if self.app.regenerate_alt_service_event.is_set():
                    self.app.regenerate_alt_service_event.clear()
                    logger.warning(f"Attempting to regenerate image {i+1} with alternate service.")
                    with self.app.image_api_lock:
                        alt_service = "recraft" if current_api_for_generation == "pollinations" else "pollinations"
                    
                    success_alt = False
                    if alt_service == "pollinations":
                        success_alt = self.poll_api.generate_image(prompt, image_path)
                    elif alt_service == "recraft":
                        success_alt, _ = self.recraft_api.generate_image(prompt, image_path)

                    if success_alt:
                        image_generated = True
                    else:
                        logger.error(f"Alternate service [{alt_service.capitalize()}] also failed to generate image {i+1}.")
                    break

                success = False
                if current_api_for_generation == "pollinations":
                    success = self.poll_api.generate_image(prompt, image_path)
                elif current_api_for_generation == "recraft":
                    success, _ = self.recraft_api.generate_image(prompt, image_path)

                if success:
                    image_generated = True
                    consecutive_failures = 0  # Скидаємо лічильник при успішній генерації
                else:
                    consecutive_failures += 1
                    logger.error(f"[{current_api_for_generation.capitalize()}] Failed to generate image {i+1}. Consecutive failures: {consecutive_failures}.")
                    
                    # Автоматичне перемикання після 10 невдач (якщо увімкнене)
                    if auto_switch_enabled and consecutive_failures >= retry_limit_for_switch:
                        logger.warning(f"Reached {consecutive_failures} consecutive failures. Triggering automatic service switch for ONE image.")
                        alt_service = "recraft" if current_api_for_generation == "pollinations" else "pollinations"
                        
                        success_alt = False
                        if alt_service == "pollinations":
                            success_alt = self.poll_api.generate_image(prompt, image_path)
                        elif alt_service == "recraft":
                            success_alt, _ = self.recraft_api.generate_image(prompt, image_path)
                        
                        if success_alt:
                            image_generated = True
                            consecutive_failures = 0  # Скидаємо лічильник після успішного автоперемикання
                            logger.info(f"Successfully generated image {i+1} using alternate service [{alt_service.capitalize()}]. Returning to main service.")
                        else:
                            logger.error(f"Alternate service [{alt_service.capitalize()}] also failed to generate image {i+1}. Skipping this image.")
                        break
                    
                    # Показуємо кнопки після 5 невдач, але поводимося по-різному залежно від налаштувань
                    if consecutive_failures >= 5 and consecutive_failures % 5 == 0:  # Показуємо кнопки кожні 5 спроб
                        self.app._update_button_states(is_processing=True, is_image_stuck=True)
                        self.tg_api.send_message_with_buttons(
                            message="❌ *Помилка генерації зображення*\n\nНе вдається згенерувати зображення\\. Процес очікує\\. Оберіть дію:",
                            buttons=[
                                {"text": "Пропустити", "callback_data": "skip_image_action"},
                                {"text": "Спробувати іншим", "callback_data": "regenerate_alt_action"},
                            ]
                        )
                        
                        # Якщо автоперемикання вимкнене, чекаємо недовго на дію користувача і продовжуємо нескінченні спроби
                        if not auto_switch_enabled:
                            wait_time = 0
                            while wait_time < 5 and not (self.app.skip_image_event.is_set() or self.app.regenerate_alt_service_event.is_set()):
                                if not self.app._check_app_state():
                                    break
                                time.sleep(0.5)
                                wait_time += 0.5
                            self.app._update_button_states(is_processing=True, is_image_stuck=False)
                            
                            # Якщо користувач не вибрав дію, продовжуємо нескінченні спроби
                            if not (self.app.skip_image_event.is_set() or self.app.regenerate_alt_service_event.is_set()):
                                logger.info(f"No user action received. Continuing infinite attempts for image {i+1}...")
                                time.sleep(2)  # Короткий відпочинок перед наступною спробою
                        else:
                            # Якщо автоперемикання увімкнене, чекаємо недовго на дію користувача і продовжуємо спроби
                            wait_time = 0
                            while wait_time < 5 and not (self.app.skip_image_event.is_set() or self.app.regenerate_alt_service_event.is_set()):
                                if not self.app._check_app_state():
                                    break
                                time.sleep(0.5)
                                wait_time += 0.5
                            self.app._update_button_states(is_processing=True, is_image_stuck=False)
                            
                            # Якщо користувач не вибрав дію, продовжуємо спроби до автоперемикання
                            if not (self.app.skip_image_event.is_set() or self.app.regenerate_alt_service_event.is_set()):
                                logger.info(f"No user action received. Continuing attempts for image {i+1}...")
                                time.sleep(2)  # Короткий відпочинок перед наступною спробою

            if image_generated:
                self.app.image_prompts_map[image_path] = prompt
                self.app.root.after(0, self.app._add_image_to_gallery, image_path, task_key)
                if self.firebase_api.is_initialized:
                    task_name = data['task'].get('task_name', f"Task {task_key[0]}")
                    def save_mapping(image_id, local_path):
                        self.app.image_id_to_path_map[image_id] = local_path
                    self.firebase_api.upload_and_add_image_in_thread(image_path, task_key, i, task_name, prompt, callback=save_mapping)

                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]["images_generated"] += 1
                    total = self.app.task_completion_status[status_key].get("total_images", 0)
                    done = self.app.task_completion_status[status_key]["images_generated"]
                    self.app.task_completion_status[status_key]['steps'][step_name] = f"{done}/{total}"
                    if is_rewrite:
                        self.app.root.after(0, self.app.update_rewrite_task_status_display)
                    else:
                        self.app.root.after(0, self.app.update_task_status_display)
            
            i += 1
        
        return True

    def _audio_subs_pipeline_master(self, processing_data, is_rewrite=False, queue_type='main'):
        """Керує пайплайном Аудіо -> Транскрипція з централізованою логікою."""
        logger.info("[Audio/Subs Master] Запуск керованого пайплайну.")

        num_parallel_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)
        self.audio_worker_pool = AudioWorkerPool(self.app, num_parallel_chunks)
        self.audio_worker_pool.start()

        tasks_info = {}
        total_audio_chunks_expected = 0
        total_transcriptions_expected = 0  # Заздалегідь розраховуємо кількість транскрипцій

        try:
            for task_key, data in sorted(processing_data.items()):
                if not data.get('text_results'): continue

                task_idx_str, lang_code = task_key
                status_key = self._get_status_key(task_idx_str, lang_code, is_rewrite)
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
                
                # Розраховуємо кількість транскрипцій для цього завдання
                if tts_service == 'voicemaker' and len(text_chunks) > num_parallel_chunks:
                    transcription_count = num_parallel_chunks
                else:
                    transcription_count = len(text_chunks)
                
                total_transcriptions_expected += transcription_count
                
                tasks_info[str(task_key)] = {
                    'tts_service': tts_service,
                    'total_chunks': len(text_chunks),
                    'expected_transcriptions': transcription_count,  # Зберігаємо очікувану кількість
                    'completed_audio_items': [],
                    'data': data,
                    'processed_voicemaker_group': False  # Флаг для уникнення повторної обробки Voicemaker
                }
                
                if status_key in self.app.task_completion_status:
                    self.app.task_completion_status[status_key]['total_audio'] = len(text_chunks)
                    self.app.task_completion_status[status_key]['total_subs'] = transcription_count
                    self.app.task_completion_status[status_key]['audio_generated'] = 0
                    self.app.task_completion_status[status_key]['subs_generated'] = 0
                
                # Розділяємо на звичайні TTS та асинхронний Voicemaker
                if tts_service == "voicemaker":
                    # Для Voicemaker: створюємо завдання та відправляємо асинхронно
                    voicemaker_items = []
                    for i, chunk in enumerate(text_chunks):
                        audio_task = AudioPipelineItem(
                            text_chunk=chunk,
                            output_path=os.path.join(temp_dir, f"audio_chunk_{i}.mp3"),
                            lang_config=lang_config, lang_code=lang_code,
                            chunk_index=i, total_chunks=len(text_chunks),
                            task_key=str(task_key)
                        )
                        voicemaker_items.append(audio_task)
                    
                    # Відправляємо всі Voicemaker завдання асинхронно з затримками
                    self.audio_worker_pool.submit_voicemaker_tasks_async(voicemaker_items)
                else:
                    # Для звичайних TTS (ElevenLabs, Speechify): додаємо в чергу воркерів
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
            logger.info(f"Очікується {total_transcriptions_expected} транскрипцій після обробки аудіо.")

            completed_audio_count = 0
            voicemaker_check_interval = 2.0  # Перевіряємо Voicemaker кожні 2 секунди

            while completed_audio_count < total_audio_chunks_expected and not self.app.shutdown_event.is_set():
                try:
                    # Перевіряємо звичайні TTS результати (ElevenLabs, Speechify)
                    result = self.audio_worker_pool.audio_results_queue.get(timeout=0.5)
                    completed_audio_count += 1

                    if not result.success:
                        logger.error(f"Помилка генерації аудіо для {result.item.task_key}, фрагмент {result.item.chunk_index}. Пропускаємо.")
                        continue
                    
                    self.app.increment_and_update_progress(queue_type)

                    task_key = result.item.task_key
                    task_info = tasks_info[task_key]
                    task_info['completed_audio_items'].append(result.item)
                    
                    task_key_tuple = eval(task_key)
                    status_key = self._get_status_key(task_key_tuple[0], task_key_tuple[1], is_rewrite)
                    if status_key in self.app.task_completion_status:
                        self.app.task_completion_status[status_key]['audio_generated'] += 1
                        self.app.root.after(0, self.app.update_task_status_display)

                    # Для НЕ-Voicemaker: одразу відправляємо на транскрипцію
                    if task_info['tts_service'] != 'voicemaker':
                        logger.info(f"Відправка аудіо на транскрипцію: {result.item.output_path} (task: {task_key}, chunk: {result.item.chunk_index})")
                        trans_item = TranscriptionPipelineItem(result.item.output_path, os.path.dirname(result.item.output_path), result.item.chunk_index, result.item.lang_code, task_key)
                        self.audio_worker_pool.add_transcription_task(trans_item)
                    # Для Voicemaker: перевіряємо чи всі частини готові для склеювання та чи не було обробки раніше
                    elif (len(task_info['completed_audio_items']) == task_info['total_chunks'] and 
                          not task_info['processed_voicemaker_group']):
                        task_info['processed_voicemaker_group'] = True  # Встановлюємо флаг
                        self._process_voicemaker_group(task_info, task_key, num_parallel_chunks)
                        
                except queue.Empty:
                    pass  # Нормально, продовжуємо перевірку
                
                # Перевіряємо асинхронні Voicemaker завдання
                for task_key, task_info in tasks_info.items():
                    if task_info['tts_service'] == 'voicemaker':
                        downloaded_items = self.audio_worker_pool.check_voicemaker_progress(task_key)
                        
                        for item in downloaded_items:
                            completed_audio_count += 1
                            self.app.increment_and_update_progress(queue_type)
                            task_info['completed_audio_items'].append(item)
                            
                            task_key_tuple = eval(task_key)
                            status_key = self._get_status_key(task_key_tuple[0], task_key_tuple[1], is_rewrite)
                            if status_key in self.app.task_completion_status:
                                self.app.task_completion_status[status_key]['audio_generated'] += 1
                                self.app.root.after(0, self.app.update_task_status_display)
                        
                        # Перевіряємо чи всі Voicemaker частини готові та чи не було обробки раніше
                        if (len(task_info['completed_audio_items']) == task_info['total_chunks'] and 
                            not task_info['processed_voicemaker_group']):
                            task_info['processed_voicemaker_group'] = True  # Встановлюємо флаг
                            self._process_voicemaker_group(task_info, task_key, num_parallel_chunks)
                
                # Невелика затримка для ефективності
                time.sleep(0.1)

            logger.info(f"Очікується {total_transcriptions_expected} результатів транскрипції.")
            completed_transcriptions = 0
            while completed_transcriptions < total_transcriptions_expected and not self.app.shutdown_event.is_set():
                try:
                    result_item = self.transcription_results_queue.get(timeout=1.0)
                    completed_transcriptions += 1
                    logger.info(f"Отримано результат транскрипції {completed_transcriptions}/{total_transcriptions_expected} для {result_item.task_key}")
                    
                    if result_item.subs_path:
                        self.app.increment_and_update_progress(queue_type)
                        info = tasks_info[result_item.task_key]
                        if 'subs_chunks' not in info['data']: info['data']['subs_chunks'] = []
                        if 'audio_chunks' not in info['data']: info['data']['audio_chunks'] = []
                        info['data']['subs_chunks'].append(result_item.subs_path)
                        info['data']['audio_chunks'].append(result_item.audio_path)
                        
                        task_key_tuple = eval(result_item.task_key)
                        status_key = self._get_status_key(task_key_tuple[0], task_key_tuple[1], is_rewrite)
                        if status_key in self.app.task_completion_status:
                            self.app.task_completion_status[status_key]['subs_generated'] += 1
                            self.app.root.after(0, self.app.update_task_status_display)
                    else:
                        logger.warning(f"Транскрипція для {result_item.task_key} не створена (subs_path = None)")

                except queue.Empty:
                    continue

            for tk, info in tasks_info.items():
                if 'subs_chunks' in info['data']: info['data']['subs_chunks'].sort()
                if 'audio_chunks' in info['data']: info['data']['audio_chunks'].sort()
                
                task_key_tuple = eval(tk)
                status_key = self._get_status_key(task_key_tuple[0], task_key_tuple[1], is_rewrite)
                if status_key in self.app.task_completion_status:
                    status_data = self.app.task_completion_status[status_key]
                    if status_data.get('total_audio', 0) > 0 and status_data.get('audio_generated') == status_data.get('total_audio'):
                         status_data['steps'][self.app._t('step_name_audio')] = f"{status_data['total_audio']}/{status_data['total_audio']}"
                    elif status_data.get('total_audio', 0) > 0:
                         status_data['steps'][self.app._t('step_name_audio')] = "Помилка"

                    if status_data.get('total_subs', 0) > 0 and status_data.get('subs_generated') == status_data.get('total_subs'):
                         status_data['steps'][self.app._t('step_name_create_subtitles')] = f"{status_data['total_subs']}/{status_data['total_subs']}"
                    elif status_data.get('total_subs', 0) > 0:
                         status_data['steps'][self.app._t('step_name_create_subtitles')] = "Помилка"

            self.app.root.after(0, self.app.update_task_status_display)

        except Exception as e:
            logger.exception(f"CRITICAL ERROR in audio/subs master pipeline: {e}")
        finally:
            if self.audio_worker_pool:
                self.audio_worker_pool.stop()
                logger.info("[Audio/Subs Master] Пайплайн завершено, воркер пул зупинено.")
    
    def _process_voicemaker_group(self, task_info: dict, task_key: str, num_parallel_chunks: int):
        """Обробляє завершену групу Voicemaker аудіофайлів: склеює та відправляє на транскрипцію."""
        sorted_items = sorted(task_info['completed_audio_items'], key=lambda x: x.chunk_index)
        audio_paths_to_merge = [item.output_path for item in sorted_items]
        
        # Розбиваємо всі аудіочастини на рівно num_parallel_chunks груп
        total_audio_chunks = len(audio_paths_to_merge)
        chunks_per_group = total_audio_chunks // num_parallel_chunks
        remaining_chunks = total_audio_chunks % num_parallel_chunks
        
        logger.info(f"Voicemaker: Склеювання {total_audio_chunks} аудіочастин у {num_parallel_chunks} фінальних файлів для {task_key}...")
        
        groups = []
        start_idx = 0
        for i in range(num_parallel_chunks):
            # Додаємо один додатковий елемент до перших "remaining_chunks" груп
            group_size = chunks_per_group + (1 if i < remaining_chunks else 0)
            end_idx = start_idx + group_size
            if start_idx < total_audio_chunks:
                groups.append(audio_paths_to_merge[start_idx:end_idx])
            start_idx = end_idx
        
        # Видаляємо порожні групи
        groups = [group for group in groups if group]
        
        # Створюємо merged файли та відправляємо на транскрипцію
        for i, group_list in enumerate(groups):
            if not group_list: 
                continue
                
            merged_path = os.path.join(task_info['data']['temp_dir'], f"merged_chunk_{i}.mp3")
            
            if len(group_list) > 1:
                if not concatenate_audio_files(group_list, merged_path): 
                    logger.error(f"Не вдалося склеїти групу {i} для {task_key}")
                    continue
            else:
                shutil.copy(group_list[0], merged_path)
            
            # Отримуємо мову з першого елементу групи
            sample_item = sorted_items[0]
            trans_item = TranscriptionPipelineItem(
                merged_path, 
                os.path.dirname(merged_path), 
                i, 
                sample_item.lang_code, 
                task_key, 
                is_merged_group=True
            )
            self.audio_worker_pool.add_transcription_task(trans_item)
        
        logger.info(f"Voicemaker: Склеювання для {task_key} завершено, відправлено {len(groups)} файлів на транскрипцію")
                
    def _video_download_worker(self, task):
        """
        Завантажує відео з будь-якого URL, використовуючи yt-dlp, і конвертує його в MP3.
        Ця версія є більш надійною і намагається знайти найкращий доступний аудіопотік
        для максимальної ефективності.
        """
        try:
            import yt_dlp

            url = task['url']
            rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']
            temp_download_dir = os.path.join(rewrite_base_dir, "temp_downloads")
            os.makedirs(temp_download_dir, exist_ok=True)
            
            ydl_opts = {
                # ОНОВЛЕНО: Спочатку шукаємо найкраще аудіо. Якщо не виходить,
                # хапаємо найкращий mp4 відео/аудіо потік, або взагалі будь-який, який знайдемо.
                'format': 'bestaudio/best/bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b',
                
                'outtmpl': os.path.join(temp_download_dir, '%(title)s.%(ext)s'),
                
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                
                'nocheckcertificate': True,
                'retries': 15,
                'fragment_retries': 15,
                'socket_timeout': 60,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
                'ignoreerrors': True,
                'quiet': True,
                'noprogress': True,
            }

            if self.config.get("rewrite_settings", {}).get("use_cookies", False):
                cookie_path = self.config.get("rewrite_settings", {}).get("cookies_path", "")
                if cookie_path and os.path.exists(cookie_path):
                    ydl_opts['cookiefile'] = cookie_path
                    logger.info(f"Використовується файл cookies: {cookie_path}")
                else:
                    logger.warning("Увімкнено використання cookies, але шлях до файлу не вказано або файл не знайдено.")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Починаю завантаження та обробку URL: {url}")
                info = ydl.extract_info(url, download=True)
                
                if not info:
                    logger.error(f"Не вдалося отримати інформацію для URL: {url}. Можливо, посилання недійсне або доступ обмежено.")
                    return None

                original_filepath = ydl.prepare_filename(info)
                base, _ = os.path.splitext(original_filepath)
                final_mp3_path = base + '.mp3'
                
                if not os.path.exists(final_mp3_path):
                     if 'entries' in info and info.get('entries'):
                         first_entry = info['entries'][0]
                         if first_entry:
                             original_filepath = ydl.prepare_filename(first_entry)
                             base, _ = os.path.splitext(original_filepath)
                             final_mp3_path = base + '.mp3'

                if os.path.exists(final_mp3_path):
                    video_title = info.get('title', 'video')
                    
                    video_folder = os.path.join(self.app.APP_BASE_PATH, "video")
                    os.makedirs(video_folder, exist_ok=True)
                    
                    final_filename = f"{sanitize_filename(video_title)}.mp3"
                    destination_path = os.path.join(video_folder, final_filename)
                    
                    if os.path.exists(destination_path):
                        logger.warning(f"Файл {final_filename} вже існує. Використовуємо існуючий.")
                        if os.path.abspath(final_mp3_path) != os.path.abspath(destination_path):
                            try:
                                os.remove(final_mp3_path)
                            except OSError as e:
                                logger.error(f"Не вдалося видалити тимчасовий файл {final_mp3_path}: {e}")
                        return destination_path

                    shutil.move(final_mp3_path, destination_path)
                    logger.info(f"Успішно завантажено та конвертовано: '{video_title}' -> {destination_path}")
                    
                    self.app.save_processed_link(final_filename)
                    
                    return destination_path
                else:
                    logger.error(f"Не вдалося знайти фінальний MP3 файл для {url}. Очікувався тут: {final_mp3_path}. Можливо, сталася помилка під час конвертації FFmpeg.")
                    return None

        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Помилка завантаження yt-dlp для URL '{task.get('url', '')}': {e}")
            logger.error("Перевірте, чи URL доступний, чи не потрібна VPN, та чи встановлено FFmpeg у системі.")
            return None
        except Exception as e:
            logger.exception(f"Критична непередбачувана помилка під час завантаження відео з '{task.get('url', '')}': {e}")
            return None

    def _concatenate_videos(self, app_instance, video_chunks, output_path):
        """Об'єднання відеофрагментів."""
        return concatenate_videos(app_instance, video_chunks, output_path)

    def _video_chunk_worker(self, app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks, task_key):
        """Створення одного відеофрагменту."""
        from utils.media_utils import video_chunk_worker
        return video_chunk_worker(app_instance, image_chunk, audio_path, subs_path, output_path, chunk_num, total_chunks, task_key)
