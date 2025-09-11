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
        self.completed_audio_items = []  # Готові аудіо елементи для ElevenLabs
        self.completed_audio_lock = threading.Lock()  # Lock для completed_audio_items
        self.worker_column_mapping = {}  # worker_id -> column_number для GUI логів
        self.is_running = False
        self.shutdown_event = threading.Event()
        self.workers = []
        
    def start(self):
        """Запускає воркер пул."""
        if self.is_running:
            return
            
        self.is_running = True
        self.shutdown_event.clear()
        
        # Створюємо мапінг worker_id до колонок для GUI
        for i in range(self.max_workers):
            column_num = i + 1
            worker_id = f"Chunk {column_num}"
            self.worker_column_mapping[worker_id] = column_num
        
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
            
        # Зупиняємо batch executor якщо існує
        if hasattr(self, 'batch_executor'):
            self.batch_executor.shutdown(wait=True)
            
        # ФІНАЛЬНА ПЕРЕВІРКА: обробляємо файли, що завершилися після зупинки
        logger.info("Фінальна перевірка залишкових аудіо файлів для транскрипції...")
        with self.completed_audio_lock:
            remaining_items = len(self.completed_audio_items)
            if remaining_items > 0:
                logger.warning(f"Знайдено {remaining_items} необроблених аудіо файлів після зупинки воркерів")
                
                # Обробляємо кожен залишковий файл окремо
                for item in list(self.completed_audio_items):
                    logger.info(f"Фінальна обробка: {item.task_key} chunk {item.chunk_index}")
                    self.queue_audio_for_transcription(
                        audio_path=item.output_path,
                        output_dir=os.path.dirname(item.output_path),
                        chunk_index=item.chunk_index,
                        lang_code=item.lang_code,
                        task_key=item.task_key,
                        is_merged_group=False
                    )
                    
                # Запускаємо окремий транскрипційний воркер для обробки залишків
                if not self.transcription_queue.empty():
                    logger.info("Запуск фінального транскрипційного воркера...")
                    final_worker = threading.Thread(
                        target=self._final_transcription_worker,
                        name="FinalTranscriptionWorker",
                        daemon=False
                    )
                    final_worker.start()
                    final_worker.join(timeout=60)  # Чекаємо максимум 1 хвилину
                    
                # Очищуємо список після обробки
                self.completed_audio_items.clear()
            
        self.workers.clear()
        logger.info("AudioWorkerPool зупинено")
        
    def add_audio_task(self, item: AudioPipelineItem):
        """Додає завдання для генерації аудіо."""
        if not self.is_running:
            logger.error("AudioWorkerPool не запущено!")
            return
        
        tts_service = item.lang_config.get("tts_service", "elevenlabs")
        
        # Для VoiceMaker/Speechify групуємо завдання за task_key для batch обробки
        if tts_service in ['voicemaker', 'speechify']:
            if not hasattr(self, 'batch_tasks'):
                self.batch_tasks = {}  # task_key -> список AudioPipelineItem
                self.batch_processing_status = {}  # task_key -> статус обробки
            
            if item.task_key not in self.batch_tasks:
                self.batch_tasks[item.task_key] = []
                self.batch_processing_status[item.task_key] = 'collecting'
            
            self.batch_tasks[item.task_key].append(item)
            logger.debug(f"Batch: Зібрано {len(self.batch_tasks[item.task_key])}/{item.total_chunks} частин для {item.task_key}")
            
            # Перевіряємо чи всі частини для цього завдання зібрані
            if len(self.batch_tasks[item.task_key]) == item.total_chunks:
                # Всі частини готові - запускаємо batch обробку
                logger.info(f"Batch: Запуск обробки {item.total_chunks} частин для {item.task_key} ({tts_service})")
                self._start_batch_processing(item.task_key, tts_service)
        else:
            # Для ElevenLabs додаємо в звичайну чергу (негайна обробка)
            self.audio_queue.put(item)
            logger.debug(f"ElevenLabs: Додано аудіо завдання: {item.task_key} chunk {item.chunk_index}")
        
    def _start_batch_processing(self, task_key: str, tts_service: str):
        """Запускає batch обробку для VoiceMaker/Speechify."""
        if task_key not in self.batch_tasks:
            return
            
        self.batch_processing_status[task_key] = 'processing'
        items = self.batch_tasks[task_key]
        
        # Запускаємо batch обробку в окремому потоці
        batch_thread = threading.Thread(
            target=self._process_batch_items,
            args=(task_key, items, tts_service),
            name=f"BatchProcessor-{task_key}",
            daemon=True
        )
        batch_thread.start()
        
    def _process_batch_items(self, task_key: str, items: List[AudioPipelineItem], tts_service: str):
        """Обробляє всі частини batch завдання з інтервалом 1 секунда."""
        try:
            logger.info(f"Batch: Початок обробки {len(items)} частин для {task_key}")
            
            # Відправляємо всі частини на озвучку з інтервалом 1 секунда
            processing_items = []
            for i, item in enumerate(items):
                if self.shutdown_event.is_set():
                    break
                    
                # Встановлюємо контекст для логування
                if hasattr(self.app, 'log_context'):
                    self.app.log_context.parallel_task = f'Batch {tts_service.title()}'
                    # Для batch використовуємо циклічний worker_id для розподілу по колонкам
                    worker_column = (i % self.max_workers) + 1  
                    self.app.log_context.worker_id = f'Chunk {worker_column}'
                
                logger.info(f"Batch-{tts_service}: Відправка {item.task_key} chunk {i}/{len(items)-1} на {tts_service.upper()} API (інтервал 1 сек)")
                
                # Запускаємо генерацію аудіо (неблокуюча)
                future = self._start_audio_generation_async(item)
                processing_items.append((item, future))
                
                # Чекаємо 1 секунду перед наступною відправкою (крім останньої)
                if i < len(items) - 1:
                    time.sleep(1)
            
            # Чекаємо завершення всіх частин
            logger.info(f"Batch: Очікування завершення {len(processing_items)} частин для {task_key}")
            completed_items = []
            
            for item, future in processing_items:
                if self.shutdown_event.is_set():
                    break
                    
                try:
                    # Чекаємо завершення генерації
                    success = future.result(timeout=300)  # 5 хвилин таймаут
                    if success:
                        completed_items.append(item)
                        logger.info(f"Batch: Завершено частину {item.chunk_index+1} для {task_key}")
                    else:
                        logger.error(f"Batch: Помилка генерації частини {item.chunk_index+1} для {task_key}")
                        
                except Exception as e:
                    logger.exception(f"Batch: Виняток при обробці частини {item.chunk_index+1}: {e}")
            
            # Всі частини завершені - тепер групуємо для транскрипції
            if completed_items and len(completed_items) == len(items):
                logger.info(f"Batch: Всі {len(completed_items)} частин готові, починаємо групування для транскрипції")
                self._group_batch_for_transcription(task_key, completed_items)
                self.batch_processing_status[task_key] = 'completed'
            else:
                logger.error(f"Batch: Завершено тільки {len(completed_items)}/{len(items)} частин для {task_key}")
                self.batch_processing_status[task_key] = 'failed'
                
        except Exception as e:
            logger.exception(f"Batch: Критична помилка при обробці {task_key}: {e}")
            self.batch_processing_status[task_key] = 'failed'
            
    def _start_audio_generation_async(self, item: AudioPipelineItem):
        """Запускає асинхронну генерацію аудіо."""
        from concurrent.futures import ThreadPoolExecutor
        
        # Створюємо окремий executor для batch обробки
        if not hasattr(self, 'batch_executor'):
            self.batch_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="BatchAudio")
        
        return self.batch_executor.submit(self._generate_audio_chunk, item)
        
    def _group_batch_for_transcription(self, task_key: str, completed_items: List[AudioPipelineItem]):
        """Групує готові batch частини для транскрипції."""
        try:
            import numpy as np
            import shutil
            
            # Сортуємо за chunk_index
            completed_items.sort(key=lambda x: x.chunk_index)
            
            # Створюємо окрему папку для об'єднаних файлів
            base_dir = os.path.dirname(completed_items[0].output_path)
            batch_merged_dir = os.path.join(base_dir, "batch_merged")
            os.makedirs(batch_merged_dir, exist_ok=True)
            logger.info(f"Batch: Створено папку для об'єднаних файлів: {batch_merged_dir}")
            
            # Створюємо НОВУ логіку групування: [1]+[2]+[3+4] замість [1+2]+[3]+[4]
            # Це забезпечує більш рівномірний розподіл тривалості
            target_groups = min(self.max_workers, len(completed_items))
            
            if len(completed_items) == 4 and target_groups == 3:
                # Спеціальна логіка для 4 файлів → 3 групи: [0], [1], [2+3]
                chunk_groups = [
                    [completed_items[0]],  # Перший файл окремо
                    [completed_items[1]],  # Другий файл окремо  
                    [completed_items[2], completed_items[3]]  # Останні два файли разом
                ]
                logger.info(f"Batch: Спеціальна логіка 4→3: [0], [1], [2+3] для {task_key}")
            else:
                # Стандартна логіка для інших випадків
                chunk_groups = np.array_split(completed_items, target_groups)
                logger.info(f"Batch: Стандартна логіка для {len(completed_items)} файлів → {target_groups} груп")
            
            logger.info(f"Batch: Створюємо {len(chunk_groups)} груп для транскрипції {task_key}")
            
            # Додаткове логування для розуміння логіки
            for j, grp in enumerate(chunk_groups):
                indices = [item.chunk_index for item in grp]
                logger.info(f"Batch: Група {j} містить оригінальні чанки: {indices}")
            
            # Оновлюємо self.results для batch_merged файлів
            if task_key not in self.results:
                self.results[task_key] = {}
            
            # Очищуємо старі результати та створюємо нові для batch_merged
            old_results = self.results[task_key].copy()
            self.results[task_key] = {}
            logger.info(f"Batch: Очищено старі результати {task_key}: {list(old_results.keys())} → нові будуть {list(range(len(chunk_groups)))}")
            
            for i, group in enumerate(chunk_groups):
                if len(group) == 0:
                    continue
                    
                if len(group) == 1:
                    # Одна частина - копіюємо в нову папку з batch_ префіксом
                    item = group[0]
                    source_path = item.output_path
                    final_path = os.path.join(batch_merged_dir, f"batch_audio_chunk_{i}.mp3")
                    
                    # Видаляємо файл якщо існує
                    if os.path.exists(final_path):
                        os.remove(final_path)
                        logger.debug(f"Batch: Видалено існуючий файл {final_path}")
                    
                    # Копіюємо файл
                    shutil.copy2(source_path, final_path)
                    logger.debug(f"Batch: Скопійовано одиночний файл → {final_path}")
                    
                    # Оновлюємо self.results для batch_merged файлу
                    self.results[task_key][i] = final_path
                    logger.debug(f"Batch: Оновлено self.results[{task_key}][{i}] = {final_path}")
                    
                    self.queue_audio_for_transcription(
                        audio_path=final_path,
                        output_dir=base_dir,
                        chunk_index=i,  # Використовуємо послідовний індекс
                        lang_code=item.lang_code,
                        task_key=item.task_key,
                        is_merged_group=False
                    )
                    logger.info(f"Batch: Додано індивідуальну частину {i} в транскрипцію")
                else:
                    # Кілька частин - об'єднуємо в групу з batch_ префіксом
                    merged_path = self._merge_audio_files_for_transcription(list(group), f"{task_key}_batch_group_{i}")
                    if merged_path:
                        # Переміщуємо об'єднаний файл в папку batch_merged з новою назвою
                        final_path = os.path.join(batch_merged_dir, f"batch_audio_chunk_{i}.mp3")
                        
                        # Видаляємо файл якщо існує
                        if os.path.exists(final_path):
                            os.remove(final_path)
                            logger.debug(f"Batch: Видалено існуючий файл {final_path}")
                        
                        if os.path.exists(merged_path) and merged_path != final_path:
                            try:
                                shutil.move(merged_path, final_path)
                                logger.debug(f"Batch: Переміщено об'єднаний файл → {final_path}")
                            except Exception as e:
                                logger.error(f"Batch: Помилка переміщення {merged_path} → {final_path}: {e}")
                                # Якщо не вдалося перемістити, використовуємо оригінальний шлях
                                final_path = merged_path
                        
                        # Оновлюємо self.results для batch_merged файлу
                        self.results[task_key][i] = final_path
                        logger.debug(f"Batch: Оновлено self.results[{task_key}][{i}] = {final_path}")
                        
                        self.queue_audio_for_transcription(
                            audio_path=final_path,
                            output_dir=base_dir,
                            chunk_index=i,  # Використовуємо послідовний індекс
                            lang_code=group[0].lang_code,
                            task_key=task_key,
                            is_merged_group=True
                        )
                        logger.info(f"Batch: Додано об'єднану групу {i} ({len(group)} частин) в транскрипцію")
                        
            logger.info(f"Batch: ЗАВЕРШЕНО групування для {task_key}. Фінальні результати: {list(self.results[task_key].keys())}")
                        
        except Exception as e:
            logger.exception(f"Batch: Помилка групування для транскрипції {task_key}: {e}")
        
        
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
        # Визначаємо GUI колонку для цього воркера
        column_num = worker_id + 1
        gui_worker_id = f"Chunk {column_num}"
        
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
                    self.app.log_context.worker_id = gui_worker_id  # Використовуємо консистентний GUI worker_id
                
                logger.info(f"AudioWorker-{worker_id}: ПОЧАТОК обробки {item.task_key} chunk {item.chunk_index}/{item.total_chunks-1} ({item.lang_config.get('tts_service', 'elevenlabs')})")
                
                # Генеруємо аудіо
                success = self._generate_audio_chunk(item)
                
                if success:
                    # Зберігаємо результат
                    if item.task_key not in self.results:
                        self.results[item.task_key] = {}
                    self.results[item.task_key][item.chunk_index] = item.output_path
                    
                    # Для ElevenLabs додаємо до completed_audio_items для негайної обробки
                    tts_service = item.lang_config.get("tts_service", "elevenlabs")
                    if tts_service == "elevenlabs":
                        with self.completed_audio_lock:
                            self.completed_audio_items.append(item)
                        logger.info(f"AudioWorker-{worker_id}: ElevenLabs {item.task_key} chunk {item.chunk_index} → completed_audio_items (негайна обробка)")
                    else:
                        # VoiceMaker/Speechify обробляються через batch систему
                        logger.info(f"AudioWorker-{worker_id}: {tts_service} {item.task_key} chunk {item.chunk_index} → batch система")
                    
                    logger.info(f"AudioWorker-{worker_id}: ЗАВЕРШЕНО {item.task_key} chunk {item.chunk_index}")
                else:
                    logger.error(f"AudioWorker-{worker_id}: ПОМИЛКА генерації {item.task_key} chunk {item.chunk_index}")
                
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
                    
                logger.info(f"TranscriptionWorker: ПОЧАТОК обробки {item.task_key} chunk {item.chunk_index} ({'група' if item.is_merged_group else 'частина'})")
                
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
                        logger.info(f"TranscriptionWorker: ЗАВЕРШЕНО повну обробку {item.task_key}")
                    
                    logger.info(f"TranscriptionWorker: ЗАВЕРШЕНО {item.task_key} chunk {item.chunk_index} ({'група' if item.is_merged_group else 'частина'})")
                else:
                    logger.error(f"TranscriptionWorker: ПОМИЛКА транскрипції {item.task_key} chunk {item.chunk_index}")
                
                self.transcription_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception(f"TranscriptionWorker: Критична помилка: {e}")
                
        logger.info("TranscriptionWorker завершено")

    def _final_transcription_worker(self):
        """Фінальний транскрипційний воркер для обробки залишкових файлів."""
        logger.info("FinalTranscriptionWorker запущено")
        
        while True:
            try:
                # Отримуємо завдання з черги
                item = self.transcription_queue.get(timeout=5)  # Коротший timeout
                
                if item is None:  # Poison pill
                    break
                    
                logger.info(f"FinalTranscriptionWorker: Обробка {item.task_key} chunk {item.chunk_index}")
                
                # Встановлюємо контекст для логування
                if hasattr(self.app, 'log_context'):
                    self.app.log_context.parallel_task = 'Transcription'
                    self.app.log_context.worker_id = 'Final'
                
                # Генеруємо транскрипцію
                subs_path = self._generate_transcription_chunk(item)
                
                if subs_path:
                    # Додаємо завдання до завершених
                    self.completed_tasks.add(item.task_key)
                    logger.info(f"FinalTranscriptionWorker: ЗАВЕРШЕНО {item.task_key} chunk {item.chunk_index}")
                else:
                    logger.error(f"FinalTranscriptionWorker: ПОМИЛКА транскрипції {item.task_key} chunk {item.chunk_index}")
                    
            except queue.Empty:
                # Черга порожня - завершуємо роботу
                break
            except Exception as e:
                logger.exception(f"FinalTranscriptionWorker: ПОМИЛКА {e}")
                
        logger.info("FinalTranscriptionWorker завершено")
        
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
                # VoiceMaker/Speechify тепер використовують batch обробку
                # Перевіряємо статус batch завдань
                if hasattr(self, 'batch_processing_status'):
                    for task_key, status in self.batch_processing_status.items():
                        if status == 'completed':
                            logger.debug(f"Batch: Завдання {task_key} вже оброблено через batch систему")
                return  # Нічого не робимо, batch система все обробила
                
            # Для ElevenLabs та інших сервісів обробляємо індивідуальні частини
            with self.completed_audio_lock:
                for item in list(self.completed_audio_items):
                    self.queue_audio_for_transcription(
                        audio_path=item.output_path,  # Виправлено: використовуємо output_path замість audio_path
                        output_dir=os.path.dirname(item.output_path),  # Виправлено: отримуємо директорію з шляху
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
            merged_path = os.path.join(os.path.dirname(first_item.output_path), merged_filename)
            
            # Створюємо список шляхів аудіо файлів
            audio_paths = [item.output_path for item in items if os.path.exists(item.output_path)]
            
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
