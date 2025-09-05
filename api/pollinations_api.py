# api/pollinations_api.py

import logging
import requests
import time
import urllib.parse
import threading

# Отримуємо існуючий логер
logger = logging.getLogger("TranslationApp")

class PollinationsAPI:
    def __init__(self, config, app_instance):
        self.token = config["pollinations"].get("token")
        self.model = config["pollinations"]["model"]
        self.width = config["pollinations"]["width"]
        self.height = config["pollinations"]["height"]
        self.timeout = config["pollinations"]["timeout"]
        self.retries = config["pollinations"]["retries"]
        self.remove_logo = config["pollinations"]["remove_logo"]
        self.base_url = "https://image.pollinations.ai"
        self.app = app_instance

    def test_connection(self):
        try:
            test_prompt = "test image"
            params = {"model": self.model, "timeout": 5}
            if self.token:
                params['token'] = self.token
            
            encoded_prompt = urllib.parse.quote(test_prompt)
            url = f"{self.base_url}/prompt/{encoded_prompt}"
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code < 500:
                 return True, "Запит на з'єднання надіслано (код стану вказує на потенційний успіх)."
            else:
                 return False, f"Помилка API: {response.status_code} - {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Не вдалося підключитися: {e}"

    def generate_image(self, prompt, output_path, width=None, height=None, **kwargs):
        if not prompt:
            logger.error("Pollinations -> ПОМИЛКА: Промпт для генерації зображення порожній.")
            return False
        
        logger.info(f"Pollinations -> Відправка запиту на генерацію зображення. Промпт: {prompt}")

        use_width = width if width is not None else self.width
        use_height = height if height is not None else self.height
        
        params = {
            "model": self.model, 
            "width": use_width, 
            "height": use_height,
            "nologo": self.remove_logo
        }
        if self.token: 
            params['token'] = self.token

        if 'model' in kwargs:
            params['model'] = kwargs['model']
        
        params.update(kwargs)
        
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"{self.base_url}/prompt/{encoded_prompt}"
        
        retry_delay = 10 
        
        # Кількість спроб тепер береться з налаштувань, а не з константи
        # Головна логіка перемикання буде в combain.py, тут ми просто робимо N спроб
        max_retries = self.app.config.get("pollinations", {}).get("retries", 5)

        for attempt in range(1, max_retries + 1):
            try:
                # Перевірка на пропуск користувачем на початку кожної ітерації
                if self.app.skip_image_event.is_set():
                    logger.warning("Pollinations -> Генерацію ОДНОГО зображення пропущено користувачем.")
                    self.app.skip_image_event.clear()
                    return False

                logger.info(f"Pollinations -> Генерація зображення (спроба #{attempt}/{max_retries})...")
                
                response = requests.get(url, params=params, timeout=180)
                
                if response.status_code == 200 and response.headers.get('content-type', '').startswith('image/'):
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Pollinations -> УСПІХ: Зображення збережено в {output_path}")
                    return True
                else:
                    logger.warning(f"Pollinations -> Спроба #{attempt} не вдалася. Статус: {response.status_code}.")
            
            except requests.exceptions.RequestException as e:
                logger.error(f"Pollinations -> ПОМИЛКА: Запит не вдався (спроба #{attempt}): {e}.")

            # Якщо це не остання спроба, чекаємо перед повтором
            if attempt < max_retries:
                logger.info(f"Повторна спроба через {retry_delay}с...")
                if self.app.skip_image_event.wait(timeout=retry_delay):
                    logger.warning("Pollinations -> Генерацію пропущено користувачем під час очікування.")
                    self.app.skip_image_event.clear()
                    return False

        # Якщо всі спроби провалилися
        logger.error(f"Pollinations -> Не вдалося згенерувати зображення після {max_retries} спроб.")
        return False