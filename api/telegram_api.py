# api/telegram_api.py

import logging
import requests
import time
import threading

# Отримуємо існуючий логер
logger = logging.getLogger("TranslationApp")

class TelegramAPI:
    def __init__(self, config):
        self.config = config.get("telegram", {})
        self.enabled = self.config.get("enabled", False)
        self.api_key = self.config.get("api_key", "")
        self.chat_id = self.config.get("chat_id", "")
        self.base_url = f"https://api.telegram.org/bot{self.api_key}"

    def test_connection(self):
        if not self.api_key:
            return False, "Ключ API Telegram не встановлено."
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=10)
            if response.status_code == 200 and response.json().get("ok"):
                bot_name = response.json().get("result", {}).get("username")
                return True, f"З'єднання успішне. Бот: @{bot_name}"
            else:
                return False, f"Помилка API: {response.status_code} - {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Не вдалося підключитися: {e}"

    def send_message(self, message):
        if not all([self.enabled, self.api_key, self.chat_id]):
            logger.debug("Telegram -> Сповіщення вимкнені або не налаштовані. Пропускаємо.")
            return

        url = f"{self.base_url}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'MarkdownV2'
        }
        
        retry_delay = 10
        while True:
            try:
                response = requests.post(url, json=payload, timeout=10)
                
                if response.status_code == 200:
                    logger.info(f"Telegram -> Сповіщення успішно надіслано в чат ID {self.chat_id}.")
                    return
                
                elif 400 <= response.status_code < 500:
                    logger.error(f"Telegram -> КРИТИЧНА ПОМИЛКА: Не вдалося надіслати сповіщення через помилку клієнта ({response.status_code}): {response.text}. Зупинка.")
                    return
                
                else:
                    logger.warning(f"Telegram -> Помилка сервера ({response.status_code}). Повторна спроба через {retry_delay}с...")
                    time.sleep(retry_delay)

            except requests.exceptions.RequestException as e:
                logger.error(f"Telegram -> Помилка мережі при відправці сповіщення: {e}. Повторна спроба через {retry_delay}с...")
                time.sleep(retry_delay)

    def send_message_in_thread(self, message):
        """Відправляє повідомлення у окремому потоці, щоб не блокувати GUI."""
        thread = threading.Thread(target=self.send_message, args=(message,), daemon=True)
        thread.start()

    def send_plain_text_message(self, message):
        """Відправляє просте текстове повідомлення без форматування."""
        if not all([self.enabled, self.api_key, self.chat_id]):
            logger.debug("Telegram -> Сповіщення вимкнені або не налаштовані. Пропускаємо.")
            return

        url = f"{self.base_url}/sendMessage"
        payload = {'chat_id': self.chat_id, 'text': message}
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info(f"Telegram -> Просте текстове сповіщення успішно надіслано в чат ID {self.chat_id}.")
            else:
                logger.error(f"Telegram -> Помилка надсилання простого тексту ({response.status_code}): {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram -> Помилка мережі при відправці простого тексту: {e}")

    def send_plain_text_in_thread(self, message):
        """Відправляє просте текстове повідомлення у окремому потоці."""
        thread = threading.Thread(target=self.send_plain_text_message, args=(message,), daemon=True)
        thread.start()

    def send_message_with_buttons(self, message, buttons):
        if not all([self.enabled, self.api_key, self.chat_id]):
            logger.debug("Telegram -> Сповіщення вимкнені, надсилання кнопок скасовано.")
            return

        url = f"{self.base_url}/sendMessage"
        inline_keyboard = [[
            {"text": btn["text"], "callback_data": btn["callback_data"]} for btn in buttons
        ]]
        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': 'MarkdownV2',
            'reply_markup': {'inline_keyboard': inline_keyboard}
        }
        
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                logger.info("Telegram -> Повідомлення з кнопками успішно надіслано.")
            else:
                logger.error(f"Telegram -> Помилка надсилання повідомлення з кнопками ({response.status_code}): {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram -> Помилка мережі при надсиланні кнопок: {e}")

    def get_updates(self, offset=None):
        """Отримує оновлення від Telegram (для опитування)."""
        if not self.api_key:
            return None
        
        url = f"{self.base_url}/getUpdates"
        params = {'timeout': 10}
        if offset:
            params['offset'] = offset
            
        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Telegram -> Не вдалося отримати оновлення ({response.status_code}): {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram -> Помилка мережі при отриманні оновлень: {e}")
            return None

    def answer_callback_query(self, callback_query_id, text=None):
        """Відповідає на натискання кнопки, щоб прибрати годинник."""
        url = f"{self.base_url}/answerCallbackQuery"
        payload = {'callback_query_id': callback_query_id}
        if text:
            payload['text'] = text
        try:
            requests.post(url, json=payload, timeout=5)
        except requests.exceptions.RequestException as e:
            logger.warning(f"Telegram -> Не вдалося відповісти на callback_query: {e}")