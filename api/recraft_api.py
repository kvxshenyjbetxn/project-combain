# api/recraft_api.py

import logging
import requests

# Отримуємо існуючий логер
logger = logging.getLogger("TranslationApp")

class RecraftAPI:
    def __init__(self, config):
        self.config = config.get("recraft", {})
        self.api_key = self.config.get("api_key", "")
        self.base_url = "https://external.api.recraft.ai/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def get_balance(self):
        """Запитує та повертає баланс кредитів Recraft."""
        if not self.api_key:
            logger.warning("Recraft -> Ключ API не встановлено, неможливо отримати баланс.")
            return None
        try:
            url = f"{self.base_url}/users/me"
            response = requests.get(url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10)
            if response.status_code == 200:
                return response.json().get("credits")
            else:
                logger.error(f"Recraft -> ПОМИЛКА: Не вдалося отримати баланс. Статус: {response.status_code}, Повідомлення: {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Recraft -> ПОМИЛКА: Помилка мережі при отриманні балансу: {e}")
            return None

    def test_connection(self):
        if not self.api_key:
            return False, "Ключ API Recraft не встановлено."
        try:
            url = f"{self.base_url}/users/me"
            response = requests.get(url, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10)
            if response.status_code == 200:
                user_info = response.json()
                credits = user_info.get('credits', 'N/A')
                return True, f"З'єднання успішне. Користувач: {user_info.get('name')}\nБаланс: {credits} кредитів"
            else:
                return False, f"Помилка API: {response.status_code} - {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Не вдалося підключитися: {e}"

    def generate_image(self, prompt, output_path, width=None, height=None, **kwargs):
        if not self.api_key:
            logger.error("Recraft -> ПОМИЛКА: Ключ API не встановлено.")
            return False, None

        if kwargs:
            logger.info(f"Recraft -> Ігноруються додаткові параметри для генерації: {kwargs}")

        url = f"{self.base_url}/images/generations"
        
        payload = {
            "prompt": prompt,
            "model": self.config.get("model", "recraftv3"),
            "style": self.config.get("style", "digital_illustration"),
            "size": self.config.get("size", "1024x1024")
        }
        if self.config.get("substyle"):
            payload["substyle"] = self.config.get("substyle")
            
        negative_prompt = self.config.get("negative_prompt", "")
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        logger.info(f"Recraft -> Відправка запиту на генерацію зображення. Пейлоад: {payload}")

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=180)
            if response.status_code == 200:
                data = response.json()
                image_url = data.get("data", [{}])[0].get("url")
                if image_url:
                    image_response = requests.get(image_url, timeout=180)
                    if image_response.status_code == 200:
                        with open(output_path, 'wb') as f:
                            f.write(image_response.content)
                        logger.info(f"Recraft -> УСПІХ: Зображення збережено в {output_path}")
                        new_balance = self.get_balance()
                        return True, new_balance
                    else:
                        logger.error(f"Recraft -> ПОМИЛКА: Не вдалося завантажити зображення з URL. Статус: {image_response.status_code}")
                        return False, None
                else:
                    logger.error("Recraft -> ПОМИЛКА: Відповідь API не містить URL зображення.")
                    return False, None
            else:
                logger.error(f"Recraft -> ПОМИЛКА API ({response.status_code}): {response.text}")
                return False, None
        except requests.exceptions.RequestException as e:
            logger.error(f"Recraft -> ПОМИЛКА: Запит не вдався: {e}")
            return False, None