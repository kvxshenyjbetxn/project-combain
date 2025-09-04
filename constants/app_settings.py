# constants/app_settings.py

import os
import sys
import datetime

# Визначаємо базовий шлях для файлів програми
if getattr(sys, 'frozen', False):
    APP_BASE_PATH = os.path.dirname(sys.executable)
else:
    # __file__ тут вказує на app_settings.py, нам треба вийти на один рівень вище
    APP_BASE_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Нова логіка для папки логів ---
LOGS_DIR = os.path.join(APP_BASE_PATH, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
current_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
DETAILED_LOG_FILE = os.path.join(LOGS_DIR, f"log_{current_time}.txt")

# --- Конфігурація ---
CONFIG_FILE = os.path.join(APP_BASE_PATH, "config.json")
TRANSLATIONS_FILE = os.path.join(APP_BASE_PATH, "translations.json")
SPEECHIFY_CHAR_LIMIT = 19000 # Ліміт символів для Speechify, трохи менше 20000