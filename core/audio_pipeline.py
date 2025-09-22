# core/audio_pipeline.py
import logging
import threading
import queue
import time
from typing import Optional, Dict
import os

logger = logging.getLogger("TranslationApp")

class AudioPipelineItem:
    """Елемент для обробки в аудіо пайплайні."""
    def __init__(self, text_chunk: str, output_path: str, lang_config: dict, 
                 lang_code: str, chunk_index: int, total_chunks: int, task_key: str):
        self.text_chunk = text_chunk
        self.output_path = output_path
        self.lang_config = lang_config
        self.lang_code = lang_code
        self.chunk_index = chunk_index
        self.total_chunks = total_chunks
        self.task_key = task_key

class TranscriptionPipelineItem:
    """Елемент для обробки в транскрипційному пайплайні."""
    def __init__(self, audio_path: str, output_dir: str, chunk_index: int, 
                 lang_code: str, task_key: str, is_merged_group: bool = False):
        self.audio_path = audio_path
        self.output_dir = output_dir
        self.chunk_index = chunk_index
        self.lang_code = lang_code
        self.task_key = task_key
        self.is_merged_group = is_merged_group
        self.subs_path: Optional[str] = None # Поле для результату

class AudioWorkerResult:
    """Клас для передачі результатів від аудіо-воркера."""
    def __init__(self, success: bool, item: AudioPipelineItem):
        self.success = success
        self.item = item

class VoicemakerAsyncHandler:
    """
    Обробляє асинхронні Voicemaker завдання з затримками та правильною хронологією.
    """
    def __init__(self, app_instance):
        self.app = app_instance
        self.vm_api = app_instance.vm_api
        self.submitted_tasks: Dict[str, dict] = {}  # task_key -> {task_id, chunk_index, item}
        self.completed_items: Dict[str, list] = {}  # task_key -> [completed AudioPipelineItems]
        self.submission_delay = 1.0  # 1 секунда між запитами
        self.task_groups: Dict[str, set] = {} # task_key -> set of vm_task_ids

    def submit_voicemaker_tasks(self, items: list) -> str:
        """
        Відправляє всі Voicemaker завдання з затримкою в 1 секунду між запитами.
        Повертає task_key для групування.
        """
        if not items:
            return ""

        # Всі items мають однаковий task_key
        task_key = items[0].task_key
        self.submitted_tasks[task_key] = {}
        self.completed_items[task_key] = []
        self.task_groups[task_key] = set()

        # Запускаємо відправку в окремому потоці
        thread = threading.Thread(target=self._submit_tasks_with_delay, args=(items, task_key), daemon=True)
        thread.start()

        logger.info(f"VoicemakerAsync -> Початок відправки {len(items)} завдань для {task_key}")
        return task_key

    def _submit_tasks_with_delay(self, items: list, task_key: str):
        """Відправляє завдання з затримкою між запитами."""
        for i, item in enumerate(items):
            try:
                # Відправляємо асинхронний запит
                vm_task_id = self.vm_api.create_audio_task_async(
                    text=item.text_chunk,
                    voice_id=item.lang_config.get("voicemaker_voice_id"),
                    engine=item.lang_config.get("voicemaker_engine"),
                    language_code=item.lang_code,
                    chunk_index=item.chunk_index
                )

                if vm_task_id:
                    self.submitted_tasks[task_key][vm_task_id] = {
                        "chunk_index": item.chunk_index,
                        "item": item,
                        "submitted_at": time.time()
                    }
                    self.task_groups[task_key].add(vm_task_id)
                    logger.info(f"VoicemakerAsync -> Відправлено {vm_task_id} для chunk {item.chunk_index}")
                else:
                    logger.error(f"VoicemakerAsync -> Не вдалося створити завдання для chunk {item.chunk_index}")

                # Затримка між запитами (крім останнього)
                if i < len(items) - 1:
                    time.sleep(self.submission_delay)

            except Exception as e:
                logger.exception(f"VoicemakerAsync -> Помилка відправки chunk {item.chunk_index}: {e}")

        logger.info(f"VoicemakerAsync -> Завершено відправку всіх завдань для {task_key}")

    def check_and_download_ready_tasks(self, task_key: str) -> list:
        """
        Перевіряє готові завдання та завантажує їх.
        Повертає список успішно завантажених AudioPipelineItem.
        """
        if task_key not in self.submitted_tasks:
            return []

        downloaded_items = []
        tasks_info = self.submitted_tasks[task_key]

        # Отримуємо список готових завдань
        ready_task_ids = self.vm_api.get_ready_tasks()

        for vm_task_id in ready_task_ids:
            if vm_task_id in tasks_info and vm_task_id in self.task_groups.get(task_key, set()):
                task_info = tasks_info[vm_task_id]
                item = task_info["item"]

                try:
                    # Завантажуємо готовий файл
                    success, remain_chars = self.vm_api.download_completed_task(vm_task_id, item.output_path)

                    if success:
                        downloaded_items.append(item)
                        self.completed_items[task_key].append(item)

                        # Видаляємо з submitted_tasks
                        del tasks_info[vm_task_id]

                        logger.info(f"VoicemakerAsync -> Завантажено chunk {item.chunk_index} для {task_key}")
                    else:
                        logger.error(f"VoicemakerAsync -> Не вдалося завантажити chunk {item.chunk_index}")

                except Exception as e:
                    logger.exception(f"VoicemakerAsync -> Помилка завантаження chunk {item.chunk_index}: {e}")

        return downloaded_items
    
    def get_task_progress(self, task_key: str) -> dict:
        """Повертає прогрес виконання завдань."""
        if task_key not in self.submitted_tasks:
            return {"submitted": 0, "completed": 0, "ready": 0, "pending": 0}
            
        tasks_info = self.submitted_tasks[task_key]
        completed_count = len(self.completed_items.get(task_key, []))
        
        ready_count = 0
        pending_count = 0
        
        for vm_task_id in tasks_info.keys():
            status = self.vm_api.get_task_status(vm_task_id)
            if status == "ready":
                ready_count += 1
            elif status == "pending":
                pending_count += 1
        
        return {
            "submitted": len(tasks_info) + completed_count,
            "completed": completed_count,
            "ready": ready_count,
            "pending": pending_count
        }
    
    def is_task_group_completed(self, task_key: str, expected_total: int) -> bool:
        """Перевіряє чи всі завдання в групі завершені."""
        completed_count = len(self.completed_items.get(task_key, []))
        return completed_count >= expected_total

class AudioWorkerPool:
    """
    Керований пул для генерації аудіо та субтитрів.
    Воркери лише виконують завдання; вся логіка керування знаходиться в WorkflowManager.
    """
    def __init__(self, app_instance, max_workers: int):
        self.app = app_instance
        self.max_workers = max_workers
        self.audio_queue = queue.Queue()
        self.transcription_queue = queue.Queue()
        self.audio_results_queue = queue.Queue() # Сюди воркери кладуть результати озвучки
        self.is_running = False
        self.shutdown_event = threading.Event()
        self.workers = []
        
        # Асинхронний обробник для Voicemaker
        self.voicemaker_handler = VoicemakerAsyncHandler(app_instance)

    def start(self):
        if self.is_running: return
        self.is_running = True
        self.shutdown_event.clear()
        
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._audio_worker, args=(i,), daemon=True)
            worker.start()
            self.workers.append(worker)
            
        transcription_worker = threading.Thread(target=self._transcription_worker, daemon=True)
        transcription_worker.start()
        self.workers.append(transcription_worker)
        logger.info(f"AudioWorkerPool запущено з {self.max_workers} аудіо-воркерами та 1 воркером транскрипції.")

    def stop(self):
        if not self.is_running: return
        logger.info("Зупинка AudioWorkerPool...")
        self.shutdown_event.set()
        
        # Відправляємо "отруйні пігулки", щоб гарантовано завершити потоки
        for _ in range(len(self.workers)):
            self.audio_queue.put(None)
            self.transcription_queue.put(None)
        
        for worker in self.workers:
            worker.join(timeout=5)
            
        self.is_running = False
        self.workers.clear()
        logger.info("AudioWorkerPool зупинено.")

    def add_audio_task(self, item: AudioPipelineItem):
        self.audio_queue.put(item)

    def add_transcription_task(self, item: TranscriptionPipelineItem):
        logger.info(f"Додання завдання транскрипції в чергу: {item.task_key} chunk {item.chunk_index}, audio_path: {item.audio_path}")
        self.transcription_queue.put(item)
    
    def submit_voicemaker_tasks_async(self, items: list) -> str:
        """Відправляє групу Voicemaker завдань асинхронно."""
        return self.voicemaker_handler.submit_voicemaker_tasks(items)
    
    def check_voicemaker_progress(self, task_key: str) -> list:
        """Перевіряє та завантажує готові Voicemaker файли."""
        return self.voicemaker_handler.check_and_download_ready_tasks(task_key)
    
    def get_voicemaker_progress(self, task_key: str) -> dict:
        """Отримує прогрес виконання Voicemaker завдань."""
        return self.voicemaker_handler.get_task_progress(task_key)
    
    def is_voicemaker_group_completed(self, task_key: str, expected_total: int) -> bool:
        """Перевіряє чи завершена група Voicemaker завдань."""
        return self.voicemaker_handler.is_task_group_completed(task_key, expected_total)
        
    def _audio_worker(self, worker_id: int):
        while not self.shutdown_event.is_set():
            try:
                item = self.audio_queue.get(timeout=1)
                if item is None: break
                
                if hasattr(self.app, 'log_context'):
                    self.app.log_context.parallel_task = 'Audio Gen'
                    self.app.log_context.worker_id = f'Chunk {worker_id + 1}'
                
                logger.info(f"AudioWorker-{worker_id}: Початок {item.task_key} chunk {item.chunk_index}")
                success = self._generate_audio_chunk(item)
                
                result = AudioWorkerResult(success=success, item=item)
                self.audio_results_queue.put(result)
                
                self.audio_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception(f"AudioWorker-{worker_id}: Критична помилка: {e}")
        logger.info(f"AudioWorker-{worker_id} завершено")

    def _transcription_worker(self):
        while not self.shutdown_event.is_set():
            try:
                item = self.transcription_queue.get(timeout=1)
                if item is None: break

                logger.info(f"TranscriptionWorker: Отримано завдання {item.task_key} chunk {item.chunk_index}, audio_path: {item.audio_path}")

                if item.audio_path is None:
                    logger.warning(f"TranscriptionWorker: audio_path = None для {item.task_key} chunk {item.chunk_index}")
                    item.subs_path = None
                    self.app.workflow_manager.transcription_results_queue.put(item)
                    self.transcription_queue.task_done()
                    continue

                if hasattr(self.app, 'log_context'):
                    self.app.log_context.parallel_task = 'Transcription'
                    self.app.log_context.worker_id = 'Transcribe'
                
                logger.info(f"TranscriptionWorker: Початок транскрипції {item.task_key} chunk {item.chunk_index}")
                subs_path = self._generate_transcription_chunk(item)
                item.subs_path = subs_path
                
                if subs_path:
                    logger.info(f"TranscriptionWorker: Успішно створено транскрипцію для {item.task_key} chunk {item.chunk_index}: {subs_path}")
                else:
                    logger.error(f"TranscriptionWorker: Не вдалося створити транскрипцію для {item.task_key} chunk {item.chunk_index}")
                
                self.app.workflow_manager.transcription_results_queue.put(item)
                
                self.transcription_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception(f"TranscriptionWorker: Критична помилка: {e}")
        logger.info("TranscriptionWorker завершено")

    def _generate_audio_chunk(self, item: AudioPipelineItem) -> bool:
        """Генерує аудіо файл для текстового фрагменту."""
        try:
            tts_service = item.lang_config.get("tts_service", "elevenlabs")
            
            if tts_service == "elevenlabs":
                task_id = self.app.el_api.create_audio_task(
                    item.text_chunk, 
                    item.lang_config.get("elevenlabs_template_uuid")
                )
                if task_id and self.app.el_api.wait_for_elevenlabs_task(self.app, task_id, item.output_path):
                    return True
                        
            elif tts_service == "voicemaker":
                voice_id = item.lang_config.get("voicemaker_voice_id")
                engine = item.lang_config.get("voicemaker_engine")
                success, _ = self.app.vm_api.generate_audio(
                    item.text_chunk, voice_id, engine, item.lang_code, item.output_path
                )
                return success
                    
            elif tts_service == "speechify":
                success, _ = self.app.speechify_api.generate_audio_streaming(
                    text=item.text_chunk,
                    voice_id=item.lang_config.get("speechify_voice_id"),
                    model=item.lang_config.get("speechify_model"),
                    output_path=item.output_path,
                    emotion=item.lang_config.get("speechify_emotion"),
                    pitch=item.lang_config.get("speechify_pitch", 0),
                    rate=item.lang_config.get("speechify_rate", 0)
                )
                return success
                    
            return False
            
        except Exception as e:
            logger.exception(f"Помилка генерації аудіо: {e}")
            return False
            
    def _generate_transcription_chunk(self, item: TranscriptionPipelineItem) -> Optional[str]:
        """Генерує транскрипцію для аудіо файлу."""
        try:
            subs_dir = os.path.join(item.output_dir, "subs")
            os.makedirs(subs_dir, exist_ok=True)
            
            subs_path = os.path.join(subs_dir, f"subs_chunk_{item.chunk_index}.ass")
            
            if self.app.montage_api.create_subtitles(item.audio_path, subs_path):
                return subs_path
            else:
                logger.error(f"Помилка створення субтитрів для {item.audio_path}")
                return None
                
        except Exception as e:
            logger.exception(f"Помилка генерації транскрипції: {e}")
            return None
