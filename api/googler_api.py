# api/googler_api.py

import logging
import requests
import concurrent.futures
import threading
import base64
import time

logger = logging.getLogger("TranslationApp")

class GooglerAPI:
    def __init__(self, config):
        self.config = config.get("googler", {})
        self.api_key = self.config.get("api_key", "")
        self.base_url = "https://app.recrafter.fun/api/v1"
        self.max_threads = self.config.get("max_threads", 25)
        self.timeout = self.config.get("timeout", 180)
        self.aspect_ratio = self.config.get("aspect_ratio", "IMAGE_ASPECT_RATIO_LANDSCAPE")
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        self._lock = threading.Lock()

    def test_connection(self):
        """Тестує підключення до Googler API."""
        if not self.api_key:
            return False, "API ключ не встановлено."
        try:
            url = f"{self.base_url}/usage"
            response = requests.get(url, headers={"X-API-Key": self.api_key}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                limits = data.get('account_limits', {})
                current_usage = data.get('current_usage', {})
                hourly_usage = current_usage.get('hourly_usage', {})
                img_usage = hourly_usage.get('image_generation', {})
                
                img_limit = limits.get('img_gen_per_hour_limit', 'N/A')
                img_current = img_usage.get('current_usage', 'N/A')
                threads_allowed = limits.get('img_generation_threads_allowed', 'N/A')
                
                return True, f"З'єднання успішне.\nЛіміт зображень/годину: {img_limit}\nВикористано: {img_current}\nМакс. потоків: {threads_allowed}"
            else:
                return False, f"Помилка API: {response.status_code} - {response.text}"
        except requests.exceptions.RequestException as e:
            return False, f"Не вдалося підключитися: {e}"

    def get_usage_stats(self):
        """Отримує статистику використання API."""
        if not self.api_key:
            logger.warning("Googler -> API ключ не встановлено, неможливо отримати статистику.")
            return None
        try:
            url = f"{self.base_url}/usage"
            response = requests.get(url, headers={"X-API-Key": self.api_key}, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Googler -> ПОМИЛКА: Не вдалося отримати статистику. Статус: {response.status_code}, Повідомлення: {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Googler -> ПОМИЛКА: Помилка мережі при отриманні статистики: {e}")
            return None

    def generate_image(self, prompt, output_path, width=None, height=None, **kwargs):
        """Генерує одне зображення з промпту."""
        if not self.api_key:
            logger.error(f"Googler -> ПОМИЛКА: API ключ не встановлено. Config keys: {list(self.config.keys())}")
            return False

        if not prompt:
            logger.error("Googler -> ПОМИЛКА: Промпт порожній.")
            return False

        logger.info(f"Googler -> Відправка запиту на генерацію зображення. Промпт: {prompt}")

        url = f"{self.base_url}/images"
        
        aspect_ratio = kwargs.get('aspect_ratio', self.aspect_ratio)
        seed = kwargs.get('seed', None)
        
        payload = {
            "provider": "google_fx",
            "operation": "generate",
            "parameters": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio
            }
        }
        
        if seed is not None:
            payload["parameters"]["seed"] = seed

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    data_uri = data.get("result")
                    if data_uri and data_uri.startswith("data:image/"):
                        try:
                            header, encoded = data_uri.split(",", 1)
                            image_bytes = base64.b64decode(encoded)
                            with open(output_path, 'wb') as f:
                                f.write(image_bytes)
                            logger.info(f"Googler -> УСПІХ: Зображення збережено в {output_path}")
                            return True
                        except Exception as e:
                            logger.error(f"Googler -> ПОМИЛКА: Не вдалося декодувати зображення: {e}")
                            return False
                    else:
                        logger.error("Googler -> ПОМИЛКА: Відповідь не містить коректного data URI.")
                        return False
                else:
                    error = data.get("error", "Невідома помилка")
                    logger.error(f"Googler -> ПОМИЛКА API: {error}")
                    return False
            else:
                logger.error(f"Googler -> ПОМИЛКА API ({response.status_code}): {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Googler -> ПОМИЛКА: Запит не вдався: {e}")
            return False

    def generate_images_batch(self, prompts_with_paths, on_image_complete=None):
        """
        Генерує багато зображень одночасно зі збереженням хронології.
        
        Args:
            prompts_with_paths: список кортежів (prompt, output_path, index)
            on_image_complete: callback функція, що викликається після генерації кожного зображення
                               з параметрами (index, success, output_path)
        
        Returns:
            список кортежів (index, success, output_path) відсортований за індексом
        """
        if not prompts_with_paths:
            logger.warning("Googler -> Немає промптів для генерації.")
            return []

        logger.info(f"Googler -> Початок пакетної генерації {len(prompts_with_paths)} зображень з {self.max_threads} потоками.")

        results = []
        results_lock = threading.Lock()

        def worker(prompt, output_path, index):
            success = self.generate_image(prompt, output_path)
            
            with results_lock:
                results.append((index, success, output_path))
            
            if on_image_complete:
                on_image_complete(index, success, output_path)
            
            return (index, success, output_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = []
            for prompt, output_path, index in prompts_with_paths:
                future = executor.submit(worker, prompt, output_path, index)
                futures.append(future)
            
            concurrent.futures.wait(futures)

        sorted_results = sorted(results, key=lambda x: x[0])
        
        successful = sum(1 for _, success, _ in sorted_results if success)
        logger.info(f"Googler -> Завершено пакетну генерацію: {successful}/{len(prompts_with_paths)} успішно.")
        
        return sorted_results

    def transform_image(self, prompt, input_image_path, output_path):
        """Трансформує існуюче зображення за промптом."""
        if not self.api_key:
            logger.error("Googler -> ПОМИЛКА: API ключ не встановлено.")
            return False

        logger.info(f"Googler -> Трансформація зображення. Промпт: {prompt}")

        try:
            with open(input_image_path, 'rb') as f:
                image_bytes = f.read()
            
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            ext = input_image_path.lower().split('.')[-1]
            if ext == 'jpg':
                ext = 'jpeg'
            data_uri = f"data:image/{ext};base64,{base64_image}"
            
        except Exception as e:
            logger.error(f"Googler -> ПОМИЛКА: Не вдалося прочитати вхідне зображення: {e}")
            return False

        url = f"{self.base_url}/images"
        payload = {
            "provider": "google_fx",
            "operation": "transform",
            "parameters": {
                "prompt": prompt,
                "input_image": data_uri
            }
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    result_uri = data.get("result")
                    if result_uri and result_uri.startswith("data:image/"):
                        try:
                            header, encoded = result_uri.split(",", 1)
                            result_bytes = base64.b64decode(encoded)
                            with open(output_path, 'wb') as f:
                                f.write(result_bytes)
                            logger.info(f"Googler -> УСПІХ: Трансформоване зображення збережено в {output_path}")
                            return True
                        except Exception as e:
                            logger.error(f"Googler -> ПОМИЛКА: Не вдалося декодувати результат: {e}")
                            return False
                    else:
                        logger.error("Googler -> ПОМИЛКА: Відповідь не містить коректного data URI.")
                        return False
                else:
                    error = data.get("error", "Невідома помилка")
                    logger.error(f"Googler -> ПОМИЛКА API: {error}")
                    return False
            else:
                logger.error(f"Googler -> ПОМИЛКА API ({response.status_code}): {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Googler -> ПОМИЛКА: Запит не вдався: {e}")
            return False

    def extract_prompt(self, input_image_path):
        """Витягує текстовий опис з зображення."""
        if not self.api_key:
            logger.error("Googler -> ПОМИЛКА: API ключ не встановлено.")
            return None

        logger.info(f"Googler -> Витягнення промпту з зображення: {input_image_path}")

        try:
            with open(input_image_path, 'rb') as f:
                image_bytes = f.read()
            
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            ext = input_image_path.lower().split('.')[-1]
            if ext == 'jpg':
                ext = 'jpeg'
            data_uri = f"data:image/{ext};base64,{base64_image}"
            
        except Exception as e:
            logger.error(f"Googler -> ПОМИЛКА: Не вдалося прочитати зображення: {e}")
            return None

        url = f"{self.base_url}/images"
        payload = {
            "provider": "google_fx",
            "operation": "extract_prompt",
            "parameters": {
                "input_image": data_uri
            }
        }

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    extracted_text = data.get("result")
                    logger.info(f"Googler -> УСПІХ: Витягнуто промпт: {extracted_text}")
                    return extracted_text
                else:
                    error = data.get("error", "Невідома помилка")
                    logger.error(f"Googler -> ПОМИЛКА API: {error}")
                    return None
            else:
                logger.error(f"Googler -> ПОМИЛКА API ({response.status_code}): {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Googler -> ПОМИЛКА: Запит не вдався: {e}")
            return None
