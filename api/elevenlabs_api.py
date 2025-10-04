import requests
import logging
import time

logger = logging.getLogger("TranslationApp")

class ElevenLabsAPI:
    def __init__(self, config):
        self.api_key = config["elevenlabs"]["api_key"]
        self.base_url = config["elevenlabs"]["base_url"]
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        self.balance = None
        self.templates = []

    def test_connection(self):
        if not self.api_key:
            return False, "Ключ API не встановлено."
        try:
            url = f"{self.base_url}/balance"
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.balance = data.get("balance", 0)
                return True, f"З'єднання успішне. Баланс: {self.balance}"
            elif response.status_code == 401:
                return False, "Недійсний ключ API."
            else:
                return False, f"Помилка API: {response.status_code} - {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Не вдалося підключитися: {e}"

    def update_balance(self):
        if not self.api_key:
            self.balance = None
            return None
        url = f"{self.base_url}/balance"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                self.balance = response.json().get("balance", 0)
                logger.info(f"ElevenLabs -> Баланс оновлено: {self.balance}")
                return self.balance
        except requests.exceptions.RequestException as e:
            logger.error(f"ElevenLabs -> Помилка мережі при оновленні балансу: {e}")
        return None

    def get_balance(self):
        """Перевіряє баланс, надсилаючи мінімальний запит."""
        if not self.api_key:
            logger.warning("ElevenLabs -> Ключ API не встановлено, неможливо отримати баланс.")
            return None
        
        payload = {
            "Engine": "neural",
            "VoiceId": "ai3-Jony",
            "LanguageCode": "en-US", 
            "Text": ".",
            "OutputFormat": "mp3"
        }
        
        try:
            response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=20)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    return data.get("remainChars")
            logger.error(f"ElevenLabs -> Не вдалося отримати баланс. Статус: {response.status_code}, Повідомлення: {response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"ElevenLabs -> Помилка мережі при отриманні балансу: {e}")
            return None

    def update_templates(self):
        if not self.api_key:
            self.templates = []
            return []
        url = f"{self.base_url}/templates"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                self.templates = response.json()
                logger.info(f"ElevenLabs -> Шаблони оновлено: знайдено {len(self.templates)}.")
                return self.templates
        except requests.exceptions.RequestException as e:
            logger.error(f"ElevenLabs -> Помилка мережі при оновленні шаблонів: {e}")
        return []

    def get_templates(self):
        return self.templates

    def create_audio_task(self, text, template_uuid=None):
        if not self.api_key: 
            logger.error("ElevenLabs -> Ключ API не встановлено."); 
            return None
        if not text: 
            logger.error("ElevenLabs -> Текст для озвучення порожній."); 
            return None
        
        logger.info("ElevenLabs -> Створення завдання на генерацію аудіо...")
        url = f"{self.base_url}/tasks"
        payload = {"text": text}
        if template_uuid: 
            payload["template_uuid"] = template_uuid
        
        notification_sent = False
        while True:
            try:
                response = requests.post(url, headers=self.headers, json=payload, timeout=20)
                
                if response.status_code == 200:
                    data = response.json()
                    task_id = data.get("task_id")
                    logger.info(f"ElevenLabs -> Завдання успішно створено. ID: {task_id}")
                    self.update_balance()
                    return task_id
                
                elif response.status_code == 402:
                    if not notification_sent:
                        logger.warning("ElevenLabs -> НЕПРИПУСТИМИЙ БАЛАНС. Програма чекатиме та повторюватиме спробу кожні 60 секунд. Будь ласка, поповніть свій рахунок.")
                        notification_sent = True
                    time.sleep(60)
                    continue
                
                elif response.status_code in [401, 422]:
                    logger.error(f"ElevenLabs -> Критична помилка ({response.status_code}): {response.text}. Зупинка.")
                    return None
                
                else:
                    logger.warning(f"ElevenLabs -> Помилка сервера ({response.status_code}). Повторна спроба через 10с...")
                    time.sleep(10)

            except requests.exceptions.RequestException as e:
                logger.error(f"ElevenLabs -> Помилка мережі: {e}. Повторна спроба через 10с...")
                time.sleep(10)

    def check_task_status(self, task_id):
        if not task_id: 
            return None
        url = f"{self.base_url}/tasks/{task_id}/status"
        while True:
            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    return response.json().get("status")
                if response.status_code == 404:
                    logger.warning(f"ElevenLabs -> Завдання {task_id} не знайдено (404).")
                    return "not_found"
                if response.status_code == 401:
                    logger.error("ElevenLabs -> Недійсний ключ API при перевірці статусу.")
                    return None
                logger.error(f"ElevenLabs -> Перевірка статусу не вдалася ({response.status_code}). Повторна спроба через 10с...")
                time.sleep(10)
            except requests.exceptions.RequestException as e:
                logger.error(f"ElevenLabs -> Помилка мережі при перевірці статусу: {e}. Повторна спроба через 10с...")
                time.sleep(10)

    def download_audio(self, task_id, output_path):
        if not task_id: 
            return False
        logger.info(f"ElevenLabs -> Спроба завантаження аудіо для завдання {task_id}...")
        url = f"{self.base_url}/tasks/{task_id}/result"
        while True:
            try:
                response = requests.get(url, headers={"X-API-Key": self.api_key}, timeout=180)
                if response.status_code == 200 and response.headers.get('content-type') == 'audio/mpeg':
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"ElevenLabs -> УСПІХ: Аудіо збережено в {output_path}")
                    return True
                if response.status_code == 202:
                    logger.info(f"ElevenLabs -> Аудіо для завдання {task_id} ще не готове (статус 202). Очікування...")
                    return False 
                if response.status_code in [404, 500, 502, 503, 504]:
                    logger.error(f"ElevenLabs -> Помилка завантаження ({response.status_code}). Повторна спроба через 10с...")
                    time.sleep(10)
                else:
                    logger.error(f"ElevenLabs -> КРИТИЧНА ПОМИЛКА: Помилка завантаження, статус {response.status_code}, що не передбачає повторних спроб.")
                    return False
            except requests.exceptions.RequestException as e:
                logger.error(f"ElevenLabs -> Помилка мережі при завантаженні: {e}. Повторна спроба через 10с...")
                time.sleep(10)

    def wait_for_elevenlabs_task(self, app, task_id, output_path):
        """Wait for ElevenLabs task completion and download the result."""
        max_wait_time, wait_interval, waited_time = 600, 15, 0
        
        while waited_time < max_wait_time:
            if not app._check_app_state(): 
                return False

            status = self.check_task_status(task_id)
            logger.info(f"[Chain] Audio task {task_id} status: {status}")

            if status == 'ending':
                logger.info(f"Task {task_id} is ready. Attempting to download.")
                time.sleep(2)
                return self.download_audio(task_id, output_path)
            
            if status in ['error', 'error_handled']:
                logger.error(f"Task {task_id} failed with status '{status}'.")
                return False

            if status in ['waiting', 'processing']:
                pass
            
            elif status == 'ending_processed':
                 logger.warning(f"Task {task_id} has status 'ending_processed', which means the audio was already downloaded and possibly deleted.")
                 return False

            elif status is None:
                logger.error(f"Failed to get status for task {task_id}. Aborting wait.")
                return False

            # Робимо очікування переривчастим
            for _ in range(wait_interval):
                if not app._check_app_state(): 
                    return False
                time.sleep(1)
            waited_time += wait_interval

        logger.warning(f"[Chain] Timed out waiting for audio task {task_id}.")
        return False