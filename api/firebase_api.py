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
            
            self.logs_ref = db.reference('logs')
            self.images_ref = db.reference('images')
            self.commands_ref = db.reference('commands')
            self.bucket = storage.bucket()
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
            blob = self.bucket.blob(remote_path)
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
        """Видаляє всі зображення з Storage та Realtime Database."""
        if not self.is_initialized:
            return
        try:
            # Видалення з Realtime Database
            logger.info("Firebase -> Очищення посилань на зображення з бази даних...")
            self.images_ref.delete()
            logger.info("Firebase -> Посилання на зображення видалено.")

            # Видалення файлів зі Storage
            if self.bucket:
                logger.info("Firebase -> Очищення файлів зображень зі Storage...")
                blobs = self.bucket.list_blobs(prefix="gallery_images/")
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
            db.reference('status').set({
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
            db.reference('status').set({
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
            # Видаляємо файл з Storage
            blob = self.bucket.blob(f"gallery_images/{image_id}.jpg")
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
            status_ref = db.reference('status')
            status_ref.child('montage_ready').set(True)
            logger.info("Firebase -> Відправлено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка відправки статусу готовності: {e}")

    def clear_montage_ready_status(self):
        """Очищає статус готовності до монтажу."""
        if not self.is_initialized: return
        try:
            status_ref = db.reference('status')
            status_ref.child('montage_ready').set(False)
            logger.info("Firebase -> Очищено статус готовності до монтажу")
        except Exception as e:
            logger.error(f"Firebase -> Помилка очищення статусу готовності: {e}")