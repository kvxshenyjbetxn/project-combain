# core/audio_pipeline.py
import logging
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional
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
        self.created_at = time.time()

class TranscriptionPipelineItem:
    """Елемент для обробки в транскрипційному пайплайні."""
    def __init__(self, audio_path: str, output_dir: str, chunk_index: int, 
                 lang_code: str, task_key: str, is_merged_group: bool = False):
        self.audio_path = audio_path
        self.output_dir = output_dir
        self.chunk_index = chunk_index
        self.lang_code = lang_code
        self.task_key = task_key
        self.is_merged_group = is_merged_group  # Позначає чи це об'єднана група
        self.created_at = time.time()

class AudioWorkerPool:
    """Воркер пул для генерації аудіо з динамічною кількістю потоків."""
    
    def __init__(self, app_instance, max_workers: int):
        self.app = app_instance
        self.max_workers = max_workers
        self.audio_queue = queue.Queue()
        self.transcription_queue = queue.Queue()
        self.results = {}  # task_key -> {chunk_index: audio_path}
        self.completed_tasks = set()  # Завершені task_key
        self.is_running = False
        self.shutdown_event = threading.Event()
        self.workers = []
        
    def start(self):
        """Запускає воркер пул."""
        if self.is_running:
            return
            
        self.is_running = True
        self.shutdown_event.clear()
        
        # Запускаємо аудіо воркери
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._audio_worker, 
                args=(i,), 
                name=f"AudioWorker-{i}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
            
        # Запускаємо єдиний транскрипційний воркер
        transcription_worker = threading.Thread(
            target=self._transcription_worker,
            name="TranscriptionWorker",
            daemon=True
        )
        transcription_worker.start()
        self.workers.append(transcription_worker)
        
        logger.info(f"AudioWorkerPool запущено з {self.max_workers} аудіо воркерами та 1 транскрипційним воркером")
        
    def stop(self):
        """Зупиняє воркер пул."""
        if not self.is_running:
            return
            
        logger.info("Зупинка AudioWorkerPool...")
        self.shutdown_event.set()
        self.is_running = False
        
        # Додаємо poison pills для завершення воркерів
        for _ in range(self.max_workers):
            self.audio_queue.put(None)
        self.transcription_queue.put(None)
        
        # Чекаємо завершення всіх воркерів
        for worker in self.workers:
            worker.join(timeout=10)
            
        self.workers.clear()
        logger.info("AudioWorkerPool зупинено")
        
    def add_audio_task(self, item: AudioPipelineItem):
        """Додає завдання для генерації аудіо."""
        if not self.is_running:
            logger.error("AudioWorkerPool не запущено!")
            return
            
        self.audio_queue.put(item)
        logger.debug(f"Додано аудіо завдання: {item.task_key} chunk {item.chunk_index}")
        
    def get_completed_audio_for_task(self, task_key: str) -> Optional[List[str]]:
        """Повертає список готових аудіо файлів для завдання, якщо всі готові."""
        if task_key not in self.results:
            return None
            
        task_results = self.results[task_key]
        if not task_results:
            return None
            
        # Перевіряємо чи всі частини готові
        max_chunk = max(task_results.keys())
        expected_chunks = list(range(max_chunk + 1))
        
        if set(task_results.keys()) == set(expected_chunks):
            # Всі частини готові, повертаємо відсортований список
            audio_files = [task_results[i] for i in expected_chunks if task_results[i]]
            return audio_files if len(audio_files) == len(expected_chunks) else None
            
        return None
        
    def get_ready_audio_groups_for_transcription(self, task_key: str, tts_service: str, num_target_chunks: int) -> Optional[List[str]]:
        """
        Повертає готові аудіо групи для транскрипції (об'єднані для VoiceMaker/Speechify).
        Використовується для оптимізації транскрипції сервісів з багатьма малими частинами.
        """
        audio_files = self.get_completed_audio_for_task(task_key)
        if not audio_files:
            return None
            
        # Для ElevenLabs повертаємо як є
        if tts_service not in ["voicemaker", "speechify"]:
            return audio_files
            
        # Для VoiceMaker/Speechify об'єднуємо в групи перед транскрипцією
        if len(audio_files) > num_target_chunks:
            return self._create_merged_audio_groups(audio_files, task_key, num_target_chunks)
        else:
            return audio_files
            
    def _create_merged_audio_groups(self, audio_files: List[str], task_key: str, num_target_chunks: int) -> List[str]:
        """Створює об'єднані аудіо групи для кращої транскрипції."""
        try:
            from utils.media_utils import concatenate_audio_files
            import numpy as np
            import os
            
            # Розбиваємо файли на групи
            chunk_groups = np.array_split(audio_files, num_target_chunks)
            merged_files = []
            
            # Створюємо тимчасову папку для об'єднаних файлів
            temp_dir = os.path.dirname(audio_files[0])
            merged_dir = os.path.join(temp_dir, "merged_for_transcription")
            os.makedirs(merged_dir, exist_ok=True)
            
            for i, group in enumerate(chunk_groups):
                if len(group) == 0:
                    continue
                    
                if len(group) == 1:
                    # Якщо в групі один файл, просто додаємо його
                    merged_files.append(group[0])
                else:
                    # Об'єднуємо кілька файлів в один
                    merged_file_path = os.path.join(merged_dir, f"merged_transcription_group_{task_key}_{i}.mp3")
                    if concatenate_audio_files(list(group), merged_file_path):
                        merged_files.append(merged_file_path)
                        logger.info(f"Об'єднано {len(group)} аудіо файлів в {os.path.basename(merged_file_path)}")
                    else:
                        logger.error(f"Помилка об'єднання аудіо групи {i} для завдання {task_key}")
                        return None
                        
            return merged_files if len(merged_files) > 0 else None
            
        except Exception as e:
            logger.exception(f"Помилка створення об'єднаних аудіо груп: {e}")
            return None
        
    def is_task_completed(self, task_key: str) -> bool:
        """Перевіряє чи завершено завдання повністю (аудіо + транскрипція)."""
        return task_key in self.completed_tasks
        
    def _audio_worker(self, worker_id: int):
        """Воркер для генерації аудіо."""
        logger.info(f"AudioWorker-{worker_id} запущено")
        
        while not self.shutdown_event.is_set():
            try:
                # Отримуємо завдання з черги
                item = self.audio_queue.get(timeout=1)
                
                if item is None:  # Poison pill
                    break
                    
                # Додаткова перевірка shutdown_event
                if self.shutdown_event.is_set():
                    logger.info(f"AudioWorker-{worker_id}: Отримано сигнал зупинки")
                    break
                    
                logger.info(f"AudioWorker-{worker_id}: Обробка {item.task_key} chunk {item.chunk_index}")
                
                # Встановлюємо контекст для логування
                if hasattr(self.app, 'log_context'):
                    self.app.log_context.parallel_task = 'Audio Gen'
                    self.app.log_context.worker_id = f'Worker-{worker_id}'
                
                # Генеруємо аудіо
                success = self._generate_audio_chunk(item)
                
                if success:
                    # Зберігаємо результат
                    if item.task_key not in self.results:
                        self.results[item.task_key] = {}
                    self.results[item.task_key][item.chunk_index] = item.output_path
                    
                    # Додаємо до черги транскрипції
                    trans_item = TranscriptionPipelineItem(
                        audio_path=item.output_path,
                        output_dir=os.path.dirname(item.output_path),
                        chunk_index=item.chunk_index,
                        lang_code=item.lang_code,
                        task_key=item.task_key
                    )
                    self.transcription_queue.put(trans_item)
                    
                    logger.info(f"AudioWorker-{worker_id}: Завершено {item.task_key} chunk {item.chunk_index}")
                else:
                    logger.error(f"AudioWorker-{worker_id}: Помилка генерації {item.task_key} chunk {item.chunk_index}")
                
                self.audio_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception(f"AudioWorker-{worker_id}: Критична помилка: {e}")
                
        logger.info(f"AudioWorker-{worker_id} завершено")
        
    def _transcription_worker(self):
        """Воркер для генерації транскрипції (завжди 1 потік)."""
        logger.info("TranscriptionWorker запущено")
        
        transcription_results = {}  # task_key -> {chunk_index: subs_path}
        
        while not self.shutdown_event.is_set():
            try:
                # Отримуємо завдання з черги
                item = self.transcription_queue.get(timeout=1)
                
                if item is None:  # Poison pill
                    break
                    
                # Додаткова перевірка shutdown_event
                if self.shutdown_event.is_set():
                    logger.info("TranscriptionWorker: Отримано сигнал зупинки")
                    break
                    
                logger.info(f"TranscriptionWorker: Обробка {item.task_key} chunk {item.chunk_index}")
                
                # Встановлюємо контекст для логування
                if hasattr(self.app, 'log_context'):
                    self.app.log_context.parallel_task = 'Transcription'
                    self.app.log_context.worker_id = 'TransWorker'
                
                # Генеруємо транскрипцію
                subs_path = self._generate_transcription_chunk(item)
                
                if subs_path:
                    # Зберігаємо результат транскрипції
                    if item.task_key not in transcription_results:
                        transcription_results[item.task_key] = {}
                    transcription_results[item.task_key][item.chunk_index] = subs_path
                    
                    # Перевіряємо чи всі частини транскрипції готові для цього завдання
                    if self._check_transcription_completion(item.task_key, transcription_results):
                        self.completed_tasks.add(item.task_key)
                        logger.info(f"TranscriptionWorker: Завершено повну обробку {item.task_key}")
                    
                    logger.info(f"TranscriptionWorker: Завершено {item.task_key} chunk {item.chunk_index}")
                else:
                    logger.error(f"TranscriptionWorker: Помилка транскрипції {item.task_key} chunk {item.chunk_index}")
                
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
                new_balance = self.app.el_api.balance
                if new_balance is not None:
                    self.app._update_elevenlabs_balance_labels(new_balance)
                if task_id and task_id != "INSUFFICIENT_BALANCE":
                    if self.app.el_api.wait_for_elevenlabs_task(self.app, task_id, item.output_path):
                        return True
                        
            elif tts_service == "voicemaker":
                voice_id = item.lang_config.get("voicemaker_voice_id")
                engine = item.lang_config.get("voicemaker_engine")
                success, new_balance = self.app.vm_api.generate_audio(
                    item.text_chunk, voice_id, engine, item.lang_code, item.output_path
                )
                if success:
                    if new_balance is not None:
                        vm_text = new_balance if new_balance is not None else 'N/A'
                        self.app.root.after(0, lambda: self.app.settings_vm_balance_label.config(
                            text=f"{self.app._t('balance_label')}: {vm_text}"
                        ))
                    return True
                    
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
                if success:
                    return True
                    
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
            
    def _check_transcription_completion(self, task_key: str, transcription_results: Dict) -> bool:
        """Перевіряє чи завершена транскрипція для всього завдання."""
        if task_key not in self.results or task_key not in transcription_results:
            return False
            
        audio_chunks = set(self.results[task_key].keys())
        transcription_chunks = set(transcription_results[task_key].keys())
        
        return audio_chunks == transcription_chunks and len(audio_chunks) > 0

    def queue_audio_for_transcription(self, audio_path: str, output_dir: str, 
                                     chunk_index: int, lang_code: str, task_key: str,
                                     is_merged_group: bool = False):
        """Додає аудіо в чергу для транскрипції."""
        item = TranscriptionPipelineItem(
            audio_path=audio_path,
            output_dir=output_dir,
            chunk_index=chunk_index,
            lang_code=lang_code,
            task_key=task_key,
            is_merged_group=is_merged_group
        )
        self.transcription_queue.put(item)
        print(f"Додано в чергу транскрипції: {audio_path} ({'група' if is_merged_group else 'частина'})")

    def process_ready_groups_for_transcription(self, tts_service: str):
        """Обробляє готові групи аудіо для транскрипції залежно від TTS сервісу."""
        try:
            if tts_service in ['voicemaker', 'speechify']:
                # Для VoiceMaker та Speechify створюємо об'єднані групи
                with self.completed_audio_lock:
                    # Групуємо за завданнями
                    tasks_groups = {}
                    for item in list(self.completed_audio_items):
                        if item.task_key not in tasks_groups:
                            tasks_groups[item.task_key] = []
                        tasks_groups[item.task_key].append(item)
                    
                    # Обробляємо кожне завдання окремо
                    for task_key, items in tasks_groups.items():
                        if len(items) < 2:
                            # Якщо менше 2 частин, обробляємо індивідуально
                            for item in items:
                                self.queue_audio_for_transcription(
                                    audio_path=item.audio_path,
                                    output_dir=item.output_dir,
                                    chunk_index=item.chunk_index,
                                    lang_code=item.lang_code,
                                    task_key=item.task_key,
                                    is_merged_group=False
                                )
                                self.completed_audio_items.remove(item)
                            continue
                        
                        # Сортуємо за chunk_index
                        items.sort(key=lambda x: x.chunk_index)
                        
                        # Розбиваємо на групи (використовуємо 3 як target групи для 3 потоків)
                        import numpy as np
                        target_groups = min(3, len(items))  # Не більше 3 груп
                        chunk_groups = np.array_split(items, target_groups)
                        
                        for i, group in enumerate(chunk_groups):
                            if len(group) == 0:
                                continue
                                
                            if len(group) == 1:
                                # Одна частина - обробляємо індивідуально
                                item = group[0]
                                self.queue_audio_for_transcription(
                                    audio_path=item.audio_path,
                                    output_dir=item.output_dir,
                                    chunk_index=item.chunk_index,
                                    lang_code=item.lang_code,
                                    task_key=item.task_key,
                                    is_merged_group=False
                                )
                            else:
                                # Кілька частин - об'єднуємо в групу
                                merged_path = self._merge_audio_files_for_transcription(list(group), f"{task_key}_group_{i}")
                                if merged_path:
                                    self.queue_audio_for_transcription(
                                        audio_path=merged_path,
                                        output_dir=group[0].output_dir,
                                        chunk_index=group[0].chunk_index,
                                        lang_code=group[0].lang_code,
                                        task_key=task_key,
                                        is_merged_group=True
                                    )
                                    print(f"Додано об'єднану групу {i+1} в транскрипцію: {len(group)} частин -> {merged_path}")
                        
                        # Видаляємо оброблені елементи
                        for item in items:
                            if item in self.completed_audio_items:
                                self.completed_audio_items.remove(item)
                                
            else:
                # Для ElevenLabs та інших сервісів обробляємо індивідуальні частини
                with self.completed_audio_lock:
                    for item in list(self.completed_audio_items):
                        self.queue_audio_for_transcription(
                            audio_path=item.audio_path,
                            output_dir=item.output_dir,
                            chunk_index=item.chunk_index,
                            lang_code=item.lang_code,
                            task_key=item.task_key,
                            is_merged_group=False
                        )
                        
                        # Видаляємо оброблений елемент
                        self.completed_audio_items.remove(item)
                        
        except Exception as e:
            logger.exception(f"Помилка обробки груп для транскрипції: {e}")

    def _merge_audio_files_for_transcription(self, items: List[AudioPipelineItem], task_key: str) -> str:
        """Об'єднує аудіо файли в один для транскрипції."""
        try:
            # Імпортуємо функцію з utils
            from utils.media_utils import concatenate_audio_files
            
            # Створюємо назву для об'єднаного файла
            first_item = items[0]
            merged_filename = f"merged_for_transcription_{task_key}_{int(time.time())}.wav"
            merged_path = os.path.join(first_item.output_dir, merged_filename)
            
            # Створюємо список шляхів аудіо файлів
            audio_paths = [item.audio_path for item in items if os.path.exists(item.audio_path)]
            
            # Об'єднуємо файли
            if concatenate_audio_files(audio_paths, merged_path):
                print(f"Створено об'єднаний файл для транскрипції: {merged_path} з {len(items)} частин")
                return merged_path
            else:
                logger.error(f"Помилка об'єднання аудіо файлів для транскрипції")
                return None
            
        except Exception as e:
            logger.exception(f"Помилка при об'єднанні аудіо файлів: {e}")
            return None
