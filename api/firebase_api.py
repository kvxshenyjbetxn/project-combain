# api/firebase_api.py

import logging
import pyrebase
import os
import datetime
import threading
import mimetypes
import time

logger = logging.getLogger("TranslationApp")

class FirebaseAPI:
    def __init__(self, config):
        self.config = config  # Зберігаємо конфігурацію
        self.is_initialized = False
        self.auth = None
        self.db = None
        self.storage = None
        self.user = None
        self.user_id = None
        
        try:
            firebase_config = config.get("firebase", {})
            db_url = firebase_config.get("database_url")
            storage_bucket = firebase_config.get("storage_bucket")

            if not db_url or not storage_bucket:
                logger.warning("Firebase -> URL бази даних або ID сховища не вказано. Інтеграція вимкнена.")
                return
            
            # ВИПРАВЛЕННЯ: Автоматично видаляємо префікс "gs://", якщо він є
            if storage_bucket.startswith("gs://"):
                storage_bucket = storage_bucket[5:]

            # Публічна конфігурація Firebase (безпечна для розповсюдження)
            firebase_client_config = {
                "apiKey": firebase_config.get("api_key", ""),
                "authDomain": firebase_config.get("auth_domain", ""),
                "databaseURL": db_url,
                "projectId": firebase_config.get("project_id", ""),
                "storageBucket": storage_bucket,
                "messagingSenderId": firebase_config.get("messaging_sender_id", ""),
                "appId": firebase_config.get("app_id", "")
            }

            # Ініціалізуємо клієнтський Firebase SDK
            firebase = pyrebase.initialize_app(firebase_client_config)
            self.auth = firebase.auth()
            self.db = firebase.database()
            self.storage = firebase.storage()

            # Логіка отримання або створення User ID
            self.user_id = self._get_or_create_user(config)
            
            if not self.user_id:
                logger.error("Firebase -> Не вдалося отримати/створити користувача")
                return
            
            # Створення шляхів з урахуванням user_id
            self.base_path = f"users/{self.user_id}"
            self.logs_ref = f'{self.base_path}/logs'
            self.images_ref = f'{self.base_path}/images'
            self.commands_ref = f'{self.base_path}/commands'
            self.is_initialized = True
            
            # Перевіряємо доступність Firebase Storage
            self._test_storage_connectivity()
            
            logger.info(f"Firebase -> API успішно ініціалізовано для користувача: {self.user_id}")

        except Exception as e:
            logger.error(f"Firebase -> КРИТИЧНА ПОМИЛКА ініціалізації: {e}", exc_info=True)
            self.is_initialized = False

    def _test_storage_connectivity(self):
        """Тестує з'єднання з Firebase Storage."""
        try:
            # Спробуємо отримати список файлів (це не створює файлів)
            test_path = f"{self.user_id}/test/"
            self.storage.child(test_path).get_url(None)
        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "Not Found" in error_msg:
                logger.warning("Firebase Storage -> Bucket може не існувати або бути недоступним")
                logger.warning("Firebase Storage -> Буде використовуватися fallback на локальні файли")
            elif "403" in error_msg:
                logger.warning("Firebase Storage -> Проблеми з правами доступу")
            else:
                logger.warning(f"Firebase Storage -> Тест з'єднання: {error_msg}")
            return False
        return True

    def _get_or_create_user(self, config):
        """Отримує або створює анонімного користувача Firebase."""
        from utils.config_utils import save_config
        
        saved_user_info = config.get("user_settings", {}).get("firebase_user", {})
        
        if saved_user_info and 'refreshToken' in saved_user_info:
            try:
                # Оновлюємо токен, щоб впевнитись, що сесія активна
                refreshed_user = self.auth.refresh(saved_user_info['refreshToken'])
                
                # Логуємо структуру відповіді для діагностики
                logger.info(f"Firebase -> Структура відповіді refresh(): {list(refreshed_user.keys()) if refreshed_user else 'None'}")
                
                # Шукаємо user ID в різних можливих полях
                user_id = None
                if 'localId' in refreshed_user:
                    user_id = refreshed_user['localId']
                elif 'userId' in refreshed_user:
                    user_id = refreshed_user['userId']
                elif 'user_id' in refreshed_user:
                    user_id = refreshed_user['user_id']
                elif saved_user_info.get('localId'):
                    # Якщо в refresh() немає ID, беремо з збереженої сесії
                    user_id = saved_user_info['localId']
                    refreshed_user['localId'] = user_id  # Додаємо для сумісності
                
                if user_id:
                    self.user = refreshed_user
                    # Оновлюємо збережену інформацію
                    config['user_settings']['firebase_user'] = refreshed_user
                    save_config(config)
                    logger.info(f"Firebase -> Успішно відновлено сесію для User ID: {user_id}")
                    return user_id
                else:
                    logger.warning(f"Firebase -> Не знайдено User ID в відповіді refresh()")
                    raise Exception("Не знайдено User ID в відповіді")
                    
            except Exception as e:
                logger.warning(f"Firebase -> Не вдалося відновити сесію, створюємо нову. Помилка: {e}")

        # Якщо збереженої сесії немає або вона недійсна, створюємо нового анонімного користувача
        try:
            new_user = self.auth.sign_in_anonymous()
            self.user = new_user
            
            if 'user_settings' not in config:
                config['user_settings'] = {}
            # Зберігаємо всю інформацію про користувача, включаючи refresh token
            config['user_settings']['firebase_user'] = new_user
            save_config(config)
            
            logger.info(f"Firebase -> Створено нового анонімного користувача. User ID: {self.user['localId']}")
            return self.user['localId']
        except Exception as e:
            logger.error(f"Firebase -> Помилка створення анонімного користувача: {e}")
            return None

    def initialize_firebase_paths(self):
        """Ініціалізує шляхи Firebase після створення користувача."""
        try:
            # Створення шляхів з урахуванням user_id
            self.base_path = f"users/{self.user_id}" if self.user_id else "users/default"
            self.logs_ref = f'{self.base_path}/logs'
            self.images_ref = f'{self.base_path}/images'
            self.commands_ref = f'{self.base_path}/commands'
            self.is_initialized = True
            logger.info(f"Firebase -> API успішно ініціалізовано для користувача: {self.user_id}")
        except Exception as e:
            logger.error(f"Firebase -> КРИТИЧНА ПОМИЛКА ініціалізації: {e}", exc_info=True)
            self.is_initialized = False

    def get_user_token(self):
        """Безпечно отримує idToken користувача з різних можливих полів."""
        if not self.user:
            return None
        return self.user.get('idToken') or self.user.get('id_token') or self.user.get('token')

    def send_log(self, message):
        if not self.is_initialized or not self.user: return
        try:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            token = self.get_user_token()
            if not token:
                logger.error("Firebase -> Не знайдено токен для аутентифікації")
                return
            self.db.child(self.logs_ref).push({'timestamp': timestamp, 'message': message}, token)
            logger.debug(f"Firebase -> Лог успішно надіслано: {message}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка надсилання логу: {e}")

    def send_log_in_thread(self, message):
        if not self.is_initialized: return
        thread = threading.Thread(target=self.send_log, args=(message,), daemon=True)
        thread.start()

    def clear_logs(self):
        if not self.is_initialized or not self.user: return
        try:
            logger.info("Firebase -> Очищення логів з бази даних...")
            self.db.child(self.logs_ref).remove(self.get_user_token())
            logger.info("Firebase -> Логи успішно очищено.")
        except Exception as e:
            logger.error(f"Firebase -> Не вдалося очистити логи: {e}")

    def upload_image_and_get_url(self, local_path, remote_path):
        # Перевіряємо, чи увімкнено завантаження в Storage
        firebase_config = getattr(self, 'config', {}).get('firebase', {})
        storage_enabled = firebase_config.get('enable_storage_upload', True)
        
        if not storage_enabled:
            logger.debug("Firebase Storage -> Завантаження вимкнено в конфігурації. Використовуємо локальний шлях.")
            return f"file://{local_path.replace(os.sep, '/')}"
            
        if not self.is_initialized or not self.user:
            logger.warning("Firebase Storage не ініціалізовано. Використовуємо локальний шлях.")
            return f"file://{local_path.replace(os.sep, '/')}"
            
        try:
            # Перевіряємо, чи існує файл локально
            if not os.path.exists(local_path):
                logger.error(f"Firebase -> Локальний файл не існує: {local_path}")
                return None
                
            # Додаємо user_id до шляху Storage
            user_remote_path = f"{self.user_id}/{remote_path}"
            logger.debug(f"Firebase -> Спроба завантажити {local_path} → {user_remote_path}")
            
            # Перевіряємо розмір файлу
            file_size = os.path.getsize(local_path)
            if file_size > 10 * 1024 * 1024:  # 10MB
                logger.warning(f"Firebase -> Файл занадто великий ({file_size} bytes). Використовуємо локальний шлях.")
                return f"file://{local_path.replace(os.sep, '/')}"
            
            # Спробуємо завантажити файл з timeout
            logger.debug(f"Firebase -> Початок завантаження файлу {file_size} bytes")
            blob = self.storage.child(user_remote_path).put(local_path, self.get_user_token())
            
            # Отримуємо URL
            download_url = self.storage.child(user_remote_path).get_url(blob['downloadTokens'])
            logger.info(f"Firebase -> ✅ Успішно завантажено: {os.path.basename(local_path)}")
            return download_url
            
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Firebase -> Помилка завантаження '{os.path.basename(local_path)}': {error_msg}")
            
            # Детальний аналіз помилки
            if "404" in error_msg:
                logger.warning("Firebase -> 404 помилка: Storage bucket може не існувати або бути недоступним")
            elif "403" in error_msg:
                logger.warning("Firebase -> 403 помилка: Проблеми з правами доступу або токеном")
            elif "401" in error_msg:
                logger.warning("Firebase -> 401 помилка: Проблеми з аутентифікацією")
            
            # Fallback на локальний файл
            logger.info(f"Firebase -> 🔄 Fallback: використовуємо локальний шлях для {os.path.basename(local_path)}")
            return f"file://{local_path.replace(os.sep, '/')}"

    def add_image_to_db(self, image_id, image_url, task_name, lang_code, prompt):
        if not self.is_initialized or not self.user: return
        try:
            # Додаємо кеш-бастер до URL для запобігання кешуванню
            cache_buster = f"?v={int(time.time() * 1000)}"
            final_url = image_url + cache_buster
            
            self.db.child(self.images_ref).child(image_id).set({
                'id': image_id, 
                'url': final_url,
                'taskName': task_name,
                'langCode': lang_code,
                'prompt': prompt,
                'timestamp': int(time.time() * 1000) # Час у мілісекундах для сортування
            }, self.get_user_token())
            logger.info(f"Firebase -> Додано посилання на зображення в базу даних: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка додавання зображення в базу даних: {e}")
            
    def update_image_in_db(self, image_id, image_url):
        if not self.is_initialized or not self.user: return
        try:
            # Створюємо унікальний "кеш-бастер" на основі часу
            cache_buster = f"?v={int(time.time() * 1000)}"
            update_data = {
                'url': image_url + cache_buster, # Додаємо його до URL
                # НЕ оновлюємо timestamp щоб зберегти оригінальну позицію
            }
            self.db.child(self.images_ref).child(image_id).update(update_data, self.get_user_token())
            logger.info(f"Firebase -> Оновлено посилання на зображення в базі даних: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка оновлення зображення в базі даних: {e}")
            
    def clear_images(self):
        """Видаляє всі зображення з Storage та Realtime Database для поточного користувача."""
        if not self.is_initialized or not self.user:
            return
        try:
            # Видалення з Realtime Database
            logger.info(f"Firebase -> Очищення посилань на зображення з бази даних для користувача {self.user_id}...")
            self.db.child(self.images_ref).remove(self.get_user_token())
            logger.info("Firebase -> Посилання на зображення видалено.")

            # Видалення файлів зі Storage
            logger.info(f"Firebase -> Очищення файлів зображень зі Storage для користувача {self.user_id}...")
            # Отримуємо список файлів для видалення
            storage_path = f"{self.user_id}/gallery_images/"
            try:
                files = self.storage.list_files()
                for file_path in files:
                    if file_path.startswith(storage_path):
                        self.storage.delete(file_path, self.get_user_token())
                logger.info("Firebase -> Файли зображень зі Storage видалено.")
            except Exception as storage_error:
                logger.warning(f"Firebase -> Помилка очищення Storage: {storage_error}")

        except Exception as e:
            logger.error(f"Firebase -> Помилка під час очищення зображень: {e}")

    def delete_image_from_storage(self, image_id):
        if not self.is_initialized or not self.user: return False
        try:
            storage_path = f"{self.user_id}/gallery_images/{image_id}.jpg"
            self.storage.delete(storage_path, self.get_user_token())
            logger.info(f"Firebase -> Зображення видалено зі Storage: {image_id}")
            return True
        except Exception as e:
            logger.error(f"Firebase -> Помилка видалення зображення зі Storage: {e}")
            return False

    def delete_image_from_db(self, image_id):
        if not self.is_initialized or not self.user: return
        try:
            self.db.child(self.images_ref).child(image_id).remove(self.get_user_token())
            logger.info(f"Firebase -> Запис про зображення видалено з БД: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка видалення запису з БД: {e}")
    
    def listen_for_commands(self, callback):
        if not self.is_initialized or not self.user: return
        logger.info("Firebase -> Запуск прослуховування команд...")
        self.db.child(self.commands_ref).stream(callback, token=self.get_user_token())

    def clear_commands(self):
        if not self.is_initialized or not self.user: return
        try:
            self.db.child(self.commands_ref).remove(self.get_user_token())
            logger.info("Firebase -> Команди очищено.")
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення команд: {e}")

    def send_continue_montage_command(self):
        """Відправляє команду продовження монтажу."""
        if not self.is_initialized or not self.user: return
        try:
            self.db.child(self.commands_ref).push({
                'command': 'continue_montage',
                'timestamp': int(time.time() * 1000)
            }, self.get_user_token())
            logger.info("Firebase -> Відправлено команду продовження монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка відправки команди продовження монтажу: {e}")

    def send_montage_ready_status(self):
        """Відправляє статус готовності до монтажу."""
        if not self.is_initialized or not self.user: return
        try:
            # Додаємо статус в окремий ref для відстеження готовності
            self.db.child(f'users/{self.user_id}/status').set({
                'montage_ready': True,
                'timestamp': int(time.time() * 1000)
            }, self.get_user_token())
            logger.info("Firebase -> Відправлено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка відправки статусу готовності: {e}")

    def clear_montage_ready_status(self):
        """Очищає статус готовності до монтажу."""
        if not self.is_initialized or not self.user: return
        try:
            self.db.child(f'users/{self.user_id}/status').set({
                'montage_ready': False,
                'timestamp': int(time.time() * 1000)
            }, self.get_user_token())
            logger.info("Firebase -> Очищено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення статусу готовності: {e}")

    def upload_and_add_image_in_thread(self, local_path, task_key, image_index, task_name, prompt, callback=None):
        if not self.is_initialized: return None
        
        def worker():
            task_index, lang_code = task_key
            # Додаємо timestamp для унікальності імені файлу
            timestamp = int(time.time() * 1000)
            image_id = f"task{task_index}_{lang_code}_img{image_index}_{timestamp}"
            remote_path = f"gallery_images/{image_id}.jpg"
            
            image_url = self.upload_image_and_get_url(local_path, remote_path)
            if image_url:
                self.add_image_to_db(image_id, image_url, task_name, lang_code, prompt)
                # Викликаємо callback з image_id та шляхом
                if callback:
                    callback(image_id, local_path)
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        
        # Повертаємо попередньо сгенерований image_id для синхронного використання
        task_index, lang_code = task_key
        timestamp = int(time.time() * 1000)
        return f"task{task_index}_{lang_code}_img{image_index}_{timestamp}"
    
    def delete_image_from_db(self, image_id):
        """Видаляє зображення з Realtime Database."""
        if not self.is_initialized: return
        try:
            self.images_ref.child(image_id).delete()
            logger.info(f"Firebase -> Видалено зображення з бази даних: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка видалення зображення з бази даних: {e}")
    
    def delete_image_from_storage(self, image_id):
        """Видаляє зображення з Firebase Storage."""
        if not self.is_initialized or not self.bucket: return
        try:
            # Видаляємо файл з Storage з user_id шляхом
            blob = self.bucket.blob(f"{self.user_id}/gallery_images/{image_id}.jpg")
            if blob.exists():
                blob.delete()
                logger.info(f"Firebase -> Видалено зображення зі Storage: {image_id}")
            else:
                logger.warning(f"Firebase -> Зображення не знайдено в Storage: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка видалення зображення зі Storage: {e}")

    def send_montage_ready_status(self):
        """Відправляє статус готовності до монтажу."""
        if not self.is_initialized or not self.user: return
        try:
            status_ref = f'users/{self.user_id}/status'
            self.db.child(status_ref).child('montage_ready').set(True, self.get_user_token())
            logger.info("Firebase -> Відправлено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка відправки статусу готовності: {e}")

    def clear_montage_ready_status(self):
        """Очищає статус готовності до монтажу."""
        if not self.is_initialized or not self.user: return
        try:
            status_ref = f'users/{self.user_id}/status'
            self.db.child(status_ref).child('montage_ready').set(False, self.get_user_token())
            logger.info("Firebase -> Очищено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення статусу готовності: {e}")

    def update_user_id(self, new_user_id):
        """Оновлює User ID та відповідні посилання."""
        if not self.is_initialized: return
        self.user_id = new_user_id if new_user_id else "default"
        self.base_path = f"users/{self.user_id}"
        self.logs_ref = f'{self.base_path}/logs'
        self.images_ref = f'{self.base_path}/images'
        self.commands_ref = f'{self.base_path}/commands'
        logger.info(f"Firebase -> User ID оновлено на: {self.user_id}")

    def clear_user_logs(self):
        """Очищення логів тільки для поточного користувача."""
        if not self.is_initialized or not self.user: return
        try:
            logger.info(f"Firebase -> Очищення логів для користувача {self.user_id}...")
            self.db.child(self.logs_ref).remove(self.get_user_token())
            logger.info(f"Firebase -> Логи для користувача {self.user_id} успішно очищено.")
            return True
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення логів для користувача {self.user_id}: {e}")
            return False

    def clear_user_images(self):
        """Очищення галереї тільки для поточного користувача."""
        if not self.is_initialized or not self.user: return
        try:
            # Очищення Database записів
            logger.info(f"Firebase -> Очищення зображень для користувача {self.user_id}...")
            self.db.child(self.images_ref).remove(self.get_user_token())
            
            # Очищення Storage файлів
            logger.info(f"Firebase -> Очищення файлів Storage для користувача {self.user_id}...")
            try:
                storage_path = f"{self.user_id}/gallery_images/"
                files = self.storage.list_files()
                for file_path in files:
                    if file_path.startswith(storage_path):
                        self.storage.delete(file_path, self.get_user_token())
                logger.info(f"Firebase -> Файли Storage для користувача {self.user_id} видалено.")
            except Exception as storage_error:
                logger.warning(f"Firebase -> Помилка очищення Storage: {storage_error}")
            
            logger.info(f"Firebase -> Зображення для користувача {self.user_id} успішно очищено.")
            return True
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення зображень для користувача {self.user_id}: {e}")
            return False

    def get_user_stats(self):
        """Отримання статистики тільки для поточного користувача."""
        if not self.is_initialized or not self.user: return {"logs": 0, "images": 0}
        try:
            token = self.get_user_token()
            if not token:
                logger.error("Firebase -> Не знайдено токен для отримання статистики")
                return {"logs": 0, "images": 0}
            
            logs_snapshot = self.db.child(self.logs_ref).get(token=token)
            images_snapshot = self.db.child(self.images_ref).get(token=token)
            
            logs_count = len(logs_snapshot.val() or {})
            images_count = len(images_snapshot.val() or {})
            
            return {
                "user_id": self.user_id,
                "logs": logs_count,
                "images": images_count
            }
        except Exception as e:
            logger.error(f"Firebase -> Помилка отримання статистики для користувача {self.user_id}: {e}")
            return {"logs": 0, "images": 0}

    def get_current_user_id(self):
        """Повертає поточний User ID."""
        return self.user_id

    def refresh_user_token(self):
        """Оновлює токен користувача."""
        if not self.is_initialized or not self.user:
            return False
        try:
            self.user = self.auth.refresh(self.user['refreshToken'])
            logger.debug("Firebase -> Токен користувача оновлено")
            return True
        except Exception as e:
            logger.error(f"Firebase -> Помилка оновлення токена: {e}")
            return False
