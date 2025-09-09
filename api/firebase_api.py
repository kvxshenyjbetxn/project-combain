# api/firebase_api.py

import logging
import firebase_admin
from firebase_admin import credentials, db, storage
import os
import datetime
import threading
import mimetypes
import time

logger = logging.getLogger("TranslationApp")

class FirebaseAPI:
    def __init__(self, config):
        self.is_initialized = False
        self.bucket = None
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

            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cred_path = os.path.join(base_path, 'firebase-credentials.json')

            if not os.path.exists(cred_path):
                logger.warning(f"Firebase -> Файл '{cred_path}' не знайдено. Інтеграція вимкнена.")
                return

            cred = credentials.Certificate(cred_path)
            
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {
                    'databaseURL': db_url,
                    'storageBucket': storage_bucket
                })
            
            self.bucket = storage.bucket()
            
            # Автоматична генерація або отримання збереженого User ID
            self.user_id = self._get_or_generate_user_id(config)
            
            # Створення шляхів з урахуванням user_id
            self.base_path = f"users/{self.user_id}" if self.user_id else "users/default"
            self.logs_ref = db.reference(f'{self.base_path}/logs')
            self.images_ref = db.reference(f'{self.base_path}/images')
            self.commands_ref = db.reference(f'{self.base_path}/commands')
            self.is_initialized = True
            logger.info("Firebase -> API успішно ініціалізовано.")

        except Exception as e:
            logger.error(f"Firebase -> КРИТИЧНА ПОМИЛКА ініціалізації: {e}", exc_info=True)
            self.is_initialized = False

    def send_log(self, message):
        if not self.is_initialized: return
        try:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            self.logs_ref.push().set({'timestamp': timestamp, 'message': message})
            logger.debug(f"Firebase -> Лог успішно надіслано: {message}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка надсилання логу: {e}")

    def send_log_in_thread(self, message):
        if not self.is_initialized: return
        thread = threading.Thread(target=self.send_log, args=(message,), daemon=True)
        thread.start()

    def clear_logs(self):
        if not self.is_initialized: return
        try:
            logger.info("Firebase -> Очищення логів з бази даних...")
            self.logs_ref.delete()
            logger.info("Firebase -> Логи успішно очищено.")
        except Exception as e:
            logger.error(f"Firebase -> Не вдалося очистити логи: {e}")

    def upload_image_and_get_url(self, local_path, remote_path):
        if not self.is_initialized or not self.bucket:
            logger.error("Firebase Storage не ініціалізовано.")
            return None
        try:
            # Додаємо user_id до шляху Storage
            user_remote_path = f"{self.user_id}/{remote_path}"
            blob = self.bucket.blob(user_remote_path)
            content_type, _ = mimetypes.guess_type(local_path)
            blob.upload_from_filename(local_path, content_type=content_type)
            blob.make_public()
            return blob.public_url
        except Exception as e:
            logger.error(f"Firebase -> Помилка завантаження зображення '{local_path}': {e}", exc_info=True)
            return None

    def add_image_to_db(self, image_id, image_url, task_name, lang_code, prompt):
        if not self.is_initialized: return
        try:
            # Додаємо кеш-бастер до URL для запобігання кешуванню
            cache_buster = f"?v={int(time.time() * 1000)}"
            final_url = image_url + cache_buster
            
            self.images_ref.child(image_id).set({
                'id': image_id, 
                'url': final_url,
                'taskName': task_name,
                'langCode': lang_code,
                'prompt': prompt,
                'timestamp': int(time.time() * 1000) # Час у мілісекундах для сортування
            })
            logger.info(f"Firebase -> Додано посилання на зображення в базу даних: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка додавання зображення в базу даних: {e}")
            
    def update_image_in_db(self, image_id, image_url):
        if not self.is_initialized: return
        try:
            # Створюємо унікальний "кеш-бастер" на основі часу
            cache_buster = f"?v={int(time.time() * 1000)}"
            update_data = {
                'url': image_url + cache_buster, # Додаємо його до URL
                # НЕ оновлюємо timestamp щоб зберегти оригінальну позицію
            }
            self.images_ref.child(image_id).update(update_data)
            logger.info(f"Firebase -> Оновлено посилання на зображення в базі даних: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка оновлення зображення в базі даних: {e}")
            
    def clear_images(self):
        """Видаляє всі зображення з Storage та Realtime Database для поточного користувача."""
        if not self.is_initialized:
            return
        try:
            # Видалення з Realtime Database
            logger.info(f"Firebase -> Очищення посилань на зображення з бази даних для користувача {self.user_id}...")
            self.images_ref.delete()
            logger.info("Firebase -> Посилання на зображення видалено.")

            # Видалення файлів зі Storage
            if self.bucket:
                logger.info(f"Firebase -> Очищення файлів зображень зі Storage для користувача {self.user_id}...")
                blobs = self.bucket.list_blobs(prefix=f"{self.user_id}/gallery_images/")
                for blob in blobs:
                    blob.delete()
                logger.info("Firebase -> Файли зображень зі Storage видалено.")

        except Exception as e:
            logger.error(f"Firebase -> Помилка під час очищення зображень: {e}")

    def delete_image_from_storage(self, image_id):
        if not self.bucket: return False
        try:
            blob = self.bucket.blob(f"gallery_images/{image_id}.jpg")
            if blob.exists():
                blob.delete()
                logger.info(f"Firebase -> Зображення видалено зі Storage: {image_id}")
            return True
        except Exception as e:
            logger.error(f"Firebase -> Помилка видалення зображення зі Storage: {e}")
            return False

    def delete_image_from_db(self, image_id):
        if not self.is_initialized: return
        try:
            self.images_ref.child(image_id).delete()
            logger.info(f"Firebase -> Запис про зображення видалено з БД: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка видалення запису з БД: {e}")
    
    def listen_for_commands(self, callback):
        if not self.is_initialized: return
        logger.info("Firebase -> Запуск прослуховування команд...")
        self.commands_ref.listen(callback)

    def clear_commands(self):
        if not self.is_initialized: return
        try:
            self.commands_ref.delete()
            logger.info("Firebase -> Команди очищено.")
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення команд: {e}")

    def send_continue_montage_command(self):
        """Відправляє команду продовження монтажу."""
        if not self.is_initialized: return
        try:
            self.commands_ref.push().set({
                'command': 'continue_montage',
                'timestamp': int(time.time() * 1000)
            })
            logger.info("Firebase -> Відправлено команду продовження монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка відправки команди продовження монтажу: {e}")

    def send_montage_ready_status(self):
        """Відправляє статус готовності до монтажу."""
        if not self.is_initialized: return
        try:
            # Додаємо статус в окремий ref для відстеження готовності
            db.reference(f'users/{self.user_id}/status').set({
                'montage_ready': True,
                'timestamp': int(time.time() * 1000)
            })
            logger.info("Firebase -> Відправлено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка відправки статусу готовності: {e}")

    def clear_montage_ready_status(self):
        """Очищає статус готовності до монтажу."""
        if not self.is_initialized: return
        try:
            db.reference(f'users/{self.user_id}/status').set({
                'montage_ready': False,
                'timestamp': int(time.time() * 1000)
            })
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
        if not self.is_initialized: return
        try:
            status_ref = db.reference(f'users/{self.user_id}/status')
            status_ref.child('montage_ready').set(True)
            logger.info("Firebase -> Відправлено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка відправки статусу готовності: {e}")

    def clear_montage_ready_status(self):
        """Очищає статус готовності до монтажу."""
        if not self.is_initialized: return
        try:
            status_ref = db.reference(f'users/{self.user_id}/status')
            status_ref.child('montage_ready').set(False)
            logger.info("Firebase -> Очищено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення статусу готовності: {e}")

    def update_user_id(self, new_user_id):
        """Оновлює User ID та відповідні посилання."""
        if not self.is_initialized: return
        self.user_id = new_user_id if new_user_id else "default"
        self.base_path = f"users/{self.user_id}"
        self.logs_ref = db.reference(f'{self.base_path}/logs')
        self.images_ref = db.reference(f'{self.base_path}/images')
        self.commands_ref = db.reference(f'{self.base_path}/commands')
        logger.info(f"Firebase -> User ID оновлено на: {self.user_id}")

    def clear_user_logs(self):
        """Очищення логів тільки для поточного користувача."""
        if not self.is_initialized: return
        try:
            logger.info(f"Firebase -> Очищення логів для користувача {self.user_id}...")
            self.logs_ref.delete()
            logger.info(f"Firebase -> Логи для користувача {self.user_id} успішно очищено.")
            return True
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення логів для користувача {self.user_id}: {e}")
            return False

    def clear_user_images(self):
        """Очищення галереї тільки для поточного користувача."""
        if not self.is_initialized: return
        try:
            # Очищення Database записів
            logger.info(f"Firebase -> Очищення зображень для користувача {self.user_id}...")
            self.images_ref.delete()
            
            # Очищення Storage файлів
            if self.bucket:
                logger.info(f"Firebase -> Очищення файлів Storage для користувача {self.user_id}...")
                blobs = self.bucket.list_blobs(prefix=f"{self.user_id}/gallery_images/")
                for blob in blobs:
                    blob.delete()
                logger.info(f"Firebase -> Файли Storage для користувача {self.user_id} видалено.")
            
            logger.info(f"Firebase -> Зображення для користувача {self.user_id} успішно очищено.")
            return True
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення зображень для користувача {self.user_id}: {e}")
            return False

    def get_user_stats(self):
        """Отримання статистики тільки для поточного користувача."""
        if not self.is_initialized: return {"logs": 0, "images": 0}
        try:
            logs_snapshot = self.logs_ref.get()
            images_snapshot = self.images_ref.get()
            
            logs_count = len(logs_snapshot) if logs_snapshot else 0
            images_count = len(images_snapshot) if images_snapshot else 0
            
            return {
                "user_id": self.user_id,
                "logs": logs_count,
                "images": images_count
            }
        except Exception as e:
            logger.error(f"Firebase -> Помилка отримання статистики для користувача {self.user_id}: {e}")
            return {"logs": 0, "images": 0}

    def _get_or_generate_user_id(self, config):
        """Отримує збережений User ID або генерує новий автоматично."""
        from utils.config_utils import save_config
        
        # Перевіряємо чи є збережений User ID
        saved_user_id = config.get("user_settings", {}).get("user_id", "")
        if saved_user_id:
            logger.info(f"Firebase -> Використовується збережений User ID: {saved_user_id}")
            return saved_user_id
        
        # Генеруємо новий User ID
        try:
            users_ref = db.reference('users')
            users_snapshot = users_ref.get()
            
            # Знаходимо найбільший існуючий числовий ID
            max_id = 0
            if users_snapshot:
                for user_id in users_snapshot.keys():
                    try:
                        numeric_id = int(user_id)
                        max_id = max(max_id, numeric_id)
                    except ValueError:
                        # Ігноруємо не-числові ID
                        continue
            
            # Генеруємо новий ID
            new_user_id = str(max_id + 1)
            
            # Зберігаємо в конфігурації
            if 'user_settings' not in config:
                config['user_settings'] = {}
            config['user_settings']['user_id'] = new_user_id
            save_config(config)
            
            logger.info(f"Firebase -> Згенеровано новий User ID: {new_user_id}")
            return new_user_id
            
        except Exception as e:
            logger.error(f"Firebase -> Помилка генерації User ID: {e}")
            # Fallback до "default"
            return "default"

    def get_current_user_id(self):
        """Повертає поточний User ID."""
        return self.user_id