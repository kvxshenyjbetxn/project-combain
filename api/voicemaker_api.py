# api/voicemaker_api.py

import logging
import requests
import time
import threading
from typing import Dict, Optional, Tuple

# Імпортуємо словник з голосами з папки constants
from constants.voicemaker_voices import VOICEMAKER_VOICES

# Отримуємо існуючий логер
logger = logging.getLogger("TranslationApp")

class VoiceMakerAPI:
    def __init__(self, config):
        self.api_key = config["voicemaker"]["api_key"]
        self.base_url = "https://developer.voicemaker.in/voice/api"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        # Для асинхронної обробки
        self.pending_tasks: Dict[str, dict] = {}  # task_id -> task_info
        self.completed_tasks: Dict[str, dict] = {}  # task_id -> result_info

    def get_balance(self):
        if not self.api_key:
            logger.warning("VoiceMaker -> Ключ API не встановлено, неможливо отримати баланс.")
            return None
        
        payload = {"Engine": "neural", "VoiceId": "ai3-Jony", "LanguageCode": "en-US", "Text": ".", "OutputFormat": "mp3"}
        try:
            response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=20)
            if response.status_code == 200 and response.json().get("success"):
                return response.json().get("remainChars")
            logger.error(f"VoiceMaker -> ПОМИЛКА: Не вдалося отримати баланс. Статус: {response.status_code}, Повідомлення: {response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"VoiceMaker -> ПОМИЛКА: Помилка мережі при отриманні балансу: {e}")
            return None

    def test_connection(self):
        if not self.api_key: return False, "Ключ API Voicemaker не встановлено."
        balance = self.get_balance()
        if balance is not None:
            return True, f"З'єднання з Voicemaker успішне.\nЗалишилось символів: {balance}"
        else:
            return False, "Не вдалося перевірити з'єднання або отримати баланс Voicemaker."

    def get_voices_for_language(self, lang_code):
        if lang_code in VOICEMAKER_VOICES: return VOICEMAKER_VOICES[lang_code]
        matching_voices = []
        prefix = lang_code + '-'
        for code, voices in VOICEMAKER_VOICES.items():
            if code.startswith(prefix): matching_voices.extend(voices)
        return matching_voices

    def generate_audio(self, text, voice_id, engine, language_code, output_path):
        if not self.api_key:
            logger.error("VoiceMaker -> ПОМИЛКА: Ключ API не встановлено.")
            return False, None
        
        logger.info(f"VoiceMaker -> Початок генерації аудіо для голосу '{voice_id}'...")
        text = text.replace('—', '-').replace('…', '...').replace('«', '"').replace('»', '"')
        payload = {"Engine": engine, "VoiceId": voice_id, "LanguageCode": language_code, "Text": text, "OutputFormat": "mp3", "SampleRate": "48000"}
        
        retry_delay = 10
        response_data = None

        while response_data is None:
            try:
                response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=180)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        response_data = data
                    else:
                        logger.error(f"VoiceMaker -> КРИТИЧНА ПОМИЛКА: Не вдалося перетворити текст: {data.get('message')}. Зупинка.")
                        return False, None
                else:
                    logger.warning(f"VoiceMaker -> Помилка API при генерації ({response.status_code}). Повторна спроба через {retry_delay}с...")
                    time.sleep(retry_delay)
            except requests.exceptions.RequestException as e:
                logger.error(f"VoiceMaker -> ПОМИЛКА: Запит на отримання URL не вдався: {e}. Повторна спроба через {retry_delay}с...")
                time.sleep(retry_delay)
        
        audio_url = response_data.get("path")
        if not audio_url:
            logger.error("VoiceMaker -> ПОМИЛКА: Відповідь API не містить шлях до аудіофайлу.")
            return False, None

        logger.info("VoiceMaker -> URL отримано, починається завантаження файлу...")
        while True:
            try:
                audio_response = requests.get(audio_url, timeout=180)
                if audio_response.status_code == 200:
                    with open(output_path, 'wb') as f:
                        f.write(audio_response.content)
                    logger.info(f"VoiceMaker -> УСПІХ: Аудіо успішно збережено в {output_path}")
                    return True, response_data.get("remainChars")
                else:
                    logger.warning(f"VoiceMaker -> Не вдалося завантажити аудіофайл ({audio_response.status_code}). Повторна спроба через {retry_delay}с...")
                    time.sleep(retry_delay)
            except requests.exceptions.RequestException as e:
                logger.error(f"VoiceMaker -> ПОМИЛКА: Запит на завантаження не вдався: {e}. Повторна спроба через {retry_delay}с...")
                time.sleep(retry_delay)

    def create_audio_task_async(self, text: str, voice_id: str, engine: str, language_code: str, chunk_index: int) -> Optional[str]:
        """
        Створює асинхронне завдання для генерації аудіо.
        Повертає task_id для відстеження, або None при помилці.
        """
        if not self.api_key:
            logger.error("VoiceMaker -> ПОМИЛКА: Ключ API не встановлено.")
            return None
        
        task_id = f"vm_task_{chunk_index}_{int(time.time())}"
        
        logger.info(f"VoiceMaker -> Створення асинхронного завдання {task_id} для chunk {chunk_index}")
        text = text.replace('—', '-').replace('…', '...').replace('«', '"').replace('»', '"')
        payload = {
            "Engine": engine, 
            "VoiceId": voice_id, 
            "LanguageCode": language_code, 
            "Text": text, 
            "OutputFormat": "mp3", 
            "SampleRate": "48000"
        }
        
        # Зберігаємо інформацію про завдання
        self.pending_tasks[task_id] = {
            "chunk_index": chunk_index,
            "payload": payload,
            "status": "pending",
            "created_at": time.time(),
            "audio_url": None,
            "error": None
        }
        
        # Запускаємо асинхронну обробку
        thread = threading.Thread(target=self._process_async_task, args=(task_id,), daemon=True)
        thread.start()
        
        return task_id

    def _process_async_task(self, task_id: str):
        """Обробляє асинхронне завдання в окремому потоці."""
        if task_id not in self.pending_tasks:
            return
            
        task_info = self.pending_tasks[task_id]
        retry_delay = 10
        
        try:
            # Надсилаємо запит на генерацію
            response = requests.post(self.base_url, headers=self.headers, json=task_info["payload"], timeout=180)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    task_info["audio_url"] = data.get("path")
                    task_info["remain_chars"] = data.get("remainChars")
                    task_info["status"] = "ready"
                    logger.info(f"VoiceMaker -> Асинхронне завдання {task_id} готове до завантаження")
                else:
                    task_info["error"] = f"Помилка генерації: {data.get('message')}"
                    task_info["status"] = "error"
                    logger.error(f"VoiceMaker -> Помилка в завданні {task_id}: {task_info['error']}")
            else:
                task_info["error"] = f"HTTP {response.status_code}: {response.text}"
                task_info["status"] = "error"
                logger.error(f"VoiceMaker -> HTTP помилка в завданні {task_id}: {task_info['error']}")
                
        except requests.exceptions.RequestException as e:
            task_info["error"] = f"Мережева помилка: {str(e)}"
            task_info["status"] = "error"
            logger.error(f"VoiceMaker -> Мережева помилка в завданні {task_id}: {task_info['error']}")

    def download_completed_task(self, task_id: str, output_path: str) -> Tuple[bool, Optional[int]]:
        """
        Завантажує готовий аудіофайл за task_id.
        Повертає (success, remain_chars).
        """
        if task_id not in self.pending_tasks:
            logger.error(f"VoiceMaker -> Завдання {task_id} не знайдено")
            return False, None
            
        task_info = self.pending_tasks[task_id]
        
        if task_info["status"] == "error":
            logger.error(f"VoiceMaker -> Завдання {task_id} завершилось з помилкою: {task_info['error']}")
            return False, None
            
        if task_info["status"] != "ready":
            logger.warning(f"VoiceMaker -> Завдання {task_id} ще не готове (статус: {task_info['status']})")
            return False, None
            
        audio_url = task_info["audio_url"]
        if not audio_url:
            logger.error(f"VoiceMaker -> Відсутній URL для завдання {task_id}")
            return False, None

        retry_delay = 10
        logger.info(f"VoiceMaker -> Початок завантаження {task_id}...")
        
        while True:
            try:
                audio_response = requests.get(audio_url, timeout=180)
                if audio_response.status_code == 200:
                    with open(output_path, 'wb') as f:
                        f.write(audio_response.content)
                    
                    remain_chars = task_info.get("remain_chars")
                    
                    # Переміщуємо в completed_tasks і видаляємо з pending
                    self.completed_tasks[task_id] = self.pending_tasks.pop(task_id)
                    
                    logger.info(f"VoiceMaker -> УСПІХ: Завдання {task_id} завантажено в {output_path}")
                    return True, remain_chars
                else:
                    logger.warning(f"VoiceMaker -> Не вдалося завантажити {task_id} ({audio_response.status_code}). Повторна спроба через {retry_delay}с...")
                    time.sleep(retry_delay)
            except requests.exceptions.RequestException as e:
                logger.error(f"VoiceMaker -> ПОМИЛКА завантаження {task_id}: {e}. Повторна спроба через {retry_delay}с...")
                time.sleep(retry_delay)

    def get_task_status(self, task_id: str) -> str:
        """Повертає статус завдання: 'pending', 'ready', 'error', 'completed', або 'not_found'."""
        if task_id in self.completed_tasks:
            return "completed"
        elif task_id in self.pending_tasks:
            return self.pending_tasks[task_id]["status"]
        else:
            return "not_found"

    def get_ready_tasks(self) -> list:
        """Повертає список task_id які готові до завантаження."""
        return [task_id for task_id, task_info in self.pending_tasks.items() 
                if task_info["status"] == "ready"]