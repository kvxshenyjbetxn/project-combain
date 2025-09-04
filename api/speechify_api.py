# api/speechify_api.py

import logging
import requests
import time
import json
import xml.sax.saxutils
import os

logger = logging.getLogger("TranslationApp")

class SpeechifyAPI:
    def __init__(self, config):
        self.config = config.get("speechify", {})
        self.api_key = self.config.get("api_key", "")
        self.base_url = "https://api.sws.speechify.com/v1" 
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

    def test_connection(self):
        """
        ФІНАЛЬНА ВЕРСІЯ. Використовує завідомо робочу українську комбінацію для тесту,
        щоб обійти дивну поведінку API з несумісними голосами.
        """
        if not self.api_key:
            return False, "Ключ API Speechify не встановлено."

        url = f"{self.base_url}/audio/speech" 
        
        payload = {
            "input": "Спіральна конфорка старої плити розколювалась нерівномірно. Миготіла, то затухаючи, то знову червоніючи.",
            "voice_id": "taras",
            "audio_format": "mp3",
            "model": "simba-multilingual"
        }

        logger.info(f"Speechify -> Тестовий запит: відправка перевіреного українського пейлоаду на {url}")

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=45)
            response.raise_for_status()
            response_json = response.json()
            
            if "audio_data" in response_json and response_json["audio_data"]:
                logger.info("Speechify -> Тест успішний. Отримано JSON з ключем audio_data.")
                return True, "З'єднання успішне. API ключ валідний."
            else:
                logger.error("Speechify -> ПОМИЛКА: API повернуло успішний статус, але JSON пошкоджено.")
                return False, "Відповідь від API отримана, але вона має неочікуваний формат."

        except requests.exceptions.HTTPError as e:
            error_text = e.response.text
            logger.error(f"Speechify -> ПОМИЛКА HTTP ({e.response.status_code}): {error_text}")
            return False, f"Помилка HTTP {e.response.status_code}. Перевірте API ключ та з'єднання.\nДеталі: {error_text}"
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
            logger.error(f"Speechify -> ПОМИЛКА: Помилка з'єднання або розбору JSON: {e}")
            return False, f"Не вдалося підключитися або обробити відповідь від API Speechify: {e}"

    def _build_ssml(self, text, emotion, pitch, rate):
        is_ssml_needed = (emotion and emotion != "Без емоцій") or (pitch != 0) or (rate != 0)
        if not is_ssml_needed:
            return text
        
        logger.debug("Speechify -> Створення SSML розмітки для тексту.")
        safe_text = xml.sax.saxutils.escape(text)
        if emotion and emotion != "Без емоцій":
            processed_text = f'<speechify:style emotion="{emotion}">{safe_text}</speechify:style>'
        else: 
            processed_text = safe_text
        
        def map_slider_to_val(value, mapping):
            for r, val in mapping.items():
                if r[0] <= value <= r[1]: return val
            return ""

        pitch_val = map_slider_to_val(pitch, {(-100, -61): "x-low", (-60, -21): "low", (21, 60): "high", (61, 100): "x-high"})
        rate_val = map_slider_to_val(rate, {(-100, -61): "x-slow", (-60, -21): "slow", (21, 60): "fast", (61, 100): "x-fast"})
        
        prosody_attrs = []
        if pitch_val: prosody_attrs.append(f'pitch="{pitch_val}"')
        if rate_val: prosody_attrs.append(f'rate="{rate_val}"')
        
        if prosody_attrs:
            processed_text = f'<prosody {" ".join(prosody_attrs)}>{processed_text}</prosody>'
        
        final_ssml = f'<speak>{processed_text}</speak>'
        logger.debug(f"Speechify -> Фінальний SSML: {final_ssml}")
        return final_ssml

    def generate_audio_streaming(self, text, voice_id, model, output_path, emotion=None, pitch=0, rate=0):
        if not self.api_key:
            logger.error("Speechify -> ПОМИЛКА: Ключ API не встановлено.")
            return False, None
            
        final_text = self._build_ssml(text, emotion, pitch, rate)
        payload = { "input": final_text, "voice_id": voice_id, "audio_format": "mp3", "model": model }
        url = f"{self.base_url}/audio/stream"
        
        headers_for_stream = self.headers.copy()
        headers_for_stream["Accept"] = "audio/mpeg"
        
        logger.debug(f"Speechify -> Відправка потокового запиту на URL: {url} з пейлоадом: {json.dumps(payload)}")
        for attempt in range(3):
            try:
                with requests.post(url, headers=headers_for_stream, json=payload, stream=True, timeout=300) as response:
                    if 'application/json' in response.headers.get('Content-Type', ''):
                        error_details = response.json()
                        logger.error(f"Speechify -> ПОМИЛКА API ({response.status_code}): {json.dumps(error_details, indent=2)}")
                        return False, None
                    response.raise_for_status()
                    
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    logger.info(f"Speechify -> УСПІХ: Аудіо успішно збережено в {output_path}")
                    return True, None
            except requests.exceptions.HTTPError as e:
                logger.error(f"Speechify -> ПОМИЛКА HTTP ({e.response.status_code}): {e.response.text}. Спроба {attempt + 1}/3.")
                time.sleep(5)
            except requests.exceptions.RequestException as e:
                logger.error(f"Speechify -> ПОМИЛКА: Запит не вдався: {e}. Спроба {attempt + 1}/3.")
                time.sleep(5)
                
        logger.error("Speechify -> КРИТИЧНА ПОМИЛКА: Усі спроби генерації аудіо не вдалися.")
        return False, None