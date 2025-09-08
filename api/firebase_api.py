# api/firebase_api.py

import logging
import firebase_admin
from firebase_admin import credentials, db, storage
import os
import datetime
import threading
import mimetypes

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

    def add_image_to_db(self, image_id, image_url):
        if not self.is_initialized: return
        try:
            self.images_ref.child(image_id).set({'id': image_id, 'url': image_url})
            logger.info(f"Firebase -> Додано посилання на зображення в базу даних: {image_id}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка додавання зображення в базу даних: {e}")
            
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

    def upload_and_add_image_in_thread(self, local_path, task_key, image_index):
        if not self.is_initialized: return
        
        def worker():
            image_id = f"task{task_key[0]}_{task_key[1]}_img{image_index}"
            remote_path = f"gallery_images/{image_id}.jpg"
            image_url = self.upload_image_and_get_url(local_path, remote_path)
            if image_url:
                self.add_image_to_db(image_id, image_url)
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()