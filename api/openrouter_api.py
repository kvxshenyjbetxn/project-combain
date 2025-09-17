# api/openrouter_api.py

import logging
import requests
import time
import json

# Імпортуємо конфігурацію, від якої залежить клас
from constants.default_config import DEFAULT_CONFIG

# Отримуємо існуючий логер
logger = logging.getLogger("TranslationApp")

class OpenRouterAPI:
    def __init__(self, config):
        self.api_key = config["openrouter"]["api_key"]
        self.base_url = "https://openrouter.ai/api/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "TranslationApp",
            "Content-Type": "application/json"
        }
        self.translation_model = config["openrouter"]["translation_model"]
        self.prompt_model = config["openrouter"]["prompt_model"]
        self.translation_params = config["openrouter"]["translation_params"]
        self.prompt_params = config["openrouter"]["prompt_params"]
        self.config = config

    def test_connection(self):
        if not self.api_key:
            return False, "Ключ API не встановлено."
        try:
            test_model = "openai/gpt-4o-mini"
            payload = {
                "model": test_model,
                "messages": [{"role": "user", "content": "Ping"}],
                "max_tokens": 1
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload, timeout=10)
            if response.status_code == 200:
                return True, "З'єднання успішне."
            else:
                return False, f"Помилка API: {response.status_code} - {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Не вдалося підключитися: {e}"

    def get_balance(self):
        """Отримує баланс OpenRouter через /api/v1/key endpoint."""
        if not self.api_key:
            logger.warning("OpenRouter -> Ключ API не встановлено, неможливо отримати баланс.")
            return None
            
        try:
            url = f"{self.base_url}/key"
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json().get('data', {})
                limit = data.get('limit')
                usage = data.get('usage', 0)
                
                if limit is None:
                    # Немає ліміту, показуємо тільки використання
                    balance_text = f"Usage: ${usage:.4f}"
                    logger.info(f"OpenRouter -> Баланс оновлено: {balance_text}")
                    return balance_text
                else:
                    # Є ліміт, показуємо залишок
                    remaining = limit - usage
                    balance_text = f"${remaining:.4f} left"
                    logger.info(f"OpenRouter -> Баланс оновлено: {balance_text}")
                    return balance_text
            else:
                logger.error(f"OpenRouter -> ПОМИЛКА: Не вдалося отримати баланс. Статус: {response.status_code}, Повідомлення: {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenRouter -> Помилка мережі при отриманні балансу: {e}")
            return None

    def call_model(self, model, messages, params, task_description=""):
        if not self.api_key:
            logger.error("OpenRouter -> Ключ API не встановлено.")
            return None
        
        payload = {"model": model, "messages": messages, **params}
        url = f"{self.base_url}/chat/completions"
        
        logger.info(f"OpenRouter -> {task_description}: Виклик моделі '{model}'...")
        
        # Новий форматований вивід пейлоаду
        payload_str = json.dumps(payload, indent=2, ensure_ascii=False)
        logger.debug(f"OpenRouter -> Пейлоад запиту:\n--- ПОЧАТОК ЗАПИТУ ---\n{payload_str}\n--- КІНЕЦЬ ЗАПИТУ ---")

        retry_delay = 10 
        while True:
            try:
                response = requests.post(url, headers=self.headers, json=payload, timeout=180)
                
                if response.status_code == 200:
                    response_data = response.json()
                    if 'choices' in response_data and len(response_data['choices']) > 0:
                        message_content = response_data['choices'][0].get('message', {}).get('content')
                        if message_content:
                            logger.info(f"OpenRouter -> УСПІХ: Отримано відповідь від моделі '{model}'.")
                            return message_content.strip()
                    logger.error("OpenRouter -> ПОМИЛКА: Неочікувана структура відповіді.")
                    return None

                elif response.status_code == 429 or response.status_code >= 500:
                    error_type = "Перевищено ліміт запитів" if response.status_code == 429 else "Помилка сервера"
                    logger.warning(f"OpenRouter -> {error_type} ({response.status_code}). Повторна спроба через {retry_delay}с...")
                    time.sleep(retry_delay)
                
                else:
                    logger.error(f"OpenRouter -> КРИТИЧНА ПОМИЛКА ({response.status_code}): {response.text}. Зупинка.")
                    return None

            except requests.exceptions.RequestException as e:
                logger.error(f"OpenRouter -> Помилка мережі: {e}. Повторна спроба через {retry_delay}с...")
                time.sleep(retry_delay)

    def translate_text(self, text, model, params, target_language_name, custom_prompt_template=None):
        if custom_prompt_template:
            prompt_template = custom_prompt_template
        else:
            prompt_template = DEFAULT_CONFIG["default_prompts"]["translation"]
        
        prompt = prompt_template.format(text=text, language=target_language_name)
        messages = [{"role": "user", "content": prompt}]
        return self.call_model(model, messages, params, f"Translation to {target_language_name}")

    def rewrite_text(self, text, model, params, custom_prompt_template):
        prompt = custom_prompt_template.format(text=text)
        messages = [{"role": "user", "content": prompt}]
        return self.call_model(model, messages, params, "Rewriting Text")

    def generate_image_prompts(self, text, model, params, lang_name=""):
        prompt_template = self.config.get("default_prompts", {}).get("image_prompt_generation", DEFAULT_CONFIG["default_prompts"]["image_prompt_generation"])
        prompt = prompt_template.format(text=text)
        messages = [{"role": "user", "content": prompt}]
        task_desc = f"Генерація промптів зображень ({lang_name})"
        return self.call_model(model, messages, params, task_desc)

    def generate_call_to_action(self, text, model, params, lang_name=""):
        prompt_template = self.config.get("default_prompts", {}).get("call_to_action", DEFAULT_CONFIG["default_prompts"]["call_to_action"])
        prompt = prompt_template.format(text=text)
        messages = [{"role": "user", "content": prompt}]
        task_desc = f"Генерація заклику до дії ({lang_name})"
        return self.call_model(model, messages, params, task_desc)