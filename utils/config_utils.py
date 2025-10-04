# utils/config_utils.py

import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
import shutil

# Імпортуємо потрібні константи
from constants.app_settings import DETAILED_LOG_FILE, CONFIG_FILE, TRANSLATIONS_FILE
from constants.default_config import DEFAULT_CONFIG

def setup_logging():
    logger = logging.getLogger("TranslationApp")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        # --- Консольний логер (без змін) ---
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter('[%(levelname)s] %(message)s')
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

        # --- Файловий логер (оновлено) ---
        # Використовуємо звичайний FileHandler замість RotatingFileHandler,
        # оскільки тепер створюємо новий файл при кожному запуску.
        detailed_file_handler = logging.FileHandler(DETAILED_LOG_FILE, mode='w', encoding='utf-8')
        detailed_file_handler.setLevel(logging.DEBUG)
        detailed_format = logging.Formatter('%(asctime)s - [%(levelname)s] - (%(funcName)s): %(message)s')
        detailed_file_handler.setFormatter(detailed_format)
        logger.addHandler(detailed_file_handler)
    #logger.info("Систему логування успішно налаштовано.")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logging.getLogger("TranslationApp").info("Конфігурація завантажена успішно.")
            def update(d, u):
                for k, v in u.items():
                    if isinstance(v, dict):
                        d[k] = update(d.get(k, {}), v) if k in d and isinstance(d.get(k), dict) else v
                    elif k not in d:
                        d[k] = v
                return d
            config = update(config, DEFAULT_CONFIG.copy())
            return config
        except Exception as e:
            logging.getLogger("TranslationApp").error(f"Error loading config: {e}")
            return DEFAULT_CONFIG.copy()
    else:
        logging.getLogger("TranslationApp").info("Config file not found. Using default configuration.")
        return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        logging.getLogger("TranslationApp").info("Конфігурація завантажена успішно.")
    except Exception as e:
        logging.getLogger("TranslationApp").error(f"Error saving config: {e}")
        # messagebox.showerror("Помилка", f"Не вдалося зберегти конфігурацію: {e}") # Це краще робити в GUI

def load_translations():
    try:
        with open(TRANSLATIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.getLogger("TranslationApp").error(f"Could not load translations file: {e}")
        return {}

def setup_ffmpeg_path(config):
    ffmpeg_path_from_config = config.get("montage", {}).get("ffmpeg_path", "")
    if ffmpeg_path_from_config and os.path.exists(ffmpeg_path_from_config):
        ffmpeg_dir = os.path.dirname(ffmpeg_path_from_config)
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ["PATH"]
        logging.getLogger("TranslationApp").info(f"Using FFmpeg from config: {ffmpeg_path_from_config}")
        return

    script_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    ffmpeg_exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    
    if shutil.which(ffmpeg_exe_name):
        logging.getLogger("TranslationApp").info(f"Знайдено системний ffmpeg у PATH.")
    else:
        logging.getLogger("TranslationApp").warning(f"System-wide '{ffmpeg_exe_name}' not found. Specify the path in Settings.")