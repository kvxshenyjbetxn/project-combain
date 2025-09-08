# api/firebase_api.py

import logging
import firebase_admin
from firebase_admin import credentials, db
import os
import datetime
import threading

logger = logging.getLogger("TranslationApp")

class FirebaseAPI:
    def __init__(self, config):
        self.is_initialized = False
        try:
            db_url = config.get("firebase", {}).get("database_url")
            if not db_url:
                logger.warning("Firebase -> URL бази даних не вказано. Інтеграція вимкнена.")
                return

            # Шлях до файлу credentials.json, який має лежати поруч з combain.py
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cred_path = os.path.join(base_path, 'firebase-credentials.json')

            if not os.path.exists(cred_path):
                logger.warning(f"Firebase -> Файл '{cred_path}' не знайдено. Інтеграція вимкнена.")
                return

            cred = credentials.Certificate(cred_path)
            
            # Перевіряємо, чи програма вже ініціалізована
            if not firebase_admin._apps:
                firebase_admin.initialize_app(cred, {
                    'databaseURL': db_url
                })
            
            self.db_ref = db.reference('logs')
            self.is_initialized = True
            logger.info("Firebase -> API успішно ініціалізовано.")

        except Exception as e:
            logger.error(f"Firebase -> КРИТИЧНА ПОМИЛКА ініціалізації: {e}", exc_info=True)
            self.is_initialized = False

    def send_log(self, message):
        if not self.is_initialized:
            return

        try:
            # Створюємо новий запис з унікальним ключем на основі часу
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
            self.db_ref.push().set({
                'timestamp': timestamp,
                'message': message
            })
            logger.debug(f"Firebase -> Лог успішно надіслано: {message}")
        except Exception as e:
            logger.error(f"Firebase -> Помилка надсилання логу: {e}")
    
    def send_log_in_thread(self, message):
        """Відправляє лог у окремому потоці, щоб не блокувати GUI."""
        if not self.is_initialized:
            return
        thread = threading.Thread(target=self.send_log, args=(message,), daemon=True)
        thread.start()

    def clear_logs(self):
        """Видаляє всі записи з вузла /logs у базі даних."""
        if not self.is_initialized:
            logger.warning("Firebase -> Неможливо очистити логи, API не ініціалізовано.")
            return
        try:
            logger.info("Firebase -> Очищення логів з бази даних...")
            self.db_ref.delete()
            logger.info("Firebase -> Логи успішно очищено.")
        except Exception as e:
            logger.error(f"Firebase -> Не вдалося очистити логи: {e}")