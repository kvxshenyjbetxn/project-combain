# api/voicemaker_api.py

import logging
import requests
import time

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