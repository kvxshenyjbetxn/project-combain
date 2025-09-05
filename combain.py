import tkinter as tk
from tkinter import ttk as classic_ttk, scrolledtext, messagebox, filedialog, simpledialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import json
import os
import requests
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import re
import sys
import random
import datetime
import contextlib
import subprocess
import ctypes
import concurrent.futures
import shutil
import numpy as np
import queue
import math

# --- Нові імпорти для галереї ---
from PIL import Image, ImageTk

# --- Нові залежності, потрібні для монтажу та рерайту ---
import whisper
import ffmpeg

#імпорти всіх api
from api.elevenlabs_api import ElevenLabsAPI
from api.montage_api import MontageAPI
from api.openrouter_api import OpenRouterAPI
from api.pollinations_api import PollinationsAPI
from api.recraft_api import RecraftAPI
from api.telegram_api import TelegramAPI
from api.voicemaker_api import VoiceMakerAPI
from api.speechify_api import SpeechifyAPI # <-- НОВИЙ ІМПОРТ

# Імпорти GUI
from gui.task_tab import create_task_tab
from gui.rewrite_tab import create_rewrite_tab
from gui.log_tab import create_log_tab
from gui.settings_tab import create_settings_tab
from gui.gui_utils import add_text_widget_bindings

#константи
from constants.app_settings import (
    APP_BASE_PATH,
    CONFIG_FILE,
    TRANSLATIONS_FILE,
    DETAILED_LOG_FILE,
    SPEECHIFY_CHAR_LIMIT # <-- НОВИЙ ІМПОРТ
)

from constants.default_config import DEFAULT_CONFIG
from constants.voicemaker_voices import VOICEMAKER_VOICES
from constants.recraft_substyles import RECRAFT_SUBSTYLES
from constants.speechify_voices import LANG_VOICE_MAP, SPEECHIFY_EMOTIONS # <-- НОВЕ

from utils import (
    setup_logging,
    load_config,
    save_config,
    load_translations,
    sanitize_filename,
    setup_ffmpeg_path,
    chunk_text,
    chunk_text_voicemaker,
    chunk_text_speechify, # <-- НОВИЙ ІМПОРТ
    concatenate_audio_files,
    suppress_stdout_stderr
)

# --- Налаштування логування ---
logger = logging.getLogger("TranslationApp")

# --- Кастомний діалог для вводу ---
class CustomAskStringDialog(tk.Toplevel):
    def __init__(self, parent, title, prompt, app_instance, initial_value=""): # Додано initial_value
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.app = app_instance 
        self.result = None
        body = ttk.Frame(self)
        self.initial_focus = self.body(body, prompt, initial_value) # Передаємо initial_value
        body.pack(padx=10, pady=10)
        self.buttonbox()
        self.grab_set()
        if not self.initial_focus:
            self.initial_focus = self
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        self.initial_focus.focus_set()
        self.wait_window(self)

    def body(self, master, prompt, initial_value=""): # Додано initial_value
        ttk.Label(master, text=prompt).pack(pady=(0, 5))
        self.entry = ttk.Entry(master, width=50)
        self.entry.pack(pady=(0, 10))
        self.entry.insert(0, initial_value) # Вставляємо текст тут
        add_text_widget_bindings(self.app, self.entry)
        return self.entry

    def buttonbox(self):
        box = ttk.Frame(self)
        ok_button = ttk.Button(box, text=self.app._t('ok_button'), width=10, command=self.ok, bootstyle="success")
        ok_button.pack(side=tk.LEFT, padx=5, pady=5)
        cancel_button = ttk.Button(box, text=self.app._t('cancel_button'), width=10, command=self.cancel, bootstyle="secondary")
        cancel_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def ok(self, event=None):
        # ВИПРАВЛЕНО: Спочатку отримуємо результат, потім закриваємо
        if self.entry:
            self.result = self.entry.get()
        self.withdraw() # Ховаємо вікно
        self.update_idletasks()
        self.destroy()

    def cancel(self, event=None):
        self.result = None # Переконуємось, що результат порожній
        self.destroy()

class AskTemplateDialog(tk.Toplevel):
    def __init__(self, parent, title, templates, app_instance):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.app = app_instance
        self.result = None
        
        body = ttk.Frame(self)
        self.initial_focus = self.body(body, templates)
        body.pack(padx=10, pady=10)
        
        self.buttonbox()
        self.grab_set()
        
        if not self.initial_focus:
            self.initial_focus = self
        
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        self.initial_focus.focus_set()
        self.wait_window(self)

    def body(self, master, templates):
        ttk.Label(master, text=self.app._t('select_template_prompt')).pack(pady=(0, 5))
        self.template_var = tk.StringVar()
        if templates:
            self.template_var.set(templates[0])
        self.combobox = ttk.Combobox(master, textvariable=self.template_var, values=templates, state="readonly", width=40)
        self.combobox.pack(pady=(0, 10))
        return self.combobox

    def buttonbox(self):
        box = ttk.Frame(self)
        ok_button = ttk.Button(box, text="OK", width=10, command=self.ok, bootstyle="success")
        ok_button.pack(side=tk.LEFT, padx=5, pady=5)
        cancel_button = ttk.Button(box, text=self.app._t('cancel_button'), width=10, command=self.cancel, bootstyle="secondary")
        cancel_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def ok(self, event=None):
        self.result = self.template_var.get()
        self.destroy()

    def cancel(self, event=None):
        self.destroy()

class AdvancedRegenerateDialog(tk.Toplevel):
    def __init__(self, parent, title, app_instance, initial_prompt=""):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.app = app_instance
        self.result = None

        body = ttk.Frame(self)
        self.initial_focus = self.body(body, initial_prompt)
        body.pack(padx=10, pady=10, fill="both", expand=True)

        self.buttonbox()
        self.grab_set()

        self.protocol("WM_DELETE_WINDOW", self.cancel)
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"600x400+{x}+{y}")
        self.initial_focus.focus_set()
        self.wait_window(self)

    def body(self, master, initial_prompt):
        master.columnconfigure(1, weight=1)

        # Prompt Entry
        ttk.Label(master, text=self.app._t('prompt_label')).grid(row=0, column=0, sticky='nw', padx=5, pady=5)
        self.prompt_text, text_container = self.app._create_scrolled_text(master, height=10, width=60)
        text_container.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        master.rowconfigure(0, weight=1)
        self.prompt_text.insert(tk.END, initial_prompt)
        add_text_widget_bindings(self.app, self.prompt_text)

        # API Service Selector
        ttk.Label(master, text=self.app._t('service_label')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.api_var = tk.StringVar(value=self.app.config.get("ui_settings", {}).get("image_generation_api", "pollinations"))
        api_combo = ttk.Combobox(master, textvariable=self.api_var, values=["pollinations", "recraft"], state="readonly")
        api_combo.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        api_combo.bind("<<ComboboxSelected>>", self.update_model_options)

        # Model Options Frame
        self.model_frame = ttk.Frame(master)
        self.model_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        self.model_frame.columnconfigure(1, weight=1)
        self.update_model_options()

        return self.prompt_text

    def update_model_options(self, event=None):
        for widget in self.model_frame.winfo_children():
            widget.destroy()

        service = self.api_var.get()
        if service == "pollinations":
            ttk.Label(self.model_frame, text=self.app._t('model_label')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
            self.poll_model_var = tk.StringVar(value=self.app.config["pollinations"]["model"])
            poll_model_dropdown = ttk.Combobox(self.model_frame, textvariable=self.poll_model_var, values=self.app.poll_available_models, state="readonly")
            poll_model_dropdown.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        elif service == "recraft":
            ttk.Label(self.model_frame, text=self.app._t('recraft_model_label')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
            self.recraft_model_var = tk.StringVar(value=self.app.config["recraft"]["model"])
            recraft_model_combo = ttk.Combobox(self.model_frame, textvariable=self.recraft_model_var, values=["recraftv3", "recraftv2"], state="readonly")
            recraft_model_combo.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
            
            ttk.Label(self.model_frame, text=self.app._t('recraft_style_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
            self.recraft_style_var = tk.StringVar(value=self.app.config["recraft"]["style"])
            recraft_style_combo = ttk.Combobox(self.model_frame, textvariable=self.recraft_style_var, values=["realistic_image", "digital_illustration", "vector_illustration", "icon", "logo_raster"], state="readonly")
            recraft_style_combo.grid(row=1, column=1, sticky='ew', padx=5, pady=2)

    def buttonbox(self):
        box = ttk.Frame(self)
        ok_button = ttk.Button(box, text="OK", width=10, command=self.ok, bootstyle="success")
        ok_button.pack(side=tk.LEFT, padx=5, pady=5)
        cancel_button = ttk.Button(box, text=self.app._t('cancel_button'), width=10, command=self.cancel, bootstyle="secondary")
        cancel_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack(pady=5)

    def ok(self, event=None):
        self.result = {
            "prompt": self.prompt_text.get("1.0", tk.END).strip(),
            "service": self.api_var.get()
        }
        if self.result["service"] == "pollinations":
            self.result["model"] = self.poll_model_var.get()
        elif self.result["service"] == "recraft":
            self.result["model"] = self.recraft_model_var.get()
            self.result["style"] = self.recraft_style_var.get()
        self.destroy()

    def cancel(self, event=None):
        self.result = None
        self.destroy()

# --- Основна логіка програми ---
class TranslationApp:
    def _check_dependencies(self):
        """Перевіряє наявність всіх необхідних бібліотек перед запуском."""
        try:
            from PIL import Image, ImageTk
        except ImportError:
            messagebox.showerror(self._t('missing_library_title'), self._t('pillow_missing_message'))
            sys.exit(1)
        
        try:
            import whisper
            import ffmpeg
        except ImportError:
            messagebox.showerror(self._t('missing_library_title'), self._t('whisper_ffmpeg_missing_message'))
            sys.exit(1)

        try:
            subprocess.run(['yt-dlp', '--version'], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        except (subprocess.CalledProcessError, FileNotFoundError):
            messagebox.showerror(self._t('missing_program_title'), self._t('yt-dlp_missing_message'))
            sys.exit(1)


    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.translations = load_translations()
        self.lang = self.config.get("ui_settings", {}).get("language", "ua")
        
        # Спочатку перевіряємо залежності, потім продовжуємо
        self._check_dependencies()

        self.log_context = threading.local()
        self.translations = load_translations()
        self.lang = self.config.get("ui_settings", {}).get("language", "ua")
        self.log_context = threading.local()
        self.speechify_lang_voice_map = LANG_VOICE_MAP # <-- ДОДАЙТЕ ЦЕЙ РЯДОК
        
        setup_ffmpeg_path(self.config)

        self.root.title(self._t("window_title"))
        try:
            icon_image = tk.PhotoImage(file='icon.png')
            self.root.iconphoto(False, icon_image)
        except tk.TclError as e:
            logger.warning(f"Не вдалося завантажити іконку програми: {e}")
        self.root.geometry("1100x800")
        
        self.or_api = OpenRouterAPI(self.config)
        self.poll_api = PollinationsAPI(self.config, self)
        self.el_api = ElevenLabsAPI(self.config)
        self.vm_api = VoiceMakerAPI(self.config)
        self.recraft_api = RecraftAPI(self.config)
        self.tg_api = TelegramAPI(self.config)
        self.speechify_api = SpeechifyAPI(self.config) # <-- НОВИЙ СЕРВІС
        self.montage_api = MontageAPI(self.config, self, self.update_progress_for_montage)

        self.task_queue = []
        self.is_processing_queue = False
        self.dynamic_scrollbars = []

        self.rewrite_task_queue = []
        self.is_processing_rewrite_queue = False
        self.processed_links = self.load_processed_links()

        self.pause_event = threading.Event()
        self.pause_event.set()
        self.shutdown_event = threading.Event()

        # Нові змінні для опитування Telegram
        self.telegram_polling_thread = None
        self.stop_telegram_polling = threading.Event()
        self.last_telegram_update_id = 0
        
        self.skip_image_event = threading.Event()
        self.regenerate_alt_service_event = threading.Event()
        self.skip_image_buttons = []
        self.switch_service_buttons = []
        self.regenerate_alt_buttons = []
        self.image_api_selectors = []
        self.active_image_api_var = tk.StringVar(value=self.config.get("ui_settings", {}).get("image_generation_api", "pollinations"))
        self.active_image_api = self.active_image_api_var.get()
        self.image_api_lock = threading.Lock()

        self.lang_output_path_vars = {}
        self.lang_widgets = {}
        self.lang_step_vars = {}
        self.lang_step_checkboxes = {}
        self.lang_output_frame = None
        
        self.rewrite_lang_step_vars = {}
        self.rewrite_lang_step_checkboxes = {}
        self.rewrite_lang_output_frame = None

        self.total_queue_steps = 0
        self.current_queue_step = 0
        self.gui_log_handler = None
        self.scrollable_canvases = []
        
        # Нова структура для відстеження статусу завдань для звіту
        self.task_completion_status = {}

        # Нові змінні для галереї
        self.image_gallery_frame = None
        self.continue_button = None
        self.image_control_active = threading.Event()
        
        # Словники для відповідності тем
        self.theme_map_to_display = {
            "darkly": self._t('theme_darkly'), 
            "cyborg": self._t('theme_cyborg'), 
            "litera": self._t('theme_litera')
        }
        self.theme_map_to_internal = {v: k for k, v in self.theme_map_to_display.items()}


        self.setup_gui()
        self.setup_global_bindings() 
        self.update_startup_balances() 
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.populate_rewrite_template_widgets()
        self.display_saved_balances()
        self.refresh_widget_colors()

    def display_saved_balances(self):
        vm_balance = self.config.get("voicemaker", {}).get("last_known_balance")
        vm_text = vm_balance if vm_balance is not None else "N/A"
        
        self.settings_vm_balance_label.config(text=f"{self._t('balance_label')}: {vm_text}")
        self.chain_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}")
        self.rewrite_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}")

    def _t(self, key, **kwargs):
        translation = self.translations.get(self.lang, {}).get(key, key)
        return translation.format(**kwargs)
    
    def _escape_markdown(self, text: str) -> str:
        """Надійно екранує спеціальні символи для Telegram MarkdownV2."""
        # Оновлений список символів, які потребують екранування
        escape_chars = r'\_*[]()~`>#+-=|{}.!'
        
        # Створюємо регулярний вираз для пошуку цих символів
        # і замінюємо кожен знайдений символ на його екрановану версію (з \ попереду)
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

    def _on_skip_image_click(self):
        logger.warning("Користувач натиснув 'Пропустити зображення'.")
        self.skip_image_event.set()
        self._update_button_states(is_processing=True, is_image_stuck=False)

    def _on_regenerate_alt_click(self):
        logger.warning("Користувач натиснув 'Спробувати іншим сервісом'.")
        self.regenerate_alt_service_event.set()
        self._update_button_states(is_processing=True, is_image_stuck=False)

    def _on_image_api_select(self, event=None):
        """Синхронізує вибір API на всіх вкладках та зберігає налаштування."""
        new_api = self.active_image_api_var.get()
        self.config["ui_settings"]["image_generation_api"] = new_api
        self.active_image_api = new_api
        logger.info(f"Default image generation API set to: {new_api}")
        # Синхронізація не потрібна, оскільки всі вони використовують одну й ту ж змінну
        save_config(self.config) # Зберігаємо зміну одразу

    def _on_switch_service_click(self):
        with self.image_api_lock:
            current_service = self.active_image_api
            new_service = "recraft" if current_service == "pollinations" else "pollinations"
            self.active_image_api = new_service
            logger.warning(f"Користувач перемкнув сервіс генерації зображень на: {new_service.capitalize()}")
            messagebox.showinfo("Сервіс змінено", f"Наступні зображення будуть генеруватися за допомогою {new_service.capitalize()}.")

    def _update_button_states(self, is_processing=False, is_image_stuck=False):
        """Централізовано оновлює стан кнопок управління."""
        switch_state = "normal" if is_processing else "disabled"
        stuck_state = "normal" if is_image_stuck else "disabled"

        for button in self.switch_service_buttons:
            if button:
                self.root.after(0, lambda b=button, s=switch_state: b.config(state=s))
        
        for button in self.skip_image_buttons:
            if button:
                self.root.after(0, lambda b=button, s=stuck_state: b.config(state=s))

        for button in self.regenerate_alt_buttons:
            if button:
                self.root.after(0, lambda b=button, s=stuck_state: b.config(state=s))

    def enable_skip_button(self):
        # Ця функція тепер вмикає ТІЛЬКИ кнопку пропуску
        for button in self.skip_image_buttons:
            if button:
                self.root.after(0, lambda b=button: b.config(state="normal"))

    def disable_skip_button(self):
        # Ця функція тепер вимикає ТІЛЬКИ кнопку пропуску
        for button in self.skip_image_buttons:
            if button:
                self.root.after(0, lambda b=button: b.config(state="disabled"))

    def on_closing(self):
        self.shutdown_event.set() # Сигнал всім потокам про зупинку
        logger.info("Завершення роботи програми та збереження налаштувань інтерфейсу...")
        if "ui_settings" not in self.config:
            self.config["ui_settings"] = {}
        
        if hasattr(self, 'main_text_frame'):
            self.config["ui_settings"]["main_text_height"] = self.main_text_frame.winfo_height()
        if hasattr(self, 'prompt_text_frame'):
            self.config["ui_settings"]["prompt_text_height"] = self.prompt_text_frame.winfo_height()
        if hasattr(self, 'cta_text_frame'):
            self.config["ui_settings"]["cta_text_height"] = self.cta_text_frame.winfo_height()
        if hasattr(self, 'lang_prompt_frame'):
            self.config["ui_settings"]["lang_text_height"] = self.lang_prompt_frame.winfo_height()
        if hasattr(self, 'rewrite_prompt_frame'):
            self.config["ui_settings"]["rewrite_prompt_height"] = self.rewrite_prompt_frame.winfo_height()

        if hasattr(self, 'queue_tree'):
            widths = {}
            widths['task_details'] = self.queue_tree.column("#0", "width")
            for col_id in self.queue_tree['columns']:
                widths[col_id] = self.queue_tree.column(col_id, "width")
            self.config["ui_settings"]["queue_column_widths"] = widths
            
        save_config(self.config)
        
        try:
            preview_folder = os.path.join(APP_BASE_PATH, "preview")
            if os.path.exists(preview_folder):
                logger.info("Очищення файлів попереднього перегляду...")
                for filename in os.listdir(preview_folder):
                    if filename.startswith("preview_video_") and filename.endswith(".mp4"):
                        file_path = os.path.join(preview_folder, filename)
                        os.remove(file_path)
                        logger.debug(f"Видалено: {file_path}")
        except Exception as e:
            logger.error(f"Помилка при очищенні папки 'preview': {e}")

        logger.info("Програму закрито.")
        self.root.destroy()
        
    def _update_elevenlabs_balance_labels(self, new_balance):
        balance_text = new_balance if new_balance is not None else 'N/A'
        self.root.after(0, lambda: self.settings_el_balance_label.config(text=f"{self._t('balance_label')}: {balance_text}"))
        self.root.after(0, lambda: self.chain_el_balance_label.config(text=f"{self._t('elevenlabs_balance_label')}: {balance_text}"))
        self.root.after(0, lambda: self.rewrite_el_balance_label.config(text=f"{self._t('elevenlabs_balance_label')}: {balance_text}"))
        logger.info(f"Інтерфейс оновлено: баланс ElevenLabs тепер {balance_text}")

    def _update_recraft_balance_labels(self, new_balance):
        balance_text = new_balance if new_balance is not None else 'N/A'
        self.root.after(0, lambda: self.settings_recraft_balance_label.config(text=f"{self._t('balance_label')}: {balance_text}"))
        self.root.after(0, lambda: self.chain_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {balance_text}"))
        self.root.after(0, lambda: self.rewrite_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {balance_text}"))
        logger.info(f"Інтерфейс оновлено: баланс Recraft тепер {balance_text}")

    def setup_global_bindings(self):
        mod_key = "Command" if sys.platform == "darwin" else "Control"
        widget_classes = ['TEntry', 'TSpinbox', 'Text', 'Listbox', 'TCombobox']
        for widget_class in widget_classes:
            self.root.bind_class(widget_class, f'<{mod_key}-c>', self._handle_copy)
            self.root.bind_class(widget_class, f'<{mod_key}-C>', self._handle_copy)
            self.root.bind_class(widget_class, f'<{mod_key}-Cyrillic_es>', self._handle_copy)
            self.root.bind_class(widget_class, f'<{mod_key}-x>', self._handle_cut)
            self.root.bind_class(widget_class, f'<{mod_key}-X>', self._handle_cut)
            self.root.bind_class(widget_class, f'<{mod_key}-Cyrillic_che>', self._handle_cut)
            self.root.bind_class(widget_class, f'<{mod_key}-v>', self._handle_paste)
            self.root.bind_class(widget_class, f'<{mod_key}-V>', self._handle_paste)
            self.root.bind_class(widget_class, f'<{mod_key}-Cyrillic_ve>', self._handle_paste)
            self.root.bind_class(widget_class, f'<{mod_key}-a>', self._handle_select_all)
            self.root.bind_class(widget_class, f'<{mod_key}-A>', self._handle_select_all)
            self.root.bind_class(widget_class, f'<{mod_key}-Cyrillic_ef>', self._handle_select_all)
        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel)
        self.root.bind_all("<Button-4>", self._on_global_mousewheel)
        self.root.bind_all("<Button-5>", self._on_global_mousewheel)

    def _handle_copy(self, event):
        widget = event.widget
        if widget:
            if widget is self.log_text and self.log_text.tag_ranges(tk.SEL):
                text = self.log_text.get(tk.SEL_FIRST, tk.SEL_LAST)
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
            elif hasattr(widget, 'event_generate'):
                widget.event_generate("<<Copy>>")
        return "break"

    def _handle_cut(self, event):
        widget = event.widget
        if widget and ('state' not in widget.configure() or widget.cget('state') != 'disabled'):
            if hasattr(widget, 'event_generate'):
                widget.event_generate("<<Cut>>")
        return "break"

    def _handle_paste(self, event):
        widget = event.widget
        try:
            is_disabled = hasattr(widget, 'cget') and widget.cget('state') == 'disabled'
            if widget and not is_disabled:
                if hasattr(widget, 'event_generate'):
                    widget.event_generate("<<Paste>>")
        except tk.TclError:
            pass
        return "break"

    def _handle_select_all(self, event):
        widget = event.widget
        if isinstance(widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            widget.selection_range(0, tk.END)
        elif isinstance(widget, (tk.Text, scrolledtext.ScrolledText)):
            is_log = (widget is self.log_text)
            if is_log: widget.configure(state='normal')
            widget.tag_add(tk.SEL, "1.0", tk.END)
            if is_log: widget.configure(state='disabled')
        return "break"

    def _on_global_mousewheel(self, event):
        try:
            target_widget = self.root.winfo_containing(event.x_root, event.y_root)
            if not target_widget:
                return
            parent = target_widget
            while parent:
                if isinstance(parent, tk.Canvas) and parent in self.scrollable_canvases:
                    delta = 0
                    if sys.platform == "darwin": delta = event.delta
                    elif event.num == 4: delta = -1
                    elif event.num == 5: delta = 1
                    elif event.delta: delta = -1 * int(event.delta / 120)
                    if delta != 0:
                        parent.yview_scroll(delta, "units")
                    return 
                if parent == self.root: break
                parent = parent.master
        except (KeyError, AttributeError):
            pass

    def setup_gui(self):
        self.notebook = ttk.Notebook(self.root, bootstyle="dark")
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.chain_frame = ttk.Frame(self.notebook)
        self.rewrite_frame = ttk.Frame(self.notebook)
        self.settings_frame = ttk.Frame(self.notebook)
        self.log_frame = ttk.Frame(self.notebook)

        # Спершу викликаємо функцію для створення і додавання вкладки "Створення завдання"
        create_task_tab(self.notebook, self)

        # Тепер додаємо решту вкладок у потрібному порядку
        self.notebook.add(self.rewrite_frame, text=self._t('rewrite_tab'))
        self.notebook.add(self.settings_frame, text=self._t('settings_tab'))
        self.notebook.add(self.log_frame, text=self._t('log_tab'))

        # Заповнюємо вмістом інші вкладки
        create_rewrite_tab(self.notebook, self)
        create_settings_tab(self.notebook, self)
        create_log_tab(self.notebook, self)

        # --- Створення контейнера для галереї (поки що прихований) ---
        self.image_gallery_frame = ttk.Frame(self.root)
        # self.image_gallery_frame.pack(fill='both', expand=True, padx=10, pady=10) # Ми покажемо його пізніше

        self.continue_button = ttk.Button(self.image_gallery_frame, text=self._t('continue_button'), command=self.continue_processing_after_image_control, bootstyle="success")
        # self.continue_button.pack(pady=10) # Також покажемо пізніше

    def add_to_queue(self, silent=False):
        selected_langs = [code for code, var in self.lang_checkbuttons.items() if var.get()]
        
        if not self.input_text.get("1.0", tk.END).strip():
            messagebox.showwarning(self._t('warning_title'), self._t('warning_no_text'))
            return False
        if not selected_langs:
            messagebox.showwarning(self._t('warning_title'), self._t('warning_no_lang'))
            return False

        task_steps = {}
        for lang_code in selected_langs:
            task_steps[lang_code] = {key: var.get() for key, var in self.lang_step_vars[lang_code].items()}

        lang_output_paths = {}
        output_cfg = self.config.get("output_settings", {})
        use_default_dir = output_cfg.get("use_default_dir", False)
        
        if not use_default_dir:
            lang_output_paths = {code: var.get() for code, var in self.lang_output_path_vars.items() if code in selected_langs and var.get().strip()}
            missing_paths = [lang_code.upper() for lang_code in selected_langs if not lang_output_paths.get(lang_code)]
            if missing_paths:
                messagebox.showwarning(self._t('warning_title'), f"{self._t('warning_no_path')}: {', '.join(missing_paths)}")
                return False
        else:
            default_dir = output_cfg.get("default_dir", "")
            if not default_dir or not os.path.isdir(default_dir):
                messagebox.showwarning(self._t('warning_title'), self._t('warning_invalid_default_dir'))
                return False

        task_name = f"{self._t('task_label')} {len(self.task_queue) + 1}"
        task_config = {
            "task_name": task_name,
            "input_text": self.input_text.get("1.0", tk.END).strip(),
            "selected_langs": selected_langs,
            "steps": task_steps,
            "timestamp": time.time(),
            "lang_output_paths": lang_output_paths
        }
            
        self.task_queue.append(task_config)
        self.update_queue_display()
        logger.info(f"Додано нове завдання '{task_name}' до черги. Загальна кількість завдань: {len(self.task_queue)}")
        
        if not silent:
            messagebox.showinfo(self._t('queue_title'), self._t('info_task_added'))
        
        self.clear_language_output_path_widgets()
        return True

    def clear_language_output_path_widgets(self):
        lang_codes_to_remove = list(self.lang_widgets.keys())
        for lang_code in lang_codes_to_remove:
            if lang_code in self.lang_checkbuttons:
                self.lang_checkbuttons[lang_code].set(False)
            self.remove_language_output_path_widgets(lang_code)

    def remove_language_output_path_widgets(self, lang_code):
        if lang_code in self.lang_widgets:
            self.lang_widgets[lang_code]['container'].destroy()
            del self.lang_widgets[lang_code]
            del self.lang_output_path_vars[lang_code]
            del self.lang_step_vars[lang_code]
            del self.lang_step_checkboxes[lang_code]

    def update_queue_display(self):
        if not hasattr(self, 'queue_tree'):
            return
        
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        
        steps_map = {
            'translate': self._t('step_translate'), 'cta': self._t('step_cta'), 
            'gen_prompts': self._t('step_gen_prompts'), 'gen_images': self._t('step_gen_images'), 
            'audio': self._t('step_audio'), 'create_subtitles': self._t('step_create_subtitles'),
            'create_video': self._t('step_create_video')
        }

        for i, task in enumerate(self.task_queue):
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(task['timestamp']))
            task_name = task.get('task_name', f"{self._t('task_label')} {i+1}")
            task_node = self.queue_tree.insert("", "end", iid=f"task_{i}", text=task_name, values=(self._t('status_pending'), timestamp), open=True)
            
            for lang_code in task['selected_langs']:
                use_default_dir = self.config.get("output_settings", {}).get("use_default_dir", False)
                lang_path_display = self._t('use_default_dir_label') if use_default_dir else task['lang_output_paths'].get(lang_code, '...')
                
                lang_node = self.queue_tree.insert(task_node, "end", text=f"  - {lang_code.upper()}", values=("", ""))
                
                self.queue_tree.insert(lang_node, "end", text=f"    {self._t('path_label')}: {lang_path_display}", values=("", ""))
                
                enabled_steps = [steps_map[key] for key, value in task['steps'][lang_code].items() if value]
                self.queue_tree.insert(lang_node, "end", text=f"    {self._t('steps_label')}: {', '.join(enabled_steps)}", values=("", ""))

    def process_queue(self):
        if self.is_processing_queue:
            messagebox.showinfo(self._t('queue_title'), self._t('info_queue_processing'))
            return
        if not self.task_queue:
            messagebox.showinfo(self._t('queue_title'), self._t('info_queue_empty'))
            return
        
        self.is_processing_queue = True
        self.pause_resume_button.config(state="normal")
        self._start_telegram_polling()
        
        thread = threading.Thread(target=self._process_hybrid_queue, args=(self.task_queue, 'main'))
        thread.daemon = True
        thread.start()

    def process_rewrite_queue(self):
        if self.is_processing_rewrite_queue:
            messagebox.showinfo(self._t('queue_title'), self._t('info_queue_processing'))
            return
        if not self.rewrite_task_queue:
            messagebox.showinfo(self._t('queue_title'), self._t('info_queue_empty'))
            return
        
        self.is_processing_rewrite_queue = True
        self._start_telegram_polling()
        
        thread = threading.Thread(target=self._process_hybrid_queue, args=(self.rewrite_task_queue, 'rewrite'))
        thread.daemon = True
        thread.start()

    def _image_generation_worker(self, data, task_key, task_num, total_tasks):
        prompts = data['text_results']['prompts']
        images_folder = data['text_results']['images_folder']
        lang_name = task_key[1].upper()

        with self.image_api_lock:
            if self.active_image_api is None:
                self.active_image_api = self.active_image_api_var.get()

        logger.info(f"Starting generation of {len(prompts)} images for {lang_name} using {self.active_image_api.capitalize()}.")

        auto_switch_enabled = self.config.get("ui_settings", {}).get("auto_switch_service_on_fail", False)
        retry_limit_for_switch = self.config.get("ui_settings", {}).get("auto_switch_retry_limit", 10)
        
        consecutive_failures = 0
        all_successful = True

        i = 0
        while i < len(prompts):
            if not self._check_app_state():
                all_successful = False
                break

            prompt = prompts[i]
            with self.image_api_lock:
                current_api_for_generation = self.active_image_api

            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - [{current_api_for_generation.capitalize()}] {self._t('step_gen_images')} {i+1}/{len(prompts)}..."
            self.update_progress(progress_text)

            image_path = os.path.join(images_folder, f"image_{i+1:03d}.jpg")

            # --- ОСНОВНА ЛОГІКА ОБРОБКИ ПОДІЙ ---
            # Перевіряємо, чи не було натиснуто одну з кнопок
            if self.skip_image_event.is_set():
                self.skip_image_event.clear()
                logger.warning(f"Skipping image {i+1} by user command.")
                i += 1
                continue

            if self.regenerate_alt_service_event.is_set():
                self.regenerate_alt_service_event.clear()
                logger.warning(f"Attempting to regenerate image {i+1} with alternate service.")
                with self.image_api_lock:
                    alt_service = "recraft" if self.active_image_api == "pollinations" else "pollinations"
                
                success_alt = False
                if alt_service == "pollinations":
                    success_alt = self.poll_api.generate_image(prompt, image_path)
                elif alt_service == "recraft":
                    success_alt, _ = self.recraft_api.generate_image(prompt, image_path)

                if success_alt:
                    logger.info(f"[{alt_service.capitalize()}] Successfully regenerated image {i+1} with alternate service.")
                    # Логіка успішної генерації, як у звичайному випадку
                    consecutive_failures = 0
                    self.image_prompts_map[image_path] = prompt
                    self.root.after(0, self._add_image_to_gallery, image_path, task_key)
                    status_key = f"{task_key[0]}_{task_key[1]}"
                    if status_key in self.task_completion_status:
                        self.task_completion_status[status_key]["images_generated"] += 1
                else:
                    logger.error(f"Alternate service [{alt_service.capitalize()}] also failed to generate image {i+1}.")
                    all_successful = False
                
                i += 1 # Переходимо до наступного зображення незалежно від результату
                continue
            
            # --- СТАНДАРТНА ГЕНЕРАЦІЯ ---
            success = False
            if current_api_for_generation == "pollinations":
                success = self.poll_api.generate_image(prompt, image_path)
            elif current_api_for_generation == "recraft":
                success, _ = self.recraft_api.generate_image(prompt, image_path)

            if success:
                consecutive_failures = 0 
                logger.info(f"[{current_api_for_generation.capitalize()}] Successfully generated image {i+1}/{len(prompts)}.")
                self.image_prompts_map[image_path] = prompt
                self.root.after(0, self._add_image_to_gallery, image_path, task_key)
                status_key = f"{task_key[0]}_{task_key[1]}"
                if status_key in self.task_completion_status:
                    self.task_completion_status[status_key]["images_generated"] += 1
                i += 1 
            else:
                consecutive_failures += 1
                logger.error(f"[{current_api_for_generation.capitalize()}] Failed to generate image {i+1}. Consecutive failures: {consecutive_failures}.")
                
                # Логіка автоматичного перемикання
                if auto_switch_enabled and consecutive_failures >= retry_limit_for_switch:
                    logger.warning(f"Reached {consecutive_failures} consecutive failures. Triggering automatic service switch.")
                    with self.image_api_lock:
                        new_service = "recraft" if self.active_image_api == "pollinations" else "pollinations"
                        self.active_image_api = new_service
                        self.active_image_api_var.set(new_service) # Оновлюємо змінну для GUI
                        logger.warning(f"Service automatically switched to: {self.active_image_api.capitalize()}")
                    consecutive_failures = 0
                    continue 

                # Логіка ручного втручання
                # Використовуємо ліміт з Pollinations як тригер для кнопок
                manual_intervention_limit = self.config.get("pollinations", {}).get("retries", 5)
                if consecutive_failures >= manual_intervention_limit:
                    logger.error(f"{manual_intervention_limit} consecutive failures for one image. Activating manual controls.")
                    self._update_button_states(is_processing=True, is_image_stuck=True)
                    self.tg_api.send_message_with_buttons(
                        message="❌ *Помилка генерації зображення*\n\nНе вдається згенерувати зображення\\. Процес очікує\\. Оберіть дію:",
                        buttons=[
                            {"text": "Пропустити", "callback_data": "skip_image_action"},
                            {"text": "Спробувати іншим", "callback_data": "regenerate_alt_action"},
                            {"text": "Перемкнути назавжди", "callback_data": "switch_service_action"}
                        ]
                    )
                    # Чекаємо на дію користувача
                    while not (self.skip_image_event.is_set() or self.regenerate_alt_service_event.is_set()):
                        if not self._check_app_state(): # Дозволяє паузу/продовження під час очікування
                            all_successful = False
                            break
                        time.sleep(0.5)
                    
                    self._update_button_states(is_processing=True, is_image_stuck=False) # Деактивуємо кнопки після дії
                    continue # Повертаємось на початок циклу, щоб обробити подію
                
                # Якщо нічого не спрацювало, просто переходимо до наступного зображення
                all_successful = False
                i += 1

        return all_successful

    def _start_telegram_polling(self):
        """Запускає потік для опитування оновлень Telegram, якщо він ще не запущений."""
        if not self.tg_api.enabled:
            return
        if self.telegram_polling_thread and self.telegram_polling_thread.is_alive():
            logger.info("Telegram polling thread is already running.")
            return

        self.stop_telegram_polling.clear()
        self.telegram_polling_thread = threading.Thread(target=self._poll_telegram_updates, daemon=True)
        self.telegram_polling_thread.start()
        logger.info("Started Telegram polling thread.")

    def _poll_telegram_updates(self):
        """Цикл, що опитує Telegram на наявність натискань кнопок."""
        while not self.stop_telegram_polling.is_set():
            updates = self.tg_api.get_updates(offset=self.last_telegram_update_id + 1)
            if updates and updates.get("ok"):
                for update in updates.get("result", []):
                    self.last_telegram_update_id = update["update_id"]
                    
                    if "callback_query" in update:
                        callback_data = update["callback_query"]["data"]
                        query_id = update["callback_query"]["id"]
                        logger.info(f"Received Telegram callback: {callback_data}")
                        
                        if callback_data == "skip_image_action":
                            self.root.after(0, self._on_skip_image_click)
                            self.tg_api.answer_callback_query(query_id, "Пропускаю зображення...")
                        elif callback_data == "switch_service_action":
                            self.root.after(0, self._on_switch_service_click)
                            self.tg_api.answer_callback_query(query_id, "Перемикаю сервіс...")
                        elif callback_data == "regenerate_alt_action":
                            self.root.after(0, self._on_regenerate_alt_click)
                            self.tg_api.answer_callback_query(query_id, "Пробую іншим сервісом...")
                        elif callback_data == "continue_montage_action":
                            self.root.after(0, self.continue_processing_after_image_control)
                            self.tg_api.answer_callback_query(query_id)
            
            time.sleep(2) # Затримка між запитами
        logger.info("Stopped Telegram polling thread.")

    def setup_empty_gallery(self, queue_type, tasks_to_display):
        if queue_type == 'main': 
            gallery_parent_frame = self.chain_image_gallery_frame
            self.active_gallery_canvas = self.chain_canvas
        elif queue_type == 'rewrite': 
            gallery_parent_frame = self.rewrite_image_gallery_frame
            self.active_gallery_canvas = self.rewrite_canvas
        else: return

        for widget in gallery_parent_frame.winfo_children(): widget.destroy()
        gallery_parent_frame.pack(fill='x', expand=True, padx=10, pady=10)

        self.gallery_lang_containers = {}
        self.image_widgets = {} 
        self.image_prompts_map = {}
        if not hasattr(self, 'gallery_photo_references'):
            self.gallery_photo_references = []
        self.gallery_photo_references.clear()

        for task_index, task in enumerate(tasks_to_display):
            task_frame = ttk.Labelframe(gallery_parent_frame, text=task.get('task_name'))
            task_frame.pack(fill='x', expand=True, padx=10, pady=5)
            
            for lang_code in task['selected_langs']:
                task_key = (task_index, lang_code)
                lang_frame = ttk.Labelframe(task_frame, text=lang_code.upper())
                lang_frame.pack(fill='x', expand=True, padx=5, pady=5)
                
                # Цей фрейм буде містити всі картинки для даної мови
                image_flow_container = ttk.Frame(lang_frame)
                image_flow_container.pack(fill='both', expand=True)

                # Створюємо перший "рядок" для картинок
                row_frame = ttk.Frame(image_flow_container)
                row_frame.pack(fill='x', anchor='nw')

                self.gallery_lang_containers[task_key] = {
                    "main_container": image_flow_container,
                    "current_row": row_frame,
                    "current_width": 0
                }

        # Створюємо кнопку "Продовжити", тільки якщо опція паузи увімкнена
        if self.config.get("ui_settings", {}).get("image_control_enabled", False):
            self.continue_button = ttk.Button(gallery_parent_frame, text=self._t('continue_montage_button'), command=self.continue_processing_after_image_control, bootstyle="success")
            self.continue_button.pack(pady=10, side='bottom')
            
        self.image_control_active.clear()

    def _add_image_to_gallery(self, image_path, task_key):
        container_info = self.gallery_lang_containers.get(task_key)
        if not container_info: return

        main_container = container_info['main_container']
        
        # --- КЛЮЧОВА ЗМІНА АРХІТЕКТУРИ ---
        # Ми більше не створюємо фрейм картинки заздалегідь.
        # Спочатку ми визначаємо, в якому РЯДКУ вона має бути, і лише ПОТІМ створюємо її.

        try:
            # 1. Отримуємо актуальні розміри майбутньої картинки (створюючи тимчасовий фрейм)
            temp_frame = ttk.Frame(main_container)
            temp_frame.update_idletasks()
            frame_width = temp_frame.winfo_reqwidth() + 200 # Приблизна ширина (256px) з кнопками
            temp_frame.destroy()
            
            container_width = self.active_gallery_canvas.winfo_width() - 20

            # 2. Перевіряємо, чи потрібен новий рядок
            if container_info['current_width'] > 0 and (container_info['current_width'] + frame_width) > container_width:
                new_row = ttk.Frame(main_container)
                new_row.pack(fill='x', anchor='nw')
                container_info['current_row'] = new_row
                container_info['current_width'] = 0
            
            # 3. Тепер, коли ми точно знаємо батьківський рядок, СТВОРЮЄМО фрейм картинки
            current_row = container_info['current_row']
            single_image_frame = ttk.Frame(current_row, bootstyle="secondary", padding=5)
            single_image_frame.pack(side='left', padx=5, pady=5, anchor='nw')
            
            # 4. Наповнюємо фрейм вмістом
            img = Image.open(image_path)
            img.thumbnail((256, 144))
            photo = ImageTk.PhotoImage(img)
            self.gallery_photo_references.append(photo)

            img_label = ttk.Label(single_image_frame, image=photo)
            img_label.image = photo
            img_label.pack(pady=5)
            
            self.image_widgets[image_path] = single_image_frame

            buttons_frame = ttk.Frame(single_image_frame)
            buttons_frame.pack(fill='x', pady=(5,0))
            
            ttk.Button(buttons_frame, text="🗑️", bootstyle="danger-outline", width=2, command=lambda p=image_path: self._delete_image(p)).pack(side='left', expand=True, fill='x')
            ttk.Button(buttons_frame, text="✏️", bootstyle="info-outline", width=2, command=lambda p=image_path: self._edit_prompt_and_regenerate(p)).pack(side='left', expand=True, fill='x')
            ttk.Button(buttons_frame, text="🔄", bootstyle="success-outline", width=2, command=lambda p=image_path: self._regenerate_image(p, use_random_seed=True)).pack(side='left', expand=True, fill='x')

            # 5. Оновлюємо зайняту ширину
            single_image_frame.update_idletasks()
            container_info['current_width'] += single_image_frame.winfo_reqwidth() + 10

            # 6. Оновлюємо область прокрутки
            if hasattr(self, 'active_gallery_canvas'):
                canvas = self.active_gallery_canvas
                canvas.config(scrollregion=canvas.bbox("all"))

        except Exception as e:
            logger.error(f"Could not load image {image_path}: {e}")

    def _rewrite_text_processing_worker(self, task, lang_code):
        """Обробляє ВЖЕ транскрибований текст для одного завдання рерайту."""
        try:
            video_title = task['video_title']
            transcribed_text = task['transcribed_text']
            rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']

            if not transcribed_text.strip(): return None

            # Подальша обробка для конкретної мови
            lang_output_path = os.path.join(rewrite_base_dir, video_title, lang_code.upper())
            os.makedirs(lang_output_path, exist_ok=True)

            selected_template_name = self.rewrite_template_var.get()
            rewrite_prompt_template = self.config.get("rewrite_prompt_templates", {}).get(selected_template_name, {}).get(lang_code)
            
            rewritten_text = self.or_api.rewrite_text(transcribed_text, self.config["openrouter"]["rewrite_model"], self.config["openrouter"]["rewrite_params"], rewrite_prompt_template)
            if not rewritten_text: return None
            
            with open(os.path.join(lang_output_path, "rewritten_text.txt"), "w", encoding='utf-8') as f: f.write(rewritten_text)
            
            # CTA та промти
            cta_path = os.path.join(lang_output_path, "call_to_action.txt")
            prompts_path = os.path.join(lang_output_path, "image_prompts.txt")

            # Генерація CTA або читання з файлу
            if task['steps'][lang_code]['cta']:
                cta_text = self.or_api.generate_call_to_action(rewritten_text, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"])
                if cta_text:
                    with open(cta_path, 'w', encoding='utf-8') as f: f.write(cta_text)

            # Генерація промтів або читання з файлу
            raw_prompts = None
            if task['steps'][lang_code]['gen_prompts']:
                raw_prompts = self.or_api.generate_image_prompts(rewritten_text, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"])
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
            elif os.path.exists(prompts_path):
                logger.info(f"Using existing prompts file for rewrite task: {prompts_path}")
                with open(prompts_path, 'r', encoding='utf-8') as f:
                    raw_prompts = f.read()

            image_prompts = []
            if raw_prompts:
                # Універсальна логіка: об'єднуємо багаторядкові промпти, а потім розділяємо за нумерацією
                # Спочатку замінюємо всі переноси рядків на пробіли
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                # Розділяємо за шаблоном "число." (наприклад, "1.", "2." і т.д.), видаляючи сам роздільник
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                # Перший елемент після розділення зазвичай порожній, тому відфільтровуємо його
                image_prompts = [block.strip() for block in prompt_blocks if block.strip()]

            images_folder = os.path.join(lang_output_path, "images")
            os.makedirs(images_folder, exist_ok=True)
            
            return {
                "text_to_process": rewritten_text, "output_path": lang_output_path,
                "prompts": image_prompts, "images_folder": images_folder, "video_title": video_title
            }
        except Exception as e:
            logger.exception(f"Error in rewrite text processing worker for {lang_code}: {e}")
            return None

    def _process_hybrid_queue(self, queue_to_process_list, queue_type):
        is_rewrite = queue_type == 'rewrite'
        if is_rewrite:
            self.is_processing_rewrite_queue = True
        else:
            self.is_processing_queue = True
        
        self._update_button_states(is_processing=True, is_image_stuck=False)

        try:
            queue_to_process = list(queue_to_process_list)
            if is_rewrite:
                self.rewrite_task_queue.clear()
                self.update_rewrite_queue_display()
            else:
                self.task_queue.clear()
                self.update_queue_display()
            
            # Ініціалізація статусу для всіх завдань у черзі
            self.task_completion_status = {}
            for i, task in enumerate(queue_to_process):
                task['task_index'] = i
                for lang_code in task['selected_langs']:
                    task_key = f"{i}_{lang_code}"
                    self.task_completion_status[task_key] = {
                        "task_name": task.get('task_name'),
                        "steps": {self._t('step_name_' + step_name): "⚪️" for step_name, enabled in task['steps'][lang_code].items() if enabled},
                        "images_generated": 0, # Лічильник успішних зображень
                        "total_images": 0      # Загальна кількість зображень для генерації
                    }

            processing_data = {}

            # --- ЕТАП 0: (ТІЛЬКИ ДЛЯ РЕРАЙТУ) ТРАНСКРИПЦІЯ ---
            if is_rewrite:
                self.update_progress(self._t('phase_0_transcription'))
                logger.info("Гібридний режим -> Етап 0: Послідовна транскрипція локальних файлів.")
                
                transcribed_texts = {}
                rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']
                
                for task in queue_to_process:
                    mp3_path = task['mp3_path']
                    original_filename = task['original_filename']
                    
                    if mp3_path not in transcribed_texts:
                        # --- ВИПРАВЛЕННЯ ---
                        # Спочатку отримуємо "чисту" назву, а потім санітизуємо її для створення папки
                        video_title = sanitize_filename(os.path.splitext(original_filename)[0])
                        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
                        
                        task_output_dir = os.path.join(rewrite_base_dir, video_title)
                        os.makedirs(task_output_dir, exist_ok=True)
                        original_transcript_path = os.path.join(task_output_dir, "original_transcript.txt")
                        
                        if os.path.exists(original_transcript_path):
                            with open(original_transcript_path, "r", encoding='utf-8') as f:
                                transcribed_text = f.read()
                        else:
                            model = self.montage_api._load_whisper_model()
                            if not model:
                                logger.error("Не вдалося завантажити модель Whisper. Переривання.")
                                return
                            transcription_result = model.transcribe(mp3_path, verbose=False)
                            transcribed_text = transcription_result['text']
                            with open(original_transcript_path, "w", encoding='utf-8') as f:
                                f.write(transcribed_text)

                        transcribed_texts[mp3_path] = {"text": transcribed_text, "title": video_title}

                for task in queue_to_process:
                    if task['mp3_path'] in transcribed_texts:
                        task['transcribed_text'] = transcribed_texts[task['mp3_path']]['text']
                        task['video_title'] = transcribed_texts[task['mp3_path']]['title']
                        
                        # Оновлюємо статус транскрипції для всіх мов у цьому завданні
                        task_idx_str = task['task_index']
                        step_name_key = self._t('step_name_transcribe')
                        for lang_code in task['selected_langs']:
                            status_key = f"{task_idx_str}_{lang_code}"
                            if status_key in self.task_completion_status and step_name_key in self.task_completion_status[status_key]['steps']:
                                self.task_completion_status[status_key]['steps'][step_name_key] = "✅"


            # --- ЕТАП 1: ПАРАЛЕЛЬНА ОБРОБКА ТЕКСТУ ---
            self.update_progress(self._t('phase_1_text_processing'))
            logger.info(f"Гібридний режим -> Етап 1: Паралельна обробка тексту для {len(queue_to_process)} завдань.")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                text_futures = {}
                worker = self._rewrite_text_processing_worker if is_rewrite else self._text_processing_worker

                for task_index, task in enumerate(queue_to_process):
                    if is_rewrite and 'transcribed_text' not in task:
                        continue
                    
                    for lang_code in task['selected_langs']:
                        task_key = (task_index, lang_code)
                        processing_data[task_key] = {'task': task} 
                        future = executor.submit(worker, task, lang_code)
                        text_futures[future] = task_key
                
                for future in concurrent.futures.as_completed(text_futures):
                    task_key = text_futures[future]
                    processing_data[task_key]['text_results'] = future.result()

            logger.info("Гібридний режим -> Етап 1: Обробку тексту завершено.")
            
            # --- ОНОВЛЕНИЙ БЛОК ПІСЛЯ ОБРОБКИ ТЕКСТУ ---
            for task_key, data in processing_data.items():
                task_idx_str, lang_code = task_key
                status_key = f"{task_idx_str}_{lang_code}"

                if status_key in self.task_completion_status:
                    if data.get('text_results'):
                        # Відмічаємо успішність текстових етапів
                        steps_to_mark = ['translate', 'rewrite', 'cta', 'gen_prompts']
                        for step in steps_to_mark:
                            step_name_key = self._t('step_name_' + step)
                            if step_name_key in self.task_completion_status[status_key]['steps']:
                                self.task_completion_status[status_key]['steps'][step_name_key] = "✅"
                        
                        # Зберігаємо загальну кількість запланованих зображень
                        num_prompts = len(data['text_results'].get("prompts", []))
                        self.task_completion_status[status_key]["total_images"] = num_prompts
                    else:
                        # Якщо текстовий етап провалився, відмічаємо всі наступні як провалені
                        for step_name in self.task_completion_status[status_key]['steps']:
                            self.task_completion_status[status_key]['steps'][step_name] = "❌"


            # --- ЕТАП 2: ОДНОЧАСНА ГЕНЕРАЦІЯ МЕДІА ---
            self.update_progress(self._t('phase_2_media_generation'))
            logger.info("Гібридний режим -> Етап 2: Одночасна генерація медіа.")
            
            self.root.after(0, self.setup_empty_gallery, queue_type, queue_to_process)
            
            should_gen_images = any(
                data.get('text_results') and data['task']['steps'][key[1]].get('gen_images')
                for key, data in processing_data.items()
            )

            if should_gen_images:
                image_master_thread = threading.Thread(target=self._sequential_image_master, args=(processing_data, queue_to_process))
                image_master_thread.start()
            else:
                image_master_thread = None
                logger.info("Гібридний режим -> Етап генерації зображень вимкнено для всіх завдань. Пропускаємо.")

            audio_subs_master_thread = threading.Thread(target=self._audio_subs_pipeline_master, args=(processing_data,))
            audio_subs_master_thread.start()
            
            if image_master_thread:
                image_master_thread.join()
            audio_subs_master_thread.join()
            
            logger.info("Гібридний режим -> Етап 2: Генерацію всіх медіафайлів завершено.")
            
            # --- ЕТАП 3: ОПЦІОНАЛЬНА ПАУЗА ---
            if self.config.get("ui_settings", {}).get("image_control_enabled", False) and should_gen_images:
                self.update_progress(self._t('phase_3_image_control'))
                logger.info("Гібридний режим -> Етап 3: Пауза для налаштування зображень користувачем.")
                
                # Надсилаємо повідомлення в Telegram
                self.tg_api.send_message_with_buttons(
                    message="🎨 *Контроль зображень*\n\nВсі зображення згенеровано\\. Будь ласка, перегляньте та відредагуйте їх у програмі, перш ніж продовжити монтаж\\.",
                    buttons=[
                        {"text": "✅ Продовжити монтаж", "callback_data": "continue_montage_action"}
                    ]
                )

                self.image_control_active.wait()
            else:
                logger.info("Гібридний режим -> Етап 3: Пауза вимкнена або не потрібна, перехід до монтажу.")

            # --- ЕТАП 4: ФІНАЛЬНИЙ МОНТАЖ ТА ЗВІТИ ПО МОВАХ ---
            self.update_progress(self._t('phase_4_final_montage'))
            logger.info("Гібридний режим -> Етап 4: Початок фінального монтажу та звітів по мовах.")

            for task_key, data in sorted(processing_data.items()):
                lang_code = task_key[1]
                task_idx_str = task_key[0]
                status_key = f"{task_idx_str}_{lang_code}"
                
                if data.get('task') and data.get('text_results') and data['task']['steps'][lang_code].get('create_video'):
                    
                    images_folder = data['text_results']['images_folder']
                    all_images = sorted([os.path.join(images_folder, f) for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                    
                    if not data.get('audio_chunks') or not data.get('subs_chunks'):
                        logger.error(f"Аудіо або субтитри відсутні для завдання {task_key}. Пропускаємо монтаж відео.")
                        if status_key in self.task_completion_status:
                            step_name = self._t('step_name_create_video')
                            self.task_completion_status[status_key]['steps'][step_name] = "❌"
                        continue
                        
                    if not all_images:
                        logger.error(f"Зображення не знайдено для завдання {task_key}. Пропускаємо монтаж відео.")
                        if status_key in self.task_completion_status:
                            step_name = self._t('step_name_create_video')
                            self.task_completion_status[status_key]['steps'][step_name] = "❌"
                        continue

                    image_chunks = np.array_split(all_images, len(data['audio_chunks']))
                    
                    video_chunk_paths = []
                    num_montage_threads = self.config.get('parallel_processing', {}).get('num_chunks', 3)

                    with concurrent.futures.ThreadPoolExecutor(max_workers=num_montage_threads) as executor:
                        video_futures = {
                            executor.submit(
                                self._video_chunk_worker, 
                                list(image_chunks[i]), 
                                data['audio_chunks'][i], 
                                data['subs_chunks'][i],
                                os.path.join(data['temp_dir'], f"video_chunk_{i}.mp4"),
                                i + 1, len(data['audio_chunks'])
                            ): i for i in range(len(data['audio_chunks']))
                        }
                        for f in concurrent.futures.as_completed(video_futures):
                            result = f.result()
                            if result: video_chunk_paths.append(result)

                    if len(video_chunk_paths) == len(data['audio_chunks']):
                        if 'video_title' in data['text_results']:
                            base_name = sanitize_filename(data['text_results']['video_title'])
                        else:
                            base_name = sanitize_filename(data['text_results'].get('task_name', f"Task_{task_key[0]}"))
                        
                        final_video_path = os.path.join(data['text_results']['output_path'], f"video_{base_name}_{lang_code}.mp4")
                        if self._concatenate_videos(sorted(video_chunk_paths), final_video_path):
                            logger.info(f"УСПІХ: Створено фінальне відео: {final_video_path}")
                            if status_key in self.task_completion_status:
                                step_name = self._t('step_name_create_video')
                                self.task_completion_status[status_key]['steps'][step_name] = "✅"
                            if is_rewrite:
                                self.save_processed_link(data['task']['original_filename'])
                        else:
                             if status_key in self.task_completion_status:
                                step_name = self._t('step_name_create_video')
                                self.task_completion_status[status_key]['steps'][step_name] = "❌"
                    else:
                        logger.error(f"ПОМИЛКА: Не вдалося створити всі частини відео для завдання {task_key}.")
                        if status_key in self.task_completion_status:
                            step_name = self._t('step_name_create_video')
                            self.task_completion_status[status_key]['steps'][step_name] = "❌"
                
                # Відправка звіту після завершення обробки однієї мови
                report_timing = self.config.get("telegram", {}).get("report_timing", "per_task")
                if report_timing == "per_language":
                    self.send_task_completion_report(data['task'], single_lang_code=lang_code)

            # --- ФІНАЛЬНИЙ КРОК: ВІДПРАВКА ЗВІТІВ ДЛЯ ВСЬОГО ЗАВДАННЯ ---
            logger.info("Гібридний режим -> Всі завдання завершено. Відправка фінальних звітів...")
            report_timing = self.config.get("telegram", {}).get("report_timing", "per_task")
            if report_timing == "per_task":
                for task_config in queue_to_process:
                    self.send_task_completion_report(task_config)
            
            self.root.after(0, lambda: self.progress_label.config(text=self._t('status_complete')))
            self.root.after(0, lambda: messagebox.showinfo(self._t('queue_title'), self._t('info_queue_complete')))

        except Exception as e:
            logger.exception(f"КРИТИЧНА ПОМИЛКА: Непередбачена помилка при обробці гібридної черги: {e}")
        finally:
            # --- НОВА ЛОГІКА: Очищення тимчасових файлів ---
            keep_temp_files = self.config.get('parallel_processing', {}).get('keep_temp_files', False)
            if not keep_temp_files:
                self.update_progress(self._t('phase_cleaning_up'))
                for task_key, data in processing_data.items():
                    if 'temp_dir' in data and os.path.exists(data['temp_dir']):
                        try:
                            shutil.rmtree(data['temp_dir'])
                            logger.info(f"Очищено тимчасову директорію: {data['temp_dir']}")
                        except Exception as e:
                            logger.error(f"Не вдалося видалити тимчасову директорію {data['temp_dir']}: {e}")
            # --- КІНЕЦЬ НОВОЇ ЛОГІКИ ---

            self.stop_telegram_polling.set() # Зупиняємо опитування
            self._update_button_states(is_processing=False, is_image_stuck=False)
            if is_rewrite:
                self.is_processing_rewrite_queue = False
                self.root.after(0, self.update_rewrite_queue_display)
            else:
                self.is_processing_queue = False
                self.root.after(0, self.update_queue_display)
            
            if hasattr(self, 'pause_resume_button'):
                 self.root.after(0, lambda: self.pause_resume_button.config(text=self._t('pause_button'), state="disabled"))
            self.pause_event.set()

    def _text_processing_worker(self, task, lang_code):
        """Виконує всі текстові операції для одного мовного завдання."""
        try:
            lang_name = lang_code.upper()
            lang_config = self.config["languages"][lang_code]
            lang_steps = task['steps'][lang_code]
            output_cfg = self.config.get("output_settings", {})
            use_default_dir = output_cfg.get("use_default_dir", False)

            # Визначення шляху для збереження
            if use_default_dir:
                task_name = sanitize_filename(task.get('task_name', f"Task_{int(time.time())}"))
                output_path = os.path.join(output_cfg.get("default_dir", ""), task_name, lang_name)
            else:
                output_path = task['lang_output_paths'].get(lang_code)
            
            if not output_path:
                logger.error(f"Немає шляху виводу для {lang_name} у завданні {task.get('task_name')}.")
                return None
            os.makedirs(output_path, exist_ok=True)

            text_to_process = task['input_text']
            translation_path = os.path.join(output_path, "translation.txt")

            # --- ОСНОВНА ЗМІНА ЛОГІКИ ---
            if lang_steps.get('translate'):
                # logger.info(f"[TextWorker] Translating for {lang_name}...")
                translated_text = self.or_api.translate_text(
                    task['input_text'], self.config["openrouter"]["translation_model"],
                    self.config["openrouter"]["translation_params"], lang_name,
                    custom_prompt_template=lang_config.get("prompt")
                )
                if translated_text:
                    text_to_process = translated_text
                    with open(translation_path, 'w', encoding='utf-8') as f:
                        f.write(translated_text)
                else:
                    logger.error(f"Translation failed for {lang_name}.")
                    return None
            elif os.path.exists(translation_path):
                 with open(translation_path, 'r', encoding='utf-8') as f:
                    text_to_process = f.read()
                 logger.info(f"Using existing translation file for {lang_name}: {translation_path}")
            else:
                logger.info(f"Translation step is disabled and no existing translation file was found for {lang_name}. Using original text.")
                text_to_process = task['input_text'] # Явно вказуємо, що використовуємо оригінал
            # --- КІНЕЦЬ ЗМІНИ ЛОГІКИ ---

            cta_text, raw_prompts = None, None
            prompts_path = os.path.join(output_path, "image_prompts.txt")
            
            # Генерація CTA (завжди з text_to_process)
            if lang_steps.get('cta'):
                 cta_text = self.or_api.generate_call_to_action(text_to_process, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"], lang_name)
                 if cta_text:
                     with open(os.path.join(output_path, "call_to_action.txt"), 'w', encoding='utf-8') as f: f.write(cta_text)

            # Генерація промптів або їх читання
            image_prompts = []
            if lang_steps.get('gen_prompts'):
                raw_prompts = self.or_api.generate_image_prompts(text_to_process, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"], lang_name)
                if raw_prompts:
                    with open(prompts_path, 'w', encoding='utf-8') as f: f.write(raw_prompts)
            elif os.path.exists(prompts_path):
                logger.info(f"Using existing prompts file: {prompts_path}")
                with open(prompts_path, 'r', encoding='utf-8') as f:
                    raw_prompts = f.read()

            if raw_prompts:
                # Універсальна логіка: об'єднуємо багаторядкові промпти, а потім розділяємо за нумерацією
                # Спочатку замінюємо всі переноси рядків на пробіли
                single_line_text = raw_prompts.replace('\n', ' ').strip()
                # Розділяємо за шаблоном "число." (наприклад, "1.", "2." і т.д.), видаляючи сам роздільник
                prompt_blocks = re.split(r'\s*\d+[\.\)]\s*', single_line_text)
                # Перший елемент після розділення зазвичай порожній, тому відфільтровуємо його
                image_prompts = [block.strip() for block in prompt_blocks if block.strip()]

            images_folder = os.path.join(output_path, "images")
            os.makedirs(images_folder, exist_ok=True)

            return {
                "text_to_process": text_to_process,
                "output_path": output_path,
                "prompts": image_prompts,
                "images_folder": images_folder,
                "task_name": task.get('task_name', 'Untitled_Task')
            }
        except Exception as e:
            logger.exception(f"Error in text processing worker for {lang_code}: {e}")
            return None

    def _audio_worker(self, data):
        """Генерує ТІЛЬКИ аудіо для одного мовного завдання (для паралельного запуску)."""
        try:
            task = data['task']
            lang_code = data['text_results']['output_path'].split(os.sep)[-1].lower()
            lang_steps = task['steps'][lang_code]
            output_path = data['text_results']['output_path']
            text_to_process = data['text_results']['text_to_process']
            lang_config = self.config["languages"][lang_code]
            
            audio_path = os.path.join(output_path, "audio.mp3")

            if lang_steps.get('audio'):
                logger.info(f"[AudioWorker] Starting parallel audio generation for {lang_code}...")
                tts_service = lang_config.get("tts_service", "elevenlabs")
                if tts_service == "elevenlabs":
                    task_id = self.el_api.create_audio_task(text_to_process, lang_config.get("elevenlabs_template_uuid"))
                    if task_id and self.wait_for_elevenlabs_task(task_id, audio_path):
                        logger.info(f"[AudioWorker] ElevenLabs audio saved for {lang_code}.")
                        return audio_path
                elif tts_service == "voicemaker":
                    success, _ = self.vm_api.generate_audio(text_to_process, lang_config.get("voicemaker_voice_id"), lang_config.get("voicemaker_engine"), lang_code, audio_path)
                    if success:
                        return audio_path
            
            return None # Повертаємо None, якщо аудіо не створювалося або сталася помилка
        except Exception as e:
            logger.exception(f"Error in parallel audio worker: {e}")
            return None
        
    def _parallel_audio_master(self, processing_data):
        """Головний потік, що керує паралельною генерацією всіх аудіофайлів."""
        logger.info("[Image Control] Audio Master Thread: Starting parallel audio generation.")
        with concurrent.futures.ThreadPoolExecutor() as executor:
            audio_futures = {}
            for task_key, data in processing_data.items():
                if data.get('text_results') and data['task']['steps'][task_key[1]].get('audio'):
                    future = executor.submit(self._audio_worker, data)
                    audio_futures[future] = task_key
            
            for future in concurrent.futures.as_completed(audio_futures):
                task_key = audio_futures[future]
                # Результат (шлях до аудіо) записується в загальний словник
                processing_data[task_key]['audio_path'] = future.result()
        logger.info("[Image Control] Audio Master Thread: All audio generation tasks complete.")

    def _sequential_image_master(self, processing_data, queue_to_process):
        """Головний потік, що керує послідовною генерацією всіх зображень."""
        logger.info("[Image Control] Image Master Thread: Starting sequential image generation.")
        for task_key, data in sorted(processing_data.items()):
            task_idx_str, lang_code = task_key
            status_key = f"{task_idx_str}_{lang_code}"
            step_name = self._t('step_name_gen_images')

            if data.get('text_results') and data['task']['steps'][lang_code].get('gen_images'):
                success = self._image_generation_worker(data, task_key, task_idx_str + 1, len(queue_to_process))
                if status_key in self.task_completion_status:
                    # Тепер ми перевіряємо, чи були згенеровані якісь зображення
                    if self.task_completion_status[status_key]["images_generated"] > 0:
                        self.task_completion_status[status_key]['steps'][step_name] = "✅"
                    else:
                        # Якщо жодного зображення не згенеровано, вважаємо крок проваленим
                        self.task_completion_status[status_key]['steps'][step_name] = "❌"
            else:
                if status_key in self.task_completion_status and step_name in self.task_completion_status[status_key]['steps']:
                    self.task_completion_status[status_key]['steps'][step_name] = "⚪️" # Mark as skipped, not failed

        logger.info("[Image Control] Image Master Thread: All image generation tasks complete.")

    def _check_app_state(self):
        """Перевіряє, чи не зупинено програму. Повертає False, якщо треба зупинити потік."""
        if self.shutdown_event.is_set():
            return False
        
        if not self.pause_event.is_set():
            original_text = self.progress_label.cget("text")
            self.update_progress(self._t('status_paused'))
            self.pause_event.wait()
            if self.shutdown_event.is_set(): # Перевіряємо знову після паузи
                return False
            self.update_progress(original_text)
        return True
            
    def _run_single_chain(self, task_num, total_tasks, original_text, lang_code, lang_steps, lang_output_paths=None):
        if lang_output_paths is None: lang_output_paths = {}

        translation_model = self.config["openrouter"]["translation_model"]
        translation_params = self.config["openrouter"]["translation_params"]

        lang_config = self.config["languages"][lang_code]
        lang_name = lang_code.upper()
        
        text_to_process = original_text
        
        if not self._check_app_state(): return
        if lang_steps.get('translate'):
            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_translate')}..."
            self.update_progress(progress_text)
            logger.info(f"[Chain] Starting translation to {lang_name}...")
            
            translated_text = self.or_api.translate_text(
                original_text, translation_model, translation_params, lang_name,
                custom_prompt_template=lang_config.get("prompt")
            )
            self.update_progress(progress_text, increment_step=True)

            if not translated_text:
                logger.error(f"[Chain] Translation failed for {lang_code}. Skipping dependent steps...")
                return 
            
            text_to_process = translated_text
            lang_output_path = lang_output_paths.get(lang_code)
            if lang_output_path:
                os.makedirs(lang_output_path, exist_ok=True)
                try:
                    with open(os.path.join(lang_output_path, "translation.txt"), 'w', encoding='utf-8') as f: f.write(translated_text)
                    logger.info(f"[Chain] Translation for {lang_name} saved successfully.")
                    self._send_telegram_notification('translate', lang_name, task_num, total_tasks)
                except Exception as e:
                    logger.error(f"[Chain] Failed to save translation: {e}")
            time.sleep(5)
        else:
            text_to_process = original_text
            lang_output_path = lang_output_paths.get(lang_code)
            if lang_output_path:
                translation_path = os.path.join(lang_output_path, "translation.txt")
                if os.path.exists(translation_path):
                    with open(translation_path, 'r', encoding='utf-8') as f:
                        text_to_process = f.read()
                    logger.info(f"Using existing translation file: {translation_path}")
                else:
                    logger.warning(f"Translation step disabled but file not found. Using original text for {lang_code}.")
            else:
                 logger.warning(f"No output path for {lang_code}. Using original text.")

        lang_output_path = lang_output_paths.get(lang_code)
        if not lang_output_path:
            logger.warning(f"Output path not specified for {lang_code}. Skipping file saving steps.")
            return

        if not self._check_app_state(): return
        if lang_steps.get('cta'):
            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_cta')}..."
            self.update_progress(progress_text)
            logger.info(f"[Chain] Starting CTA generation for {lang_name}...")
            
            call_to_action_text = self.or_api.generate_call_to_action(text_to_process, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"])
            self.update_progress(progress_text, increment_step=True)
            if call_to_action_text:
                try:
                    with open(os.path.join(lang_output_path, "call_to_action.txt"), 'w', encoding='utf-8') as f: f.write(call_to_action_text)
                    logger.info(f"[Chain] CTA for {lang_name} saved successfully.")
                    self._send_telegram_notification('cta', lang_name, task_num, total_tasks)
                except Exception as e:
                    logger.error(f"[Chain] Failed to save CTA: {e}")
            else:
                logger.error(f"[Chain] CTA generation failed for {lang_code}.")
            time.sleep(5)

        if not self._check_app_state(): return
        image_prompts = []
        if lang_steps.get('gen_prompts'):
            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_gen_prompts')}..."
            self.update_progress(progress_text)
            logger.info(f"[Chain] Starting image prompt generation for {lang_name}...")

            raw_image_prompts = self.or_api.generate_image_prompts(text_to_process, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"])
            self.update_progress(progress_text, increment_step=True)
            if raw_image_prompts:
                try:
                    with open(os.path.join(lang_output_path, "image_prompts.txt"), 'w', encoding='utf-8') as f: f.write(raw_image_prompts)
                    logger.info(f"[Chain] Original (raw) image prompts for {lang_name} saved.")
                    self._send_telegram_notification('gen_prompts', lang_name, task_num, total_tasks)
                except Exception as e:
                    logger.error(f"[Chain] Failed to save raw image prompts: {e}")
                
                image_prompts = [re.sub(r'^\s*(\d+[\.\)]|[a-zA-Z][\.\)])\s*', '', line).strip() for line in raw_image_prompts.splitlines() if line.strip()]
            else:
                logger.error(f"[Chain] Image prompt generation failed for {lang_name}. Skipping image generation...")
            time.sleep(5)
        elif lang_steps.get('gen_images'): 
            prompts_path = os.path.join(lang_output_path, "image_prompts.txt")
            if os.path.exists(prompts_path):
                with open(prompts_path, 'r', encoding='utf-8') as f:
                    raw_prompts = f.read()
                    image_prompts = [re.sub(r'^\s*(\d+[\.\)]|[a-zA-Z][\.\)])\s*', '', line).strip() for line in raw_prompts.splitlines() if line.strip()]
                logger.info(f"Using existing prompts file: {prompts_path}")

        if not self._check_app_state(): return
        if lang_steps.get('gen_images'):
            if not image_prompts:
                logger.warning(f"No prompts available for image generation ({lang_name}). Step skipped.")
                self.update_progress("", increment_step=True)
            else:
                images_folder = os.path.join(lang_output_path, "images")
                os.makedirs(images_folder, exist_ok=True)
                logger.info(f"[Chain] Starting image generation for {lang_name}...")
                for i, prompt in enumerate(image_prompts):
                    if not self._check_app_state(): return
                    progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_gen_images')} {i+1}/{len(image_prompts)}..."
                    self.update_progress(progress_text)
                    
                    image_path = os.path.join(images_folder, f"image_{i+1:03d}.jpg")
                    if not self.poll_api.generate_image(prompt, image_path):
                        logger.error(f"[Chain] Failed to generate image {i+1} for {lang_name}.")
                self.update_progress("", increment_step=True)
                logger.info(f"[Chain] Image generation for {lang_name} finished.")
                self._send_telegram_notification('gen_images', lang_name, task_num, total_tasks)
                time.sleep(5)
        
        if not self._check_app_state(): return
        audio_file_path = os.path.join(lang_output_path, "audio.mp3")
        if lang_steps.get('audio'):
            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_audio')}..."
            self.update_progress(progress_text)
            logger.info(f"[Chain] Starting audio generation for {lang_name}...")

            tts_service = lang_config.get("tts_service", "elevenlabs")
            
            if tts_service == "elevenlabs":
                logger.info("[Chain] Using ElevenLabs for TTS.")
                task_id = self.el_api.create_audio_task(text_to_process, lang_config.get("elevenlabs_template_uuid"))
                new_balance = self.el_api.balance
                if new_balance is not None:
                    self._update_elevenlabs_balance_labels(new_balance)
                if task_id and task_id != "INSUFFICIENT_BALANCE":
                    logger.info(f"[Chain] ElevenLabs audio task created: {task_id}. Waiting for result...")
                    if self.wait_for_elevenlabs_task(task_id, audio_file_path):
                        logger.info(f"[Chain] Audio for {lang_name} successfully saved.")
                        self._send_telegram_notification('audio', lang_name, task_num, total_tasks)
                    else:
                        logger.error(f"[Chain] Failed to get audio for task {task_id}.")
                else:
                    logger.error(f"[Chain] Failed to create ElevenLabs audio task (Reason: {task_id}).")

            elif tts_service == "voicemaker":
                logger.info("[Chain] Using Voicemaker for TTS.")
                voicemaker_limit = self.config.get("voicemaker", {}).get("char_limit", 9900)
                if len(text_to_process) > voicemaker_limit:
                    logger.info(f"Text is too long for Voicemaker ({len(text_to_process)} chars). Splitting into chunks.")
                    text_chunks = chunk_text_voicemaker(text_to_process, voicemaker_limit)
                    audio_chunks = []
                    temp_audio_dir = os.path.join(lang_output_path, "temp_audio_chunks")
                    os.makedirs(temp_audio_dir, exist_ok=True)
                    
                    try:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=len(text_chunks)) as executor:
                            future_to_index = {
                                executor.submit(
                                    self.vm_api.generate_audio,
                                    chunk, lang_config.get("voicemaker_voice_id"), lang_config.get("voicemaker_engine"),
                                    lang_code, os.path.join(temp_audio_dir, f"chunk_{i}.mp3")
                                ): i for i, chunk in enumerate(text_chunks)
                            }
                            
                            results = [None] * len(text_chunks)
                            for future in concurrent.futures.as_completed(future_to_index):
                                index = future_to_index[future]
                                if future.result():
                                    results[index] = os.path.join(temp_audio_dir, f"chunk_{index}.mp3")
                        
                        audio_chunks = [r for r in results if r is not None and os.path.exists(r)]
                        if len(audio_chunks) == len(text_chunks):
                            if concatenate_audio_files(audio_chunks, audio_file_path):
                                logger.info(f"[Chain] Voicemaker audio for {lang_name} successfully chunked, generated and merged.")
                                self._send_telegram_notification('audio', lang_name, task_num, total_tasks)
                            else:
                                logger.error(f"[Chain] Failed to merge Voicemaker audio chunks for {lang_name}.")
                        else:
                            logger.error(f"[Chain] Failed to generate all Voicemaker audio chunks. Got {len(audio_chunks)} of {len(text_chunks)}.")

                    finally:
                        if os.path.exists(temp_audio_dir):
                            shutil.rmtree(temp_audio_dir)
                else:
                    success, new_balance = self.vm_api.generate_audio(text_to_process, lang_config.get("voicemaker_voice_id"), lang_config.get("voicemaker_engine"), lang_code, audio_file_path)
                if success:
                    logger.info(f"[Chain] Voicemaker audio for {lang_name} successfully saved.")
                    self._send_telegram_notification('audio', lang_name, task_num, total_tasks)
                    if new_balance is not None:
                        vm_text = new_balance if new_balance is not None else 'N/A'
                        self.root.after(0, lambda: self.settings_vm_balance_label.config(text=f"{self._t('balance_label')}: {vm_text}"))
                        self.root.after(0, lambda: self.chain_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
                        self.root.after(0, lambda: self.rewrite_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
                else:
                    logger.error(f"[Chain] Failed to generate Voicemaker audio for {lang_name}.")

            self.update_progress(progress_text, increment_step=True)
            time.sleep(5)

        if not self._check_app_state(): return
        subs_file_path = os.path.join(lang_output_path, "subtitles.ass")
        if lang_steps.get('create_subtitles'):
            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_create_subtitles')}..."
            self.update_progress(progress_text)
            logger.info(f"[Chain] Starting subtitle creation for {lang_name}...")
            if os.path.exists(audio_file_path):
                if self.montage_api.create_subtitles(audio_file_path, subs_file_path):
                    logger.info(f"[Chain] Subtitles for {lang_name} created successfully.")
                    self._send_telegram_notification('create_subtitles', lang_name, task_num, total_tasks)
                else:
                    logger.error(f"[Chain] Failed to create subtitles for {lang_name}.")
            else:
                logger.error(f"[Chain] Audio file not found for subtitle creation: {audio_file_path}")
            self.update_progress(progress_text, increment_step=True)

        if not self._check_app_state(): return
        video_file_path = os.path.join(lang_output_path, f"video_{lang_code}.mp4")
        if lang_steps.get('create_video'):
            progress_text = f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_create_video')}..."
            self.update_progress(progress_text)
            logger.info(f"[Chain] Starting video creation for {lang_name}...")
            images_folder = os.path.join(lang_output_path, "images")
            
            audio_exists = os.path.exists(audio_file_path)
            subs_exist = os.path.exists(subs_file_path)
            images_exist = os.path.exists(images_folder) and any(f.lower().endswith(('.png', '.jpg', '.jpeg')) for f in os.listdir(images_folder))

            if audio_exists and subs_exist and images_exist:
                image_files = sorted([os.path.join(images_folder, f) for f in os.listdir(images_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                if self.montage_api.create_video(image_files, audio_file_path, subs_file_path, video_file_path):
                    logger.info(f"[Chain] Video for {lang_name} created successfully.")
                    self._send_telegram_notification('create_video', lang_name, task_num, total_tasks)
                else:
                    logger.error(f"[Chain] Failed to assemble video for {lang_name}.")
            else:
                missing_files = []
                if not audio_exists: missing_files.append("audio")
                if not subs_exist: missing_files.append("subtitles")
                if not images_exist: missing_files.append("images folder")
                logger.error(f"[Chain] Missing files for video assembly: {', '.join(missing_files)}.")
            self.update_progress(progress_text, increment_step=True)

    def send_telegram_error_notification(self, task_name, lang_code, step, error_details):
        """Негайно відправляє сповіщення про помилку."""
        message = (
            f"❌ *Виникла помилка під час виконання\\!* ❌\n\n"
            f"*Завдання:* {self._escape_markdown(task_name)}\n"
            f"*Мова:* {self._escape_markdown(lang_code.upper())}\n"
            f"*Етап:* {self._escape_markdown(step)}\n"
            f"*Помилка:* {self._escape_markdown(error_details)}"
        )
        self.tg_api.send_message_in_thread(message)

    def send_task_completion_report(self, task_config, single_lang_code=None):
        """Формує та відправляє фінальний звіт по завершенню всього завдання або однієї мови."""
        task_name = self._escape_markdown(task_config.get('task_name', 'Невідоме завдання'))
        
        langs_to_report = [single_lang_code] if single_lang_code else task_config['selected_langs']
        
        # Визначаємо заголовок
        if single_lang_code:
            escaped_lang_code = self._escape_markdown(single_lang_code.upper())
            report_lines = [f"✅ *Завдання \"{task_name}\" для мови {escaped_lang_code} завершено\\!* ✅\n"]
        else:
            report_lines = [f"✅ *Завдання \"{task_name}\" повністю завершено\\!* ✅\n"]

        task_key_prefix = f"{task_config['task_index']}_"

        for lang_code in langs_to_report:
            task_key = task_key_prefix + lang_code
            status = self.task_completion_status.get(task_key)
            if not status: continue

            report_lines.append(self._escape_markdown(f"---"))
            lang_flags = {"it": "🇮🇹", "ro": "🇷🇴", "ua": "🇺🇦", "en": "🇬🇧", "pl": "🇵🇱", "de": "🇩🇪", "fr": "🇫🇷", "es": "🇪🇸"}
            flag = lang_flags.get(lang_code.lower(), "")
            escaped_lang_code = self._escape_markdown(lang_code.upper())
            report_lines.append(f"{flag} *Мова: {escaped_lang_code}*")
            report_lines.append(self._escape_markdown(f"---"))

            # Проходимо по ключах та значеннях правильно
            for step_name, result_icon in status['steps'].items():
                escaped_step_name = self._escape_markdown(step_name)
                
                # Спеціальна логіка для кроку генерації зображень
                if step_name == self._t('step_name_gen_images'):
                    images_generated = status.get("images_generated", 0)
                    total_images = status.get("total_images", 0)
                    count_text = self._escape_markdown(f"({images_generated}/{total_images} шт.)")
                    
                    # Визначаємо іконку на основі реальних даних, а не попередньо встановленої
                    current_icon = result_icon
                    if total_images > 0: # Якщо зображення планувались
                        if images_generated == total_images:
                            current_icon = "✅"
                        elif images_generated > 0:
                            current_icon = "⚠️" # Частково виконано
                        else:
                            current_icon = "❌"
                    
                    # Якщо крок був пропущений (total_images == 0), іконка залишиться "⚪️"
                    if current_icon == "❌":
                        report_lines.append(f"• {current_icon} ~{escaped_step_name}~ *{count_text}*")
                    else:
                        report_lines.append(f"• {current_icon} {escaped_step_name} *{count_text}*")
                
                elif result_icon == "❌":
                    report_lines.append(f"• {result_icon} ~{escaped_step_name}~")
                elif result_icon == "⚪️":
                     skipped_text = self._escape_markdown("(пропущено)")
                     report_lines.append(f"• {result_icon} {escaped_step_name} *{skipped_text}*")
                else:
                    report_lines.append(f"• {result_icon} {escaped_step_name}")
        
        self.tg_api.send_message_in_thread("\n".join(report_lines))

    def wait_for_elevenlabs_task(self, task_id, output_path):
        max_wait_time, wait_interval, waited_time = 600, 15, 0
        
        while waited_time < max_wait_time:
            if not self._check_app_state(): return False

            status = self.el_api.check_task_status(task_id)
            logger.info(f"[Chain] Audio task {task_id} status: {status}")

            if status == 'ending':
                logger.info(f"Task {task_id} is ready. Attempting to download.")
                time.sleep(2)
                return self.el_api.download_audio(task_id, output_path)
            
            if status in ['error', 'error_handled']:
                logger.error(f"Task {task_id} failed with status '{status}'.")
                return False

            if status in ['waiting', 'processing']:
                pass
            
            elif status == 'ending_processed':
                 logger.warning(f"Task {task_id} has status 'ending_processed', which means the audio was already downloaded and possibly deleted.")
                 return False

            elif status is None:
                logger.error(f"Failed to get status for task {task_id}. Aborting wait.")
                return False

            # Робимо очікування переривчастим
            for _ in range(wait_interval):
                if not self._check_app_state(): return False
                time.sleep(1)
            waited_time += wait_interval

        logger.warning(f"[Chain] Timed out waiting for audio task {task_id}.")
        return False
        
    def update_progress(self, text, increment_step=False):
        if increment_step:
            self.current_queue_step += 1
        
        self.root.after(0, lambda: self.progress_label.config(text=text))
        progress_percent = (self.current_queue_step / self.total_queue_steps) * 100 if self.total_queue_steps > 0 else 0
        self.root.after(0, lambda: self.progress_var.set(progress_percent))
    
    def update_progress_for_montage(self, message):
        self.root.after(0, lambda: self.progress_label.config(text=message))
        logger.info(f"[Montage Progress] {message}")
        
    def _create_scrollable_tab(self, parent_tab):
        theme_name = self.root.style.theme_use()
        if theme_name == 'cyborg': canvas_bg = "#060606"
        elif theme_name == 'darkly': canvas_bg = "#222222"
        else: canvas_bg = "#ffffff"

        canvas = tk.Canvas(parent_tab, highlightthickness=0, bg=canvas_bg)
        scrollbar = ttk.Scrollbar(parent_tab, orient="vertical", command=canvas.yview)
        self.dynamic_scrollbars.append(scrollbar)

        scrollable_frame = ttk.Frame(canvas)
        frame_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def configure_canvas(event):
            # ВИПРАВЛЕНО: Прибираємо умову і завжди розтягуємо внутрішній фрейм
            # на всю ширину канвасу. Це робить поведінку стабільною.
            canvas.itemconfig(frame_id, width=event.width)
            canvas.configure(scrollregion=canvas.bbox("all"))

        def configure_scrollable_frame(event):
            # Оновлюємо скролрегіон, коли змінюється розмір контенту
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind('<Configure>', configure_canvas)
        scrollable_frame.bind('<Configure>', configure_scrollable_frame)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.scrollable_canvases.append(canvas)
        return canvas, scrollable_frame

    def _create_scrolled_text(self, parent, **kwargs):
        container = ttk.Frame(parent)
        scrollbar = ttk.Scrollbar(container, orient="vertical")
        self.dynamic_scrollbars.append(scrollbar)
        text_widget = tk.Text(container, yscrollcommand=scrollbar.set, **kwargs)
        scrollbar.config(command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.pack(side="left", fill="both", expand=True)
        return text_widget, container

    # --- МЕТОДИ, ПОВЕРНУТІ ПІСЛЯ РЕФАКТОРИНГУ ---

    def test_openrouter_connection(self):
        api_key = self.or_api_key_var.get()
        temp_config = self.config.copy()
        temp_config["openrouter"]["api_key"] = api_key
        temp_api = OpenRouterAPI(temp_config)
        success, message = temp_api.test_connection()
        if success:
            messagebox.showinfo(self._t('test_connection_title_or'), message)
        else:
            messagebox.showerror(self._t('test_connection_title_or'), message)

    def test_pollinations_connection(self):
        token = self.poll_token_var.get()
        model = self.poll_model_var.get()
        temp_config = self.config.copy()
        temp_config["pollinations"]["token"] = token
        temp_config["pollinations"]["model"] = model
        temp_api = PollinationsAPI(temp_config, self)
        success, message = temp_api.test_connection()
        if success:
            messagebox.showinfo(self._t('test_connection_title_poll'), message)
        else:
            messagebox.showerror(self._t('test_connection_title_poll'), message)

    def test_elevenlabs_connection(self):
        api_key = self.el_api_key_var.get()
        temp_config = self.config.copy()
        temp_config["elevenlabs"]["api_key"] = api_key
        temp_api = ElevenLabsAPI(temp_config)
        success, message = temp_api.test_connection()
        if success:
            self.el_api = temp_api
            balance_text = self.el_api.balance if self.el_api.balance is not None else 'N/A'
            self.settings_el_balance_label.config(text=f"{self._t('balance_label')}: {balance_text}")
            messagebox.showinfo(self._t('test_connection_title_el'), message)
        else:
            messagebox.showerror(self._t('test_connection_title_el'), message)

    def test_voicemaker_connection(self):
        api_key = self.vm_api_key_var.get()
        temp_config = {"voicemaker": {"api_key": api_key}}
        temp_api = VoiceMakerAPI(temp_config)
        balance = temp_api.get_balance()
        if balance is not None:
            if 'voicemaker' not in self.config: self.config['voicemaker'] = {}
            self.config['voicemaker']['last_known_balance'] = balance
            save_config(self.config)
            vm_text = balance
            self.root.after(0, lambda: self.settings_vm_balance_label.config(text=f"{self._t('balance_label')}: {vm_text}"))
            self.root.after(0, lambda: self.chain_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
            self.root.after(0, lambda: self.rewrite_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
            message = f"З'єднання з Voicemaker успішне.\nЗалишилось символів: {balance}"
            messagebox.showinfo(self._t('test_connection_title_vm'), message)
        else:
            message = "Не вдалося перевірити з'єднання або отримати баланс Voicemaker."
            messagebox.showerror(self._t('test_connection_title_vm'), message)

    def test_recraft_connection(self):
        api_key = self.recraft_api_key_var.get()
        temp_config = {"recraft": {"api_key": api_key}}
        temp_api = RecraftAPI(temp_config)
        success, message = temp_api.test_connection()
        if success:
            messagebox.showinfo(self._t('test_connection_title_recraft'), message)
        else:
            messagebox.showerror(self._t('test_connection_title_recraft'), message)

    def test_telegram_connection(self):
        api_key = self.tg_api_key_var.get()
        temp_config = {"telegram": {"api_key": api_key}}
        temp_api = TelegramAPI(temp_config)
        success, message = temp_api.test_connection()
        if success:
            messagebox.showinfo(self._t('test_connection_title_tg'), message)
        else:
            messagebox.showerror(self._t('test_connection_title_tg'), message)

    def test_speechify_connection(self):
        api_key = self.speechify_api_key_var.get()
        temp_config = {"speechify": {"api_key": api_key}}
        temp_api = SpeechifyAPI(temp_config)
        success, message = temp_api.test_connection()
        if success:
            messagebox.showinfo(self._t('test_connection_title_speechify'), message)
        else:
            messagebox.showerror(self._t('test_connection_title_speechify'), message)

    def _update_recraft_substyles(self, event=None):
        selected_model = self.recraft_model_var.get()
        selected_style = self.recraft_style_var.get()
        substyles = RECRAFT_SUBSTYLES.get(selected_model, {}).get(selected_style, [])
        current_substyle = self.recraft_substyle_var.get()
        self.recraft_substyle_combo['values'] = substyles
        if not substyles:
            self.recraft_substyle_var.set("")
            self.recraft_substyle_combo.config(state="disabled")
        else:
            self.recraft_substyle_combo.config(state="readonly")
            if current_substyle not in substyles:
                self.recraft_substyle_var.set("")

    def save_settings(self):
        if 'parallel_processing' not in self.config: self.config['parallel_processing'] = {}
        self.config['parallel_processing']['enabled'] = self.parallel_enabled_var.get()
        self.config['parallel_processing']['num_chunks'] = self.parallel_num_chunks_var.get()
        self.config['parallel_processing']['keep_temp_files'] = self.parallel_keep_temps_var.get()
        self.config["openrouter"]["api_key"] = self.or_api_key_var.get()
        self.config["openrouter"]["translation_model"] = self.or_trans_model_var.get()
        self.config["openrouter"]["prompt_model"] = self.or_prompt_model_var.get()
        self.config["openrouter"]["cta_model"] = self.or_cta_model_var.get()
        self.config["openrouter"]["rewrite_model"] = self.or_rewrite_model_var.get()
        self.config["openrouter"]["saved_models"] = list(self.or_models_listbox.get(0, tk.END))
        self.config["openrouter"]["translation_params"]["temperature"] = self.trans_temp_var.get()
        self.config["openrouter"]["translation_params"]["max_tokens"] = self.trans_tokens_var.get()
        self.config["openrouter"]["rewrite_params"]["temperature"] = self.rewrite_temp_var.get()
        self.config["openrouter"]["rewrite_params"]["max_tokens"] = self.rewrite_tokens_var.get()
        self.config["openrouter"]["prompt_params"]["temperature"] = self.prompt_gen_temp_var.get()
        self.config["openrouter"]["prompt_params"]["max_tokens"] = self.prompt_gen_tokens_var.get()
        self.config["openrouter"]["cta_params"]["temperature"] = self.cta_temp_var.get()
        self.config["openrouter"]["cta_params"]["max_tokens"] = self.cta_tokens_var.get()
        self.config["default_prompts"]["image_prompt_generation"] = self.prompt_gen_prompt_text.get("1.0", tk.END).strip()
        self.config["default_prompts"]["call_to_action"] = self.cta_prompt_text.get("1.0", tk.END).strip()
        self.config["pollinations"]["token"] = self.poll_token_var.get()
        self.config["pollinations"]["model"] = self.poll_model_var.get()
        self.config["pollinations"]["width"] = self.poll_width_var.get()
        self.config["pollinations"]["height"] = self.poll_height_var.get()
        self.config["pollinations"]["timeout"] = self.poll_timeout_var.get()
        self.config['ui_settings']['image_generation_api'] = self.image_api_var.get()
        self.config["pollinations"]["remove_logo"] = self.poll_remove_logo_var.get()
        if 'recraft' not in self.config: self.config['recraft'] = {}
        self.config['recraft']['api_key'] = self.recraft_api_key_var.get()
        self.config['recraft']['model'] = self.recraft_model_var.get()
        self.config['recraft']['style'] = self.recraft_style_var.get()
        self.config['recraft']['substyle'] = self.recraft_substyle_var.get()
        self.config['recraft']['size'] = self.recraft_size_var.get().split(' ')[0]
        self.config['recraft']['negative_prompt'] = self.recraft_negative_prompt_var.get()
        self.config["elevenlabs"]["api_key"] = self.el_api_key_var.get()
        if 'voicemaker' not in self.config: self.config['voicemaker'] = {}
        self.config['voicemaker']['api_key'] = self.vm_api_key_var.get()
        self.config['voicemaker']['char_limit'] = self.vm_char_limit_var.get()

        # --- НОВИЙ БЛОК ЗБЕРЕЖЕННЯ SPEECHIFY ---
        if 'speechify' not in self.config: self.config['speechify'] = {}
        self.config['speechify']['api_key'] = self.speechify_api_key_var.get()
        # --- КІНЕЦЬ НОВОГО БЛОКУ ---
        if 'output_settings' not in self.config: self.config['output_settings'] = {}
        self.config['output_settings']['use_default_dir'] = self.output_use_default_var.get()
        self.config['output_settings']['default_dir'] = self.output_default_dir_var.get()
        self.config['output_settings']['rewrite_default_dir'] = self.output_rewrite_default_dir_var.get()
        if 'rewrite_settings' not in self.config: self.config['rewrite_settings'] = {}
        self.config['rewrite_settings']['download_threads'] = self.rewrite_download_threads_var.get()
        if 'telegram' not in self.config: self.config['telegram'] = {}
        self.config['telegram']['enabled'] = self.tg_enabled_var.get()
        self.config['telegram']['api_key'] = self.tg_api_key_var.get()
        self.config['telegram']['chat_id'] = self.tg_chat_id_var.get()
        # Зберігаємо нове налаштування режиму звіту
        display_value = self.tg_report_timing_var.get()
        # Знаходимо ключ ('per_task' або 'per_language') за відображуваним значенням
        internal_value = next((k for k, v in self.report_timing_display_map.items() if v == display_value), 'per_task')
        self.config['telegram']['report_timing'] = internal_value
        # Видаляємо збереження старих налаштувань notify_on
        if 'notify_on' in self.config['telegram']:
            del self.config['telegram']['notify_on']
        if 'montage' not in self.config: self.config['montage'] = {}
        self.config['montage']['ffmpeg_path'] = self.montage_ffmpeg_path_var.get()
        self.config['montage']['whisper_model'] = self.montage_whisper_model_var.get()
        self.config['montage']['motion_enabled'] = self.montage_motion_enabled_var.get()
        self.config['montage']['motion_type'] = self.montage_motion_type_var.get()
        self.config['montage']['motion_intensity'] = self.montage_motion_intensity_var.get()
        self.config['montage']['zoom_enabled'] = self.montage_zoom_enabled_var.get()
        self.config['montage']['zoom_intensity'] = self.montage_zoom_intensity_var.get()
        self.config['montage']['zoom_speed'] = self.montage_zoom_speed_var.get()
        self.config['montage']['transition_effect'] = self.montage_transition_var.get()
        self.config['montage']['font_size'] = self.montage_font_size_var.get()
        self.config['montage']['output_framerate'] = self.montage_output_framerate_var.get()
        if 'codec' not in self.config['montage']: self.config['montage']['codec'] = {}
        self.config['montage']['codec']['video_codec'] = self.codec_video_codec_var.get()
        self.config['montage']['codec']['x264_crf'] = self.codec_x264_crf_var.get()
        self.config['montage']['codec']['nvenc_cq'] = self.codec_nvenc_cq_var.get()
        self.config['montage']['codec']['amf_usage'] = self.codec_amf_usage_var.get()
        self.config['montage']['codec']['amf_quality'] = self.codec_amf_quality_var.get()
        self.config['montage']['codec']['amf_rc'] = self.codec_amf_rc_var.get()
        self.config['montage']['codec']['amf_bitrate'] = self.codec_amf_bitrate_var.get()
        self.config['montage']['codec']['vt_bitrate'] = self.codec_vt_bitrate_var.get()
        if "rewrite_prompt_templates" not in self.config:
            self.config["rewrite_prompt_templates"] = {}
        current_templates = list(self.rewrite_templates_listbox.get(0, tk.END))
        for template_name in list(self.config["rewrite_prompt_templates"].keys()):
            if template_name not in current_templates:
                del self.config["rewrite_prompt_templates"][template_name]
        for template_name in current_templates:
            if template_name not in self.config["rewrite_prompt_templates"]:
                 self.config["rewrite_prompt_templates"][template_name] = {}
        if 'ui_settings' not in self.config: self.config['ui_settings'] = {}
        self.config['ui_settings']['image_generation_api'] = self.image_api_var.get()
        
        selected_display_name = self.theme_var.get()
        self.config['ui_settings']['theme'] = self.theme_map_to_internal.get(selected_display_name, "darkly")
        
        self.config['ui_settings']['image_control_enabled'] = self.image_control_var.get()
        self.config['ui_settings']['auto_switch_service_on_fail'] = self.auto_switch_var.get()
        self.config['ui_settings']['auto_switch_retry_limit'] = self.auto_switch_retries_var.get()

        save_config(self.config)
        self.or_api = OpenRouterAPI(self.config)
        self.poll_api = PollinationsAPI(self.config, self)
        self.recraft_api = RecraftAPI(self.config)
        self.el_api = ElevenLabsAPI(self.config)
        self.vm_api = VoiceMakerAPI(self.config)
        self.tg_api = TelegramAPI(self.config)
        self.speechify_api = SpeechifyAPI(self.config)
        self.montage_api = MontageAPI(self.config, self, self.update_progress_for_montage)
        setup_ffmpeg_path(self.config)
        if self.selected_lang_code:
            self.update_language_voice_dropdowns(self.selected_lang_code)
        self.update_path_widgets_state()
        messagebox.showinfo(self._t('saved_title'), self._t('info_settings_saved'))

    def update_elevenlabs_info(self, update_templates=True):
        balance = self.el_api.update_balance()
        balance_text = balance if balance is not None else 'N/A'
        
        self.root.after(0, lambda: self.settings_el_balance_label.config(text=f"{self._t('balance_label')}: {balance_text}"))
        self.root.after(0, lambda: self.chain_el_balance_label.config(text=f"{self._t('elevenlabs_balance_label')}: {balance_text}"))
        self.root.after(0, lambda: self.rewrite_el_balance_label.config(text=f"{self._t('elevenlabs_balance_label')}: {balance_text}"))
        
        templates_len = "N/A"
        if update_templates:
            templates = self.el_api.update_templates()
            if templates:
                templates_len = len(templates)
        elif self.el_api.templates:
            templates_len = len(self.el_api.templates)

    def update_api_balances(self):
        def update_thread():
            self.update_elevenlabs_info(update_templates=False)
            
            recraft_balance = self.recraft_api.get_balance()
            recraft_text = recraft_balance if recraft_balance is not None else 'N/A'
            self.root.after(0, lambda: self.settings_recraft_balance_label.config(text=f"{self._t('balance_label')}: {recraft_text}"))
            self.root.after(0, lambda: self.chain_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
            self.root.after(0, lambda: self.rewrite_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
            logger.info(f"Recraft balance updated: {recraft_balance}")

            vm_balance = self.vm_api.get_balance()
            if vm_balance is not None:
                if 'voicemaker' not in self.config: self.config['voicemaker'] = {}
                self.config['voicemaker']['last_known_balance'] = vm_balance
                save_config(self.config)
            
            vm_text = vm_balance if vm_balance is not None else 'N/A'
            self.root.after(0, lambda: self.settings_vm_balance_label.config(text=f"{self._t('balance_label')}: {vm_text}"))
            self.root.after(0, lambda: self.chain_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
            self.root.after(0, lambda: self.rewrite_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
            logger.info(f"Voicemaker balance updated: {vm_balance}")

        threading.Thread(target=update_thread, daemon=True).start()

    def update_startup_balances(self):
        def update_thread():
            self.update_elevenlabs_info(update_templates=True)
            recraft_balance = self.recraft_api.get_balance()
            recraft_text = recraft_balance if recraft_balance is not None else 'N/A'
            self.root.after(0, lambda: self.settings_recraft_balance_label.config(text=f"{self._t('balance_label')}: {recraft_text}"))
            self.root.after(0, lambda: self.chain_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
            self.root.after(0, lambda: self.rewrite_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
        
        threading.Thread(target=update_thread, daemon=True).start()

    def update_char_count(self, event=None):
        text = self.input_text.get("1.0", tk.END)
        char_count = len(text) - 1
        self.char_count_label.config(text=f"{self._t('chars_label')}: {char_count}")

    def toggle_pause_resume(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            self.pause_resume_button.config(text=self._t('resume_button'))
            self.update_progress(self._t('status_pausing'))
            logger.info("Pause requested. The process will pause after the current step.")
        else:
            self.pause_resume_button.config(text=self._t('pause_button'))
            self.update_progress(self._t('status_resuming'))
            self.pause_event.set()
            logger.info("Resuming process.")

    def edit_task_name(self, event):
        item_id = self.queue_tree.identify_row(event.y)
        if not item_id or not item_id.startswith("task_"):
            return 
        x, y, width, height = self.queue_tree.bbox(item_id, column="#0")
        entry_var = tk.StringVar(value=self.queue_tree.item(item_id, "text"))
        entry = ttk.Entry(self.queue_tree, textvariable=entry_var)
        add_text_widget_bindings(self, entry)
        
        def on_focus_out(event):
            new_name = entry_var.get()
            if new_name:
                try:
                    task_index = int(item_id.split('_')[1])
                    if 0 <= task_index < len(self.task_queue):
                        self.queue_tree.item(item_id, text=new_name)
                        self.task_queue[task_index]['task_name'] = new_name
                        logger.info(f"Task {task_index + 1} renamed to '{new_name}'")
                    else:
                        logger.warning(f"Task index {task_index} out of range for renaming.")
                except (IndexError, ValueError) as e:
                    logger.error(f"Could not update task name for item {item_id}: {e}")
            entry.destroy()
            
        def on_return(event):
            on_focus_out(event)
            
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        entry.bind("<FocusOut>", on_focus_out)
        entry.bind("<Return>", on_return)

    def clear_queue(self):
        if messagebox.askyesno(self._t('confirm_title'), self._t('confirm_clear_queue')):
            self.task_queue.clear()
            self.update_queue_display()
            logger.info("Queue cleared.")

    def _preview_montage(self):
        """Створює та відкриває коротке відео для попереднього перегляду налаштувань монтажу."""
        
        def preview_thread():
            try:
                self.root.after(0, lambda: self.preview_button.config(state="disabled", text=self._t('generating_label', default="Генерація..."))) # Припускаємо, що ключ 'generating_label' буде додано
                
                preview_folder = os.path.join(APP_BASE_PATH, "preview")
                if not os.path.exists(preview_folder):
                    os.makedirs(preview_folder)
                    messagebox.showinfo(self._t('preview_folder_title'), self._t('preview_folder_message'))
                    return

                image_paths = [os.path.join(preview_folder, f"image_{i}.jpg") for i in range(1, 4)]
                audio_path = os.path.join(preview_folder, "audio.mp3")
                subs_path = os.path.join(preview_folder, "subtitles.ass")
                
                # --- НОВА ЛОГІКА: Унікальна назва для кожного прев'ю ---
                preview_output_path = os.path.join(preview_folder, f"preview_video_{int(time.time())}.mp4")

                missing_files = [p for p in image_paths + [audio_path, subs_path] if not os.path.exists(p)]
                if missing_files:
                    messagebox.showerror(self._t('error_title'), self._t('preview_files_not_found_error', files="\n".join(os.path.basename(p) for p in missing_files)))
                    return

                current_montage_config = {
                    'montage': {
                        'motion_enabled': self.montage_motion_enabled_var.get(),
                        'motion_type': self.montage_motion_type_var.get(),
                        'motion_intensity': self.montage_motion_intensity_var.get(),
                        'zoom_enabled': self.montage_zoom_enabled_var.get(),
                        'zoom_intensity': self.montage_zoom_intensity_var.get(),
                        'zoom_speed': self.montage_zoom_speed_var.get(),
                        'transition_effect': self.montage_transition_var.get(),
                        'font_size': self.montage_font_size_var.get(),
                        'output_framerate': self.montage_output_framerate_var.get(),
                        'codec': {
                            'video_codec': self.codec_video_codec_var.get(),
                            'x264_crf': self.codec_x264_crf_var.get(),
                            'nvenc_cq': self.codec_nvenc_cq_var.get(),
                            'amf_usage': self.codec_amf_usage_var.get(),
                            'amf_quality': self.codec_amf_quality_var.get(),
                            'amf_rc': self.codec_amf_rc_var.get(),
                            'amf_bitrate': self.codec_amf_bitrate_var.get(),
                            'vt_bitrate': self.codec_vt_bitrate_var.get(),
                        }
                    }
                }
                
                temp_montage_api = MontageAPI(current_montage_config, self, self.update_progress_for_montage)
                
                success = temp_montage_api.create_video(image_paths, audio_path, subs_path, preview_output_path)
                
                if success:
                    logger.info("Preview video generated successfully. Opening...")
                    if sys.platform == "win32":
                        os.startfile(preview_output_path)
                    elif sys.platform == "darwin":
                        subprocess.run(["open", preview_output_path])
                    else:
                        subprocess.run(["xdg-open", preview_output_path])
                else:
                    messagebox.showerror(self._t('error_title'), self._t('preview_video_creation_error'))
            
            finally:
                # --- ВИДАЛЕНО ЛОГІКУ ВИДАЛЕННЯ ---
                # Тепер відео залишається у папці
                self.root.after(0, lambda: self.preview_button.config(state="normal", text=self._t('preview_button_text')))

        threading.Thread(target=preview_thread, daemon=True).start()

    def continue_processing_after_image_control(self):
        logger.info("Continue button pressed. Resuming final video processing. Gallery remains visible.")
        
        # Більше не ховаємо галерею. Вона залишиться видимою.
        # Код для приховування видалено.
        
        # Ховаємо лише саму кнопку "Продовжити", щоб уникнути повторних натискань
        if self.continue_button and self.continue_button.winfo_ismapped():
            self.continue_button.pack_forget()
            
        self.image_control_active.set() # Знімає блокування з потоку обробки

    def _delete_image(self, image_path):
        """Видаляє зображення з диску та з галереї."""
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
                logger.info(f"Image deleted: {image_path}")
                if image_path in self.image_widgets:
                    self.image_widgets[image_path].destroy()
                    del self.image_widgets[image_path]
        except Exception as e:
            logger.error(f"Failed to delete image {image_path}: {e}")
            messagebox.showerror("Помилка", f"Не вдалося видалити зображення:\n{e}")
    
    def _edit_prompt_and_regenerate(self, image_path):
        original_prompt = self.image_prompts_map.get(image_path, "")
        
        dialog = AdvancedRegenerateDialog(self.root, self._t('regenerate_image_title'), self, initial_prompt=original_prompt)
        result = dialog.result

        if result:
            new_prompt = result['prompt']
            self.image_prompts_map[image_path] = new_prompt
            
            # Створюємо словник з параметрами для передачі
            regeneration_params = {
                'new_prompt': new_prompt,
                'service_override': result['service']
            }
            if result['service'] == 'pollinations':
                regeneration_params['model_override'] = result['model']
            elif result['service'] == 'recraft':
                regeneration_params['model_override'] = result['model']
                regeneration_params['style_override'] = result['style']
            
            self._regenerate_image(image_path, **regeneration_params)

    def _regenerate_image(self, image_path, new_prompt=None, use_random_seed=False, service_override=None, **kwargs):
        """Перегенеровує одне зображення."""
        prompt_to_use = new_prompt if new_prompt else self.image_prompts_map.get(image_path)
        if not prompt_to_use:
            logger.error(f"No prompt found for image {image_path}. Cannot regenerate.")
            return

        def regeneration_thread():
            self.root.after(0, lambda: self._update_gallery_image(image_path, is_loading=True))
            
            api_params = {}
            active_api_name = service_override if service_override else self.active_image_api
            
            # --- КЛЮЧОВА ЗМІНА ---
            # Якщо сервіс - Pollinations, ЗАВЖДИ додаємо випадковий seed для уникнення кешування
            if active_api_name == "pollinations":
                random_seed = random.randint(0, 2**32 - 1)
                api_params['seed'] = random_seed
                logger.info(f"Regenerating image {os.path.basename(image_path)} with new seed: {random_seed}")
            elif use_random_seed: # Для інших сервісів (якщо знадобиться) seed додається лише по кнопці "🔄"
                random_seed = random.randint(0, 2**32 - 1)
                api_params['seed'] = random_seed
                logger.info(f"Regenerating image {os.path.basename(image_path)} with new seed: {random_seed}")

            logger.info(f"[{active_api_name.capitalize()}] Regenerating image for prompt: {prompt_to_use}")
            
            success = False
            
            if active_api_name == "pollinations":
                # Перевіряємо, чи передали нову модель з діалогового вікна
                if 'model_override' in kwargs:
                    api_params['model'] = kwargs['model_override']
                success = self.poll_api.generate_image(prompt_to_use, image_path, **api_params)
            
            elif active_api_name == "recraft":
                temp_recraft_config = self.config.copy()
                if 'recraft' not in temp_recraft_config: temp_recraft_config['recraft'] = {}
                
                if 'model_override' in kwargs:
                    temp_recraft_config['recraft']['model'] = kwargs['model_override']
                if 'style_override' in kwargs:
                    temp_recraft_config['recraft']['style'] = kwargs['style_override']

                temp_recraft_api = RecraftAPI(temp_recraft_config)
                success, _ = temp_recraft_api.generate_image(prompt_to_use, image_path, **api_params)

            if success:
                logger.info(f"Image regenerated successfully: {image_path}")
                self.root.after(0, lambda: self._update_gallery_image(image_path, is_loading=False, is_error=False))
            else:
                logger.error(f"Failed to regenerate image: {image_path}")
                self.root.after(0, lambda: self._update_gallery_image(image_path, is_loading=False, is_error=True))

        threading.Thread(target=regeneration_thread, daemon=True).start()

    def _update_gallery_image(self, image_path, is_loading=False, is_error=False):
        """Оновлює мініатюру зображення в галереї."""
        if image_path not in self.image_widgets:
            return

        frame = self.image_widgets[image_path]
        # Видаляємо стару картинку, індикатор завантаження або помилки
        for widget in frame.winfo_children():
            if isinstance(widget, ttk.Label):
                widget.destroy()

        if is_loading:
            loading_label = ttk.Label(frame, text=self._t('loading_label_text'))
            loading_label.pack(pady=5, side='top', expand=True, fill='both')
        elif is_error:
            error_label = ttk.Label(frame, text=self._t('error_label_text'), bootstyle="danger")
            error_label.pack(pady=5, side='top', expand=True, fill='both')
        else:
            try:
                img = Image.open(image_path)
                img.thumbnail((256, 144))
                photo = ImageTk.PhotoImage(img)
                
                # Зберігаємо посилання на фото, щоб його не видалив збирач сміття
                img_label = ttk.Label(frame, image=photo)
                img_label.image = photo 
                img_label.pack(pady=5, side='top', expand=True, fill='both')
            except Exception as e:
                logger.error(f"Could not reload image {image_path}: {e}")
                error_label = ttk.Label(frame, text=self._t('error_loading_label_text'))
                error_label.pack(pady=5, side='top', expand=True, fill='both')

    def _sequential_image_master(self, processing_data, queue_to_process):
        """Головний потік, що керує послідовною генерацією всіх зображень."""
        logger.info("[Hybrid Mode] Image Master Thread: Starting sequential image generation.")
        for task_key, data in sorted(processing_data.items()):
            if data.get('text_results') and data['task']['steps'][task_key[1]].get('gen_images'):
                self._image_generation_worker(data, task_key, task_key[0] + 1, len(queue_to_process))
        logger.info("[Hybrid Mode] Image Master Thread: All image generation tasks complete.")

    def _audio_subs_pipeline_master(self, processing_data):
        """Керує послідовним конвеєром Аудіо -> Субтитри для кожної мови."""
        logger.info("[Audio/Subs Master] Starting pipeline.")
        num_parallel_chunks = self.config.get('parallel_processing', {}).get('num_chunks', 3)

        for task_key, data in sorted(processing_data.items()):
            if not data.get('text_results'): continue
            
            task_idx_str, lang_code = task_key
            status_key = f"{task_idx_str}_{lang_code}"
            lang_steps = data['task']['steps'][lang_code]
            lang_config = self.config["languages"][lang_code]
            tts_service = lang_config.get("tts_service", "elevenlabs")
            text_to_process = data['text_results']['text_to_process']
            output_path = data['text_results']['output_path']
            
            temp_dir = os.path.join(output_path, "temp_chunks")
            os.makedirs(temp_dir, exist_ok=True)
            data['temp_dir'] = temp_dir
            
            final_audio_chunks = []

            audio_step_name = self._t('step_name_audio')
            if lang_steps.get('audio'):
                voicemaker_limit = self.config.get("voicemaker", {}).get("char_limit", 9900)
                text_chunks = []
                if tts_service == "voicemaker" and len(text_to_process) > voicemaker_limit:
                    text_chunks = chunk_text_voicemaker(text_to_process, voicemaker_limit)
                elif tts_service == "speechify" and len(text_to_process) > SPEECHIFY_CHAR_LIMIT:
                    text_chunks = chunk_text_speechify(text_to_process, SPEECHIFY_CHAR_LIMIT, num_parallel_chunks)
                else:
                    text_chunks = chunk_text(text_to_process, num_parallel_chunks)
                
                if not text_chunks:
                    logger.error(f"Text for {lang_code} is empty after chunking. Skipping.")
                    if status_key in self.task_completion_status and audio_step_name in self.task_completion_status[status_key]['steps']:
                        self.task_completion_status[status_key]['steps'][audio_step_name] = "❌"
                    continue

                self.update_progress(f"{lang_code.upper()}: Генерація {len(text_chunks)} аудіо-шматків...")
                initial_audio_chunks = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                    future_to_chunk = {}
                    for i, chunk in enumerate(text_chunks):
                        future = executor.submit(self._audio_generation_worker, chunk, os.path.join(temp_dir, f"audio_chunk_{i}.mp3"), lang_config, lang_code, i + 1, len(text_chunks))
                        future_to_chunk[future] = i
                        time.sleep(1)
                    
                    results = [None] * len(text_chunks)
                    for future in concurrent.futures.as_completed(future_to_chunk):
                        results[future_to_chunk[future]] = future.result()
                initial_audio_chunks = [r for r in results if r]

                if len(initial_audio_chunks) != len(text_chunks):
                     logger.error(f"Failed to generate all audio chunks for {lang_code}. Skipping subs/video.")
                     if status_key in self.task_completion_status and audio_step_name in self.task_completion_status[status_key]['steps']:
                        self.task_completion_status[status_key]['steps'][audio_step_name] = "❌"
                     continue

                if (tts_service in ["voicemaker", "speechify"]) and len(initial_audio_chunks) > num_parallel_chunks:
                    logger.info(f"Merging {len(initial_audio_chunks)} {tts_service} audio chunks into {num_parallel_chunks} final chunks.")
                    chunk_groups = np.array_split(initial_audio_chunks, num_parallel_chunks)
                    
                    for i, group in enumerate(chunk_groups):
                        if not group.any(): continue
                        merged_output_file = os.path.join(temp_dir, f"merged_chunk_{lang_code}_{i}.mp3")
                        if concatenate_audio_files(list(group), merged_output_file):
                            final_audio_chunks.append(merged_output_file)
                        else:
                             logger.error(f"Failed to merge a group of {tts_service} audio files for {lang_code}.")
                else:
                    final_audio_chunks = initial_audio_chunks
                
                if final_audio_chunks:
                     if status_key in self.task_completion_status and audio_step_name in self.task_completion_status[status_key]['steps']:
                        self.task_completion_status[status_key]['steps'][audio_step_name] = "✅"
                else:
                    logger.error(f"Audio processing resulted in zero final chunks for {lang_code}.")
                    if status_key in self.task_completion_status and audio_step_name in self.task_completion_status[status_key]['steps']:
                        self.task_completion_status[status_key]['steps'][audio_step_name] = "❌"
            else:
                logger.info(f"Audio step disabled for {lang_code}. Searching for existing merged audio chunks...")
                found_chunks = sorted([os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.startswith(f'merged_chunk_{lang_code}_') and f.endswith('.mp3')])
                if found_chunks:
                    logger.info(f"Found {len(found_chunks)} existing merged audio chunks.")
                    final_audio_chunks = found_chunks
                else:
                    logger.warning(f"No merged audio chunks found for {lang_code}. Dependent steps will be skipped.")
            
            if not final_audio_chunks:
                continue

            data['audio_chunks'] = sorted(final_audio_chunks)
            subs_chunk_dir = os.path.join(temp_dir, "subs"); os.makedirs(subs_chunk_dir, exist_ok=True)
            subs_chunk_paths = []
            
            subs_step_name = self._t('step_name_create_subtitles')
            if lang_steps.get('create_subtitles'):
                self.update_progress(f"{lang_code.upper()}: Генерація субтитрів...")
                subs_chunk_paths = self._sequential_subtitle_worker(data['audio_chunks'], subs_chunk_dir)
                
                if len(subs_chunk_paths) == len(data['audio_chunks']):
                    if status_key in self.task_completion_status and subs_step_name in self.task_completion_status[status_key]['steps']:
                        self.task_completion_status[status_key]['steps'][subs_step_name] = "✅"
                else:
                    logger.error(f"Failed to generate all subtitle chunks for {lang_code}.")
                    if status_key in self.task_completion_status and subs_step_name in self.task_completion_status[status_key]['steps']:
                        self.task_completion_status[status_key]['steps'][subs_step_name] = "❌"
                    continue
            else:
                logger.info(f"Subtitles step disabled for {lang_code}. Searching for existing subtitle chunks...")
                found_subs = sorted([os.path.join(subs_chunk_dir, f) for f in os.listdir(subs_chunk_dir) if f.startswith('subs_chunk_') and f.endswith('.ass')])
                if len(found_subs) == len(data['audio_chunks']):
                     logger.info(f"Found {len(found_subs)} existing subtitle chunks.")
                     subs_chunk_paths = found_subs
                else:
                    logger.warning(f"Found {len(found_subs)} subtitle chunks, but expected {len(data['audio_chunks'])}. Video montage might fail.")
                    subs_chunk_paths = found_subs 

            data['subs_chunks'] = sorted(subs_chunk_paths)

        logger.info("[Audio/Subs Master] Pipeline finished.")

    def populate_rewrite_template_widgets(self):
        templates = self.config.get("rewrite_prompt_templates", {}).keys()
        
        self.rewrite_templates_listbox.delete(0, tk.END)
        for template in templates:
            self.rewrite_templates_listbox.insert(tk.END, template)
        
        self.rewrite_template_selector['values'] = list(templates)
        if list(templates):
            self.rewrite_template_var.set(list(templates)[0])

    def add_rewrite_template(self):
        dialog = CustomAskStringDialog(self.root, self._t('add_template_title'), self._t('add_template_prompt'), self)
        new_template_name = dialog.result

        if new_template_name:
            if new_template_name not in self.config.get("rewrite_prompt_templates", {}):
                
                new_template_prompts = {}
                for lang_code, lang_data in self.config.get("languages", {}).items():
                    new_template_prompts[lang_code] = lang_data.get("rewrite_prompt", "")
                
                if "rewrite_prompt_templates" not in self.config:
                    self.config["rewrite_prompt_templates"] = {}
                self.config["rewrite_prompt_templates"][new_template_name] = new_template_prompts
                self.populate_rewrite_template_widgets()
            else:
                messagebox.showwarning(self._t('warning_title'), self._t('warning_template_exists'))

    def remove_rewrite_template(self):
        selected_indices = self.rewrite_templates_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning(self._t('warning_title'), self._t('warning_select_template_to_remove'))
            return
            
        selected_template = self.rewrite_templates_listbox.get(selected_indices[0])
        
        if len(self.config.get("rewrite_prompt_templates", {})) <= 1:
            messagebox.showwarning(self._t('warning_title'), self._t('warning_cannot_remove_last_template'))
            return

        if messagebox.askyesno(self._t('confirm_title'), f"{self._t('confirm_remove_template')} '{selected_template}'?"):
            if selected_template in self.config.get("rewrite_prompt_templates", {}):
                del self.config["rewrite_prompt_templates"][selected_template]
                self.populate_rewrite_template_widgets()

    def update_codec_settings_ui(self, event=None):
        selected_codec_key = self.codec_video_codec_var.get()
        selected_codec = self.montage_api.codec_map.get(selected_codec_key)
        
        self.x264_settings_frame.pack_forget()
        self.amf_settings_frame.pack_forget()
        self.nvenc_settings_frame.pack_forget()
        self.vt_settings_frame.pack_forget()
        
        if selected_codec is None: return

        if selected_codec == 'libx264':
            self.x264_settings_frame.pack(fill='x', expand=True, pady=5, padx=5)
        elif 'nvenc' in selected_codec:
            self.nvenc_settings_frame.pack(fill='x', expand=True, pady=5, padx=5)
        elif 'amf' in selected_codec:
            self.amf_settings_frame.pack(fill='x', expand=True, pady=5, padx=5)
        elif 'videotoolbox' in selected_codec:
            self.vt_settings_frame.pack(fill='x', expand=True, pady=5, padx=5)

    def select_ffmpeg_path(self, title, filetypes):
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        if path:
            if sys.platform == 'win32' and os.path.basename(path).lower() != 'ffmpeg.exe':
                messagebox.showwarning(self._t('warning_title'), self._t('warning_select_ffmpeg_exe'))
            else:
                self.montage_ffmpeg_path_var.set(path)

    def change_language(self, event=None):
        selected_lang = self.language_var.get()
        lang_code = "ua" if selected_lang == "Українська" else "en"
        self.config["ui_settings"]["language"] = lang_code
        save_config(self.config)
        messagebox.showinfo(self._t('info_title'), self._t('info_restart_required'))

    def on_theme_changed(self, event=None):
        theme_map = {
            self._t('theme_darkly'): "darkly",
            self._t('theme_cyborg'): "cyborg",
            self._t('theme_litera'): "litera"
        }
        selected_display_name = self.theme_var.get()
        selected_theme = theme_map.get(selected_display_name, "darkly")
        self.config['ui_settings']['theme'] = selected_theme
        save_config(self.config)
        self.apply_theme_dynamically(selected_theme)
        messagebox.showinfo(self._t('info_message_box_title'), self._t('theme_changed_successfully'))

    def apply_theme_dynamically(self, theme_name):
        try:
            self.root.style.theme_use(theme_name)
            self.root.update()
            self.refresh_widget_colors()
            logger.info(f"Theme changed dynamically to: {theme_name}")
        except Exception as e:
            logger.error(f"Error applying theme {theme_name}: {e}")
            messagebox.showerror(self._t('error_title'), self._t('error_applying_theme', e=e))

    def refresh_widget_colors(self):
        try:
            theme_name = self.root.style.theme_use()
            is_dark = theme_name in ['darkly', 'cyborg']
            listbox_bg = "#444" if is_dark else "white"
            listbox_fg = "white" if is_dark else "black"
            scrolled_text_bg = "#333" if is_dark else "white"
            scrolled_text_fg = "white" if is_dark else "black"
            log_bg = "#1e1e1e" if is_dark else "#f0f0f0"
            log_fg = "white" if is_dark else "black"
            scrollbar_style = "dark-round" if is_dark else "light-round"
            if theme_name == 'cyborg': canvas_bg = "#060606"
            elif theme_name == 'darkly': canvas_bg = "#222222"
            else: canvas_bg = "#ffffff"
            widgets_to_update = {
                'rewrite_templates_listbox': (listbox_bg, listbox_fg), 'lang_listbox': (listbox_bg, listbox_fg),
                'or_models_listbox': (listbox_bg, listbox_fg), 'input_text': (scrolled_text_bg, scrolled_text_fg),
                'prompt_gen_prompt_text': (scrolled_text_bg, scrolled_text_fg), 'cta_prompt_text': (scrolled_text_bg, scrolled_text_fg),
                'lang_prompt_text': (scrolled_text_bg, scrolled_text_fg), 'rewrite_prompt_text': (scrolled_text_bg, scrolled_text_fg),
                'rewrite_links_text': (scrolled_text_bg, scrolled_text_fg), 'log_text': (log_bg, log_fg),
            }
            for attr_name, (bg, fg) in widgets_to_update.items():
                if hasattr(self, attr_name):
                    getattr(self, attr_name).configure(bg=bg, fg=fg)
            if hasattr(self, 'parallel_log_widgets'):
                for log_widget in self.parallel_log_widgets:
                    log_widget.configure(bg=log_bg, fg=fg)
            if hasattr(self, 'scrollable_canvases'):
                for cv in self.scrollable_canvases:
                    cv.configure(bg=canvas_bg)
            if hasattr(self, 'dynamic_scrollbars'):
                for sb in self.dynamic_scrollbars:
                    sb.configure(bootstyle=scrollbar_style)
        except Exception as e:
            logger.error(f"Помилка оновлення кольорів віджетів: {e}")

    def populate_openrouter_widgets(self):
        models = self.config["openrouter"].get("saved_models", [])
        self.or_models_listbox.delete(0, tk.END)
        for model in models:
            self.or_models_listbox.insert(tk.END, model)
        self.or_trans_model_combo['values'] = models
        self.or_prompt_model_combo['values'] = models
        self.or_cta_model_combo['values'] = models
        self.or_rewrite_model_combo['values'] = models

    def add_openrouter_model(self):
        dialog = CustomAskStringDialog(self.root, self._t('add_model_title'), self._t('add_model_prompt'), self)
        new_model = dialog.result
        if new_model:
            models = self.config["openrouter"].get("saved_models", [])
            if new_model not in models:
                models.append(new_model)
                self.config["openrouter"]["saved_models"] = models
                self.populate_openrouter_widgets()
            else:
                messagebox.showwarning(self._t('warning_title'), self._t('warning_model_exists'))

    def remove_openrouter_model(self):
        selected_indices = self.or_models_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning(self._t('warning_title'), self._t('warning_select_model_to_remove'))
            return
        selected_model = self.or_models_listbox.get(selected_indices[0])
        if messagebox.askyesno(self._t('confirm_title'), f"{self._t('confirm_remove_model')} '{selected_model}'?"):
            self.or_models_listbox.delete(selected_indices[0])
            self.config["openrouter"]["saved_models"] = list(self.or_models_listbox.get(0, tk.END))
            self.populate_openrouter_widgets()

    def populate_language_list(self):
        if hasattr(self, 'rewrite_templates_listbox'):
            self.populate_rewrite_template_widgets()
        self.lang_listbox.delete(0, tk.END)
        for code in self.config["languages"]:
            self.lang_listbox.insert(tk.END, code)

    def on_language_select(self, event):
        selection = event.widget.curselection()
        if selection:
            index = selection[0]
            code = event.widget.get(index)
            self.selected_lang_code = code
            self.show_language_details(code)

    def show_language_details(self, code):
        for widget in self.lang_details_frame.winfo_children():
            widget.destroy()
        lang_data = self.config["languages"][code]
        ttk.Label(self.lang_details_frame, text=f"{self._t('details_for_label')} {code.upper()}", font="-weight bold").pack(anchor='w')
        ttk.Label(self.lang_details_frame, text=self._t('translation_prompt_label')).pack(anchor='w')
        lang_prompt_container = ttk.Frame(self.lang_details_frame)
        lang_prompt_container.pack(fill="both", expand=True, padx=5, pady=5)
        initial_lang_height = self.config.get("ui_settings", {}).get("lang_text_height", 75)
        self.lang_prompt_frame = ttk.Frame(lang_prompt_container, height=initial_lang_height)
        self.lang_prompt_frame.pack(fill="x")
        self.lang_prompt_frame.pack_propagate(False)
        self.lang_prompt_text, text_container_widget = self._create_scrolled_text(self.lang_prompt_frame, height=3, width=60, relief="flat", insertbackground="white")
        text_container_widget.pack(fill="both", expand=True)
        add_text_widget_bindings(self, self.lang_prompt_text)
        lang_grip = ttk.Frame(lang_prompt_container, height=8, bootstyle="secondary", cursor="sb_v_double_arrow")
        lang_grip.pack(fill="x")
        canvas = self.lang_details_frame.canvas
        def start_resize_lang(event):
            lang_grip.startY = event.y
            lang_grip.start_height = self.lang_prompt_frame.winfo_height()
        def do_resize_lang(event):
            new_height = lang_grip.start_height + (event.y - lang_grip.startY)
            if 50 <= new_height <= 300:
                self.lang_prompt_frame.config(height=new_height)
                canvas.update_idletasks()
                canvas.config(scrollregion=canvas.bbox("all"))
        lang_grip.bind("<ButtonPress-1>", start_resize_lang)
        lang_grip.bind("<B1-Motion>", do_resize_lang)
        self.lang_prompt_text.insert(tk.END, lang_data.get("prompt", ""))
        ttk.Label(self.lang_details_frame, text=self._t('rewrite_prompt_label')).pack(anchor='w', pady=(10, 0))
        rewrite_prompt_container = ttk.Frame(self.lang_details_frame)
        rewrite_prompt_container.pack(fill="both", expand=True, padx=5, pady=5)
        initial_rewrite_height = self.config.get("ui_settings", {}).get("rewrite_prompt_height", 75)
        self.rewrite_prompt_frame = ttk.Frame(rewrite_prompt_container, height=initial_rewrite_height)
        self.rewrite_prompt_frame.pack(fill="x")
        self.rewrite_prompt_frame.pack_propagate(False)
        self.rewrite_prompt_text, text_container_widget = self._create_scrolled_text(self.rewrite_prompt_frame, height=3, width=60, relief="flat", insertbackground="white")
        text_container_widget.pack(fill="both", expand=True)
        add_text_widget_bindings(self, self.rewrite_prompt_text)
        rewrite_grip = ttk.Frame(rewrite_prompt_container, height=8, bootstyle="secondary", cursor="sb_v_double_arrow")
        rewrite_grip.pack(fill="x")
        def start_resize_rewrite(event):
            rewrite_grip.startY = event.y
            rewrite_grip.start_height = self.rewrite_prompt_frame.winfo_height()
        def do_resize_rewrite(event):
            new_height = rewrite_grip.start_height + (event.y - rewrite_grip.startY)
            if 50 <= new_height <= 300: 
                self.rewrite_prompt_frame.config(height=new_height)
                canvas.update_idletasks()
                canvas.config(scrollregion=canvas.bbox("all"))
        rewrite_grip.bind("<ButtonPress-1>", start_resize_rewrite)
        rewrite_grip.bind("<B1-Motion>", do_resize_rewrite)
        self.rewrite_prompt_text.insert(tk.END, lang_data.get("rewrite_prompt", ""))
        template_actions_frame = ttk.Frame(self.lang_details_frame)
        template_actions_frame.pack(fill='x', padx=5, pady=5)
        ttk.Label(template_actions_frame, text=self._t('view_prompt_from_template_label')).pack(side='left', padx=(0, 5))
        template_names = list(self.config.get("rewrite_prompt_templates", {}).keys())
        template_viewer_combo = ttk.Combobox(template_actions_frame, values=template_names, state="readonly", width=25)
        template_viewer_combo.pack(side='left', padx=5)
        if template_names:
            template_viewer_combo.set(template_names[0])
        template_viewer_combo.bind("<<ComboboxSelected>>", lambda event, c=code: self._on_template_view_selected(event, c))
        ttk.Button(template_actions_frame, text=self._t('save_to_template_button'), 
                command=lambda c=code: self.save_rewrite_prompt_to_template(c), 
                bootstyle="success-outline").pack(side='right', padx=5)
        ttk.Separator(self.lang_details_frame, orient='horizontal').pack(fill='x', pady=10)
        tts_frame = ttk.Frame(self.lang_details_frame)
        tts_frame.pack(fill='x', pady=5)
        ttk.Label(tts_frame, text=self._t('tts_service_label')).pack(side='left', padx=(0, 10))
        self.lang_tts_service_var = tk.StringVar(value=lang_data.get("tts_service", "elevenlabs"))
        self.lang_tts_service_dropdown = ttk.Combobox(tts_frame, textvariable=self.lang_tts_service_var, values=["elevenlabs", "voicemaker", "speechify"], state="readonly")
        self.lang_tts_service_dropdown.pack(side='left', fill='x', expand=True)
        self.lang_tts_service_dropdown.bind("<<ComboboxSelected>>", lambda e, c=code: self._on_tts_service_selected(c))
        
        self.el_voice_frame = ttk.Frame(self.lang_details_frame)
        self.vm_voice_frame = ttk.Frame(self.lang_details_frame)
        self.speechify_voice_frame = ttk.Frame(self.lang_details_frame) # <-- НОВЕ

        # --- ElevenLabs Widgets ---
        ttk.Label(self.el_voice_frame, text=self._t('voice_template_label')).pack(anchor='w')
        self.lang_el_template_var = tk.StringVar()
        self.lang_el_template_dropdown = ttk.Combobox(self.el_voice_frame, textvariable=self.lang_el_template_var, state="readonly")
        self.lang_el_template_dropdown.pack(fill='x', padx=5, pady=2)
        add_text_widget_bindings(self, self.lang_el_template_dropdown)

        # --- Voicemaker Widgets ---
        ttk.Label(self.vm_voice_frame, text=self._t('voicemaker_voice_label')).pack(anchor='w')
        self.lang_vm_voice_var = tk.StringVar()
        self.lang_vm_voice_dropdown = ttk.Combobox(self.vm_voice_frame, textvariable=self.lang_vm_voice_var, state="readonly")
        self.lang_vm_voice_dropdown.pack(fill='x', padx=5, pady=2)
        add_text_widget_bindings(self, self.lang_vm_voice_dropdown)
        
        # --- Speechify Widgets ---
        self.speechify_voice_frame.grid_columnconfigure(1, weight=1)
        
        ttk.Label(self.speechify_voice_frame, text=self._t('speechify_language_label')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
        self.lang_speechify_lang_var = tk.StringVar()
        self.lang_speechify_lang_dropdown = ttk.Combobox(self.speechify_voice_frame, textvariable=self.lang_speechify_lang_var, values=list(self.speechify_lang_voice_map.keys()), state="readonly")
        self.lang_speechify_lang_dropdown.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        
        ttk.Label(self.speechify_voice_frame, text=self._t('speechify_voice_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
        self.lang_speechify_voice_var = tk.StringVar()
        speechify_voice_entry = ttk.Entry(self.speechify_voice_frame, textvariable=self.lang_speechify_voice_var)
        speechify_voice_entry.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
        add_text_widget_bindings(self, speechify_voice_entry)
        
        ttk.Label(self.speechify_voice_frame, text=self._t('speechify_model_label')).grid(row=2, column=0, sticky='w', padx=5, pady=2)
        self.lang_speechify_model_var = tk.StringVar()
        self.lang_speechify_model_dropdown = ttk.Combobox(self.speechify_voice_frame, textvariable=self.lang_speechify_model_var, values=["simba-multilingual", "simba-english"], state="readonly")
        self.lang_speechify_model_dropdown.grid(row=2, column=1, sticky='ew', padx=5, pady=2)
        
        ttk.Label(self.speechify_voice_frame, text=self._t('speechify_emotion_label')).grid(row=3, column=0, sticky='w', padx=5, pady=2)
        self.lang_speechify_emotion_var = tk.StringVar()
        self.lang_speechify_emotion_dropdown = ttk.Combobox(self.speechify_voice_frame, textvariable=self.lang_speechify_emotion_var, values=SPEECHIFY_EMOTIONS, state="readonly")
        self.lang_speechify_emotion_dropdown.grid(row=3, column=1, sticky='ew', padx=5, pady=2)

        ttk.Label(self.speechify_voice_frame, text=self._t('speechify_pitch_label')).grid(row=4, column=0, sticky='w', padx=5, pady=2)
        self.lang_speechify_pitch_var = tk.IntVar(value=0)
        ttk.Scale(self.speechify_voice_frame, from_=-100, to=100, orient=tk.HORIZONTAL, variable=self.lang_speechify_pitch_var).grid(row=4, column=1, sticky='ew', padx=5, pady=2)
        
        ttk.Label(self.speechify_voice_frame, text=self._t('speechify_rate_label')).grid(row=5, column=0, sticky='w', padx=5, pady=2)
        self.lang_speechify_rate_var = tk.IntVar(value=0)
        ttk.Scale(self.speechify_voice_frame, from_=-100, to=100, orient=tk.HORIZONTAL, variable=self.lang_speechify_rate_var).grid(row=5, column=1, sticky='ew', padx=5, pady=2)

        # --- Control Widgets ---
        self.update_language_voice_dropdowns(code)
        self._on_tts_service_selected(code)
        ttk.Button(self.lang_details_frame, text=self._t('update_button'), command=lambda: self.update_language_details(code), bootstyle="info-outline").pack(pady=10)

    def _on_template_view_selected(self, event, lang_code):
        template_name = event.widget.get()
        if not template_name:
            return
        prompt_text = self.config.get("rewrite_prompt_templates", {}).get(template_name, {}).get(lang_code, "")
        self.rewrite_prompt_text.delete("1.0", tk.END)
        self.rewrite_prompt_text.insert("1.0", prompt_text)
        logger.info(f"Loaded rewrite prompt for '{lang_code}' from template '{template_name}' for viewing.")

    def _on_tts_service_selected(self, lang_code):
        service = self.lang_tts_service_var.get()
        self.el_voice_frame.pack_forget()
        self.vm_voice_frame.pack_forget()
        self.speechify_voice_frame.pack_forget() # <-- ДОДАНО
        if service == 'elevenlabs':
            self.el_voice_frame.pack(fill='x', pady=5)
        elif service == 'voicemaker':
            self.vm_voice_frame.pack(fill='x', pady=5)
        elif service == 'speechify': # <-- ДОДАНО
            self.speechify_voice_frame.pack(fill='x', pady=5) # <-- ДОДАНО

    def update_language_details(self, code):
        if code in self.config["languages"]:
            lang_data = self.config["languages"][code]
            lang_data["prompt"] = self.lang_prompt_text.get("1.0", tk.END).strip()
            lang_data["rewrite_prompt"] = self.rewrite_prompt_text.get("1.0", tk.END).strip()
            selected_service = self.lang_tts_service_var.get()
            lang_data["tts_service"] = selected_service
            if selected_service == "elevenlabs":
                selected_template_name = self.lang_el_template_var.get()
                if selected_template_name and hasattr(self, 'lang_el_template_uuid_map') and selected_template_name in self.lang_el_template_uuid_map:
                    lang_data["elevenlabs_template_uuid"] = self.lang_el_template_uuid_map[selected_template_name]
                else:
                    lang_data.pop("elevenlabs_template_uuid", None)
            elif selected_service == "voicemaker":
                selected_voice_id = self.lang_vm_voice_var.get()
                lang_data["voicemaker_voice_id"] = selected_voice_id
                voices = self.vm_api.get_voices_for_language(code)
                voice_info = next((v for v in voices if v['VoiceId'] == selected_voice_id), None)
                if voice_info:
                    lang_data["voicemaker_engine"] = voice_info['Engine']
                else:
                    lang_data.pop("voicemaker_engine", None)
            # --- НОВИЙ БЛОК ДЛЯ SPEECHIFY ---
            elif selected_service == "speechify":
                lang_data["speechify_language"] = self.lang_speechify_lang_var.get()
                lang_data["speechify_voice_id"] = self.lang_speechify_voice_var.get()
                lang_data["speechify_model"] = self.lang_speechify_model_var.get()
                lang_data["speechify_emotion"] = self.lang_speechify_emotion_var.get()
                lang_data["speechify_pitch"] = self.lang_speechify_pitch_var.get()
                lang_data["speechify_rate"] = self.lang_speechify_rate_var.get()
            # --- КІНЕЦЬ НОВОГО БЛОКУ ---
            logger.info(f"Updated settings for language {code}")
            messagebox.showinfo(self._t('success_title'), f"{self._t('info_settings_updated_for')} {code.upper()}")
    
    def save_rewrite_prompt_to_template(self, lang_code):
        prompt_content = self.rewrite_prompt_text.get("1.0", tk.END).strip()
        if not prompt_content:
            messagebox.showwarning(self._t('warning_title'), self._t('warning_prompt_empty'))
            return
        dialog = AskTemplateDialog(self.root, self._t('select_template_dialog_title'), 
                                   list(self.config.get("rewrite_prompt_templates", {}).keys()), self)
        template_name = dialog.result
        if template_name:
            if template_name in self.config.get("rewrite_prompt_templates", {}):
                self.config["rewrite_prompt_templates"][template_name][lang_code] = prompt_content
                messagebox.showinfo(self._t('success_title'), 
                                    self._t('info_prompt_saved_to_template', lang=lang_code.upper(), template=template_name))
                logger.info(f"Saved rewrite prompt for '{lang_code}' to template '{template_name}'.")
            else:
                messagebox.showerror(self._t('error_title'), self._t('error_template_not_found'))

    def update_language_voice_dropdowns(self, lang_code):
        lang_data = self.config["languages"].get(lang_code, {})
        el_templates = self.el_api.get_templates()
        el_template_names = [t['name'] for t in el_templates]
        self.lang_el_template_dropdown['values'] = el_template_names
        self.lang_el_template_uuid_map = {t['name']: t['uuid'] for t in el_templates}
        current_el_uuid = lang_data.get("elevenlabs_template_uuid")
        if current_el_uuid:
            current_el_name = next((name for name, uuid in self.lang_el_template_uuid_map.items() if uuid == current_el_uuid), None)
            if current_el_name:
                self.lang_el_template_var.set(current_el_name)
        
        vm_voices = self.vm_api.get_voices_for_language(lang_code)
        vm_voice_ids = [v['VoiceId'] for v in vm_voices]
        self.lang_vm_voice_dropdown['values'] = vm_voice_ids
        current_vm_voice_id = lang_data.get("voicemaker_voice_id")
        if current_vm_voice_id in vm_voice_ids:
            self.lang_vm_voice_var.set(current_vm_voice_id)
        elif vm_voice_ids:
            self.lang_vm_voice_var.set(vm_voice_ids[0])

        # --- НОВИЙ БЛОК ДЛЯ SPEECHIFY ---
        self.lang_speechify_lang_var.set(lang_data.get("speechify_language", "Ukrainian"))
        self.lang_speechify_voice_var.set(lang_data.get("speechify_voice_id", "anatoly"))
        self.lang_speechify_model_var.set(lang_data.get("speechify_model", "simba-multilingual"))
        self.lang_speechify_emotion_var.set(lang_data.get("speechify_emotion", "Без емоцій"))
        self.lang_speechify_pitch_var.set(lang_data.get("speechify_pitch", 0))
        self.lang_speechify_rate_var.set(lang_data.get("speechify_rate", 0))
        # --- КІНЕЦЬ НОВОГО БЛОКУ ---

    def add_language(self):
        dialog = CustomAskStringDialog(self.root, self._t('add_language_title'), self._t('add_language_prompt'), self)
        code = dialog.result
        if code and code not in self.config["languages"]:
            default_prompt = DEFAULT_CONFIG["default_prompts"]["translation"].format(language=code, text="{text}")
            default_rewrite_prompt = f"Rewrite the following text in {code}, keeping the main idea but making it unique: {{text}}"
            self.config["languages"][code] = { 
                "prompt": default_prompt,
                "rewrite_prompt": default_rewrite_prompt,
                "tts_service": "elevenlabs",
                "elevenlabs_template_uuid": None,
                "voicemaker_voice_id": None,
                "voicemaker_engine": None
            }
            for template_name in self.config.get("rewrite_prompt_templates", {}):
                self.config["rewrite_prompt_templates"][template_name][code] = default_rewrite_prompt
            self.populate_language_list()
            logger.info(f"Added new language: {code}")

    def remove_language(self):
        if self.selected_lang_code and self.selected_lang_code in self.config["languages"]:
            if messagebox.askyesno(self._t('confirm_title'), f"{self._t('confirm_remove_language')} {self.selected_lang_code.upper()}?"):
                code_to_remove = self.selected_lang_code
                del self.config["languages"][code_to_remove]
                for template_name in self.config.get("rewrite_prompt_templates", {}):
                    if code_to_remove in self.config["rewrite_prompt_templates"][template_name]:
                        del self.config["rewrite_prompt_templates"][template_name][code_to_remove]
                self.selected_lang_code = None
                self.populate_language_list()
                for widget in self.lang_details_frame.winfo_children():
                    widget.destroy()
                logger.info(f"Removed language: {code_to_remove}")

    def update_path_widgets_state(self):
        use_default = self.config.get("output_settings", {}).get("use_default_dir", False)
        state = 'disabled' if use_default else 'normal'
        for lang_code, widgets in self.lang_widgets.items():
            widgets['entry'].config(state=state)
            widgets['button'].config(state=state)
        if hasattr(self, 'rewrite_lang_widgets'):
            for lang_code, widgets in self.rewrite_lang_widgets.items():
                pass
        self.update_queue_display()
        self.update_rewrite_queue_display()

    def toggle_default_dir_widgets(self):
        is_checked = self.output_use_default_var.get()
        state = 'normal' if is_checked else 'disabled'
        
        if hasattr(self, 'output_default_dir_entry'):
            self.output_default_dir_entry.config(state=state)
        if hasattr(self, 'output_default_dir_button'):
            self.output_default_dir_button.config(state=state)
        
        self.config['output_settings']['use_default_dir'] = is_checked
        self.update_path_widgets_state()

    def browse_default_dir(self):
        folder = filedialog.askdirectory(title=self._t('default_dir_label'))
        if folder:
            self.output_default_dir_var.set(folder)

    def browse_rewrite_default_dir(self):
        folder = filedialog.askdirectory(title=self._t('rewrite_default_dir_label'))
        if folder:
            self.output_rewrite_default_dir_var.set(folder)

    def _concatenate_videos(self, video_files, output_path):
        if not video_files:
            logger.error("No video files to concatenate.")
            return False
        
        self.update_progress(self._t('phase_final_video'))
        logger.info(f"Concatenating {len(video_files)} video chunks into {output_path}...")

        concat_list_path = os.path.join(os.path.dirname(output_path), "concat_list.txt")
        with open(concat_list_path, "w", encoding='utf-8') as f:
            for file_path in video_files:
                safe_path = file_path.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        try:
            (
                ffmpeg
                .input(concat_list_path, format='concat', safe=0)
                .output(output_path, c='copy')
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            logger.info("Video concatenation successful.")
            os.remove(concat_list_path)
            return True
        except ffmpeg.Error as e:
            logger.error(f"Failed to concatenate videos. FFmpeg stderr:\n{e.stderr.decode()}")
            if os.path.exists(concat_list_path):
                os.remove(concat_list_path)
            return False

    def _audio_generation_worker(self, text_chunk, output_path, lang_config, lang_code, chunk_index, total_chunks):
        self.log_context.parallel_task = 'Audio Gen'
        self.log_context.worker_id = f'Chunk {chunk_index}/{total_chunks}'
        try:
            tts_service = lang_config.get("tts_service", "elevenlabs")
            logger.info(f"Starting audio generation task with {tts_service}")
            
            if tts_service == "elevenlabs":
                task_id = self.el_api.create_audio_task(text_chunk, lang_config.get("elevenlabs_template_uuid"))
                new_balance = self.el_api.balance
                if new_balance is not None:
                    self._update_elevenlabs_balance_labels(new_balance)
                if task_id and task_id != "INSUFFICIENT_BALANCE":
                    if self.wait_for_elevenlabs_task(task_id, output_path):
                        return output_path
            
            elif tts_service == "voicemaker":
                voice_id = lang_config.get("voicemaker_voice_id")
                engine = lang_config.get("voicemaker_engine")
                success, new_balance = self.vm_api.generate_audio(text_chunk, voice_id, engine, lang_code, output_path)
                if success:
                    if new_balance is not None:
                        vm_text = new_balance if new_balance is not None else 'N/A'
                        self.root.after(0, lambda: self.settings_vm_balance_label.config(text=f"{self._t('balance_label')}: {vm_text}"))
                        self.root.after(0, lambda: self.chain_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
                        self.root.after(0, lambda: self.rewrite_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}"))
                    return output_path
            
            elif tts_service == "speechify":
                logger.info("[Chain] Using Speechify for TTS.")
                success, _ = self.speechify_api.generate_audio_streaming(
                    text=text_chunk,
                    voice_id=lang_config.get("speechify_voice_id"),
                    model=lang_config.get("speechify_model"),
                    output_path=output_path,
                    emotion=lang_config.get("speechify_emotion"),
                    pitch=lang_config.get("speechify_pitch", 0),
                    rate=lang_config.get("speechify_rate", 0)
                )
                if success:
                    return output_path

            logger.error(f"Failed to generate audio chunk using {tts_service}")
            return None
        finally:
            if hasattr(self.log_context, 'parallel_task'): del self.log_context.parallel_task
            if hasattr(self.log_context, 'worker_id'): del self.log_context.worker_id

    def _parallel_subtitle_worker(self, audio_chunk_paths: list, subs_chunk_dir: str) -> list:
        logger.info(f"Starting parallel subtitle generation for {len(audio_chunk_paths)} audio chunks.")
        subs_chunk_paths = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(audio_chunk_paths)) as executor:
            future_to_index = {
                executor.submit(self.montage_api.create_subtitles, audio_path, os.path.join(subs_chunk_dir, f"subs_chunk_{i}.ass")): i
                for i, audio_path in enumerate(audio_chunk_paths)
            }
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                if future.result():
                    subs_path = os.path.join(subs_chunk_dir, f"subs_chunk_{index}.ass")
                    subs_chunk_paths.append(subs_path)
                else:
                    logger.error(f"Failed to generate subtitle chunk for index {index}.")

        logger.info(f"Finished subtitle generation. Successfully created {len(subs_chunk_paths)} subtitle files.")
        return sorted(subs_chunk_paths)
    
    def _sequential_subtitle_worker(self, audio_chunk_paths: list, subs_chunk_dir: str) -> list:
        logger.info(f"Starting sequential subtitle generation for {len(audio_chunk_paths)} audio chunks.")
        subs_chunk_paths = []
        total_chunks = len(audio_chunk_paths)
        for i, audio_path in enumerate(audio_chunk_paths):
            self.update_progress(self._t('transcribing_chunk', current=i + 1, total=total_chunks))
            subs_path = os.path.join(subs_chunk_dir, f"subs_chunk_{i}.ass")
            if self.montage_api.create_subtitles(audio_path, subs_path):
                subs_chunk_paths.append(subs_path)
            else:
                logger.error(f"Failed to generate subtitle chunk for {audio_path}.")
        
        logger.info(f"Finished subtitle generation. Successfully created {len(subs_chunk_paths)} subtitle files.")
        return sorted(subs_chunk_paths)

    def _video_chunk_worker(self, images_for_chunk, audio_path, subs_path, output_path, chunk_index, total_chunks):
        self.log_context.parallel_task = 'Video Montage'
        self.log_context.worker_id = f'Chunk {chunk_index}/{total_chunks}'
        try:
            logger.info(f"ЗАПУСК FFMPEG (відео шматок {chunk_index}/{total_chunks}) для аудіо: {os.path.basename(audio_path)}")
            if self.montage_api.create_video(images_for_chunk, audio_path, subs_path, output_path):
                logger.info(f"ЗАВЕРШЕННЯ FFMPEG (відео шматок {chunk_index}/{total_chunks})")
                return output_path
            logger.error(f"ПОМИЛКА FFMPEG (відео шматок {chunk_index}/{total_chunks})")
            return None
        finally:
            if hasattr(self.log_context, 'parallel_task'): del self.log_context.parallel_task
            if hasattr(self.log_context, 'worker_id'): del self.log_context.worker_id

    def _prepare_parallel_audio_chunks(self, text_to_process, lang_config, lang_code, temp_dir, num_parallel_chunks):
        tts_service = lang_config.get("tts_service", "elevenlabs")
        temp_audio_dir = os.path.join(temp_dir, "audio_chunks")
        os.makedirs(temp_audio_dir, exist_ok=True)
        logger.info(f"Preparing audio chunks for {lang_code} using {tts_service}...")

        text_chunks = []
        # Визначаємо, як нарізати текст, залежно від сервісу та довжини
        voicemaker_limit = self.config.get("voicemaker", {}).get("char_limit", 9900)
        if tts_service == "voicemaker" and len(text_to_process) > voicemaker_limit:
            logger.info(f"Voicemaker: Text is long ({len(text_to_process)}), splitting by limit.")
            text_chunks = chunk_text_voicemaker(text_to_process, voicemaker_limit)
        elif tts_service == "speechify" and len(text_to_process) > SPEECHIFY_CHAR_LIMIT:
            logger.info(f"Speechify: Text is long ({len(text_to_process)}), splitting into ~{num_parallel_chunks} chunks.")
            text_chunks = chunk_text_speechify(text_to_process, SPEECHIFY_CHAR_LIMIT, num_parallel_chunks)
        else:
            logger.info(f"Standard TTS: Splitting text into {num_parallel_chunks} chunks for parallel processing.")
            text_chunks = chunk_text(text_to_process, num_parallel_chunks)

        # Генерація аудіо для отриманих частин
        audio_chunks_paths = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(text_chunks)) as executor:
            future_to_index = {
                executor.submit(self._audio_generation_worker, chunk, os.path.join(temp_audio_dir, f"chunk_{i}.mp3"), lang_config, lang_code, i + 1, len(text_chunks)): i
                for i, chunk in enumerate(text_chunks)
            }
            results = [None] * len(text_chunks)
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                results[index] = future.result()
        
        audio_chunks_paths = [r for r in results if r]
        
        if len(audio_chunks_paths) != len(text_chunks):
            logger.error(f"Failed to generate all audio chunks for {tts_service}.")
            return None

        # Специфічна логіка для Voicemaker та Speechify: об'єднання, якщо частин більше, ніж потоків
        if (tts_service == "voicemaker" or tts_service == "speechify") and len(audio_chunks_paths) > num_parallel_chunks:
            logger.info(f"Merging {len(audio_chunks_paths)} {tts_service} audio chunks into {num_parallel_chunks} final chunks.")
            chunk_size = math.ceil(len(audio_chunks_paths) / num_parallel_chunks)
            final_audio_chunks = []
            for i in range(0, len(audio_chunks_paths), chunk_size):
                chunk_to_merge = audio_chunks_paths[i:i + chunk_size]
                if len(chunk_to_merge) > 1:
                    output_file = os.path.join(temp_audio_dir, f"merged_chunk_{len(final_audio_chunks)}.mp3")
                    if concatenate_audio_files(chunk_to_merge, output_file):
                        final_audio_chunks.append(output_file)
                    else:
                        logger.error(f"Failed to merge a chunk of {tts_service} audio files.")
                        return None
                else:
                    final_audio_chunks.extend(chunk_to_merge)
            return final_audio_chunks
        else:
            return sorted(audio_chunks_paths)

# --- НОВИЙ БЛОК: ВСЕ ДЛЯ ВКЛАДКИ РЕРАЙТУ ---
    def add_to_rewrite_queue(self):
        video_folder = os.path.join(APP_BASE_PATH, "video")
        if not os.path.isdir(video_folder):
            os.makedirs(video_folder)
            messagebox.showinfo(self._t('folder_created_title'), self._t('folder_created_message'))
            return

        selected_langs = [code for code, var in self.rewrite_lang_checkbuttons.items() if var.get()]
        if not selected_langs:
            messagebox.showwarning(self._t('warning_title'), self._t('warning_no_lang'))
            return

        output_cfg = self.config.get("output_settings", {})
        if not output_cfg.get("rewrite_default_dir") or not os.path.isdir(output_cfg.get("rewrite_default_dir")):
            messagebox.showwarning(self._t('warning_title'), self._t('warning_invalid_rewrite_dir'))
            return
        
        self.processed_links = self.load_processed_links()
        
        new_files_found = 0
        for filename in os.listdir(video_folder):
            if filename.lower().endswith(".mp3") and filename not in self.processed_links:
                file_path = os.path.join(video_folder, filename)
                task_name = f"{self._t('rewrite_task_prefix')}: {os.path.splitext(filename)[0]}"
                steps = {lang: {key: var.get() for key, var in self.rewrite_lang_step_vars[lang].items()} for lang in selected_langs}

                task_config = {
                    "task_name": task_name,
                    "mp3_path": file_path,
                    "original_filename": filename,
                    "selected_langs": selected_langs,
                    "steps": steps,
                    "timestamp": time.time(),
                }
                self.rewrite_task_queue.append(task_config)
                new_files_found += 1

        if new_files_found > 0:
            self.update_rewrite_queue_display()
            messagebox.showinfo(self._t('queue_title'), self._t('info_new_tasks_added', count=new_files_found))
        else:
            messagebox.showinfo(self._t('queue_title'), self._t('info_no_new_files'))

    def update_rewrite_queue_display(self):
        if not hasattr(self, 'rewrite_queue_tree'): return
        
        for item in self.rewrite_queue_tree.get_children():
            self.rewrite_queue_tree.delete(item)
            
        steps_map = {
            'download': self._t('step_download'), 'transcribe': self._t('step_transcribe'),
            'rewrite': self._t('step_rewrite'), 'cta': self._t('step_cta'), 
            'gen_prompts': self._t('step_gen_prompts'), 'gen_images': self._t('step_gen_images'), 
            'audio': self._t('step_audio'), 'create_subtitles': self._t('step_create_subtitles'),
            'create_video': self._t('step_create_video')
        }

        for i, task in enumerate(self.rewrite_task_queue):
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(task['timestamp']))
            task_node = self.rewrite_queue_tree.insert("", "end", iid=f"task_{i}", text=task['task_name'], values=(self._t('status_pending'), timestamp), open=True)
            for lang_code in task['selected_langs']:
                lang_node = self.rewrite_queue_tree.insert(task_node, "end", text=f"  - {lang_code.upper()}", values=("", ""))
                enabled_steps = [steps_map[key] for key, value in task['steps'][lang_code].items() if value]
                self.rewrite_queue_tree.insert(lang_node, "end", text=f"    {self._t('steps_label')}: {', '.join(enabled_steps)}", values=("", ""))

    def clear_rewrite_queue(self):
        if messagebox.askyesno(self._t('confirm_title'), self._t('confirm_clear_queue')):
            self.rewrite_task_queue.clear()
            self.update_rewrite_queue_display()
            logger.info("Rewrite queue cleared.")

    def load_links_from_file(self):
        filepath = filedialog.askopenfilename(title=self._t('load_from_file_button'), filetypes=[("Text files", "*.txt")])
        if filepath:
            with open(filepath, 'r', encoding='utf-8') as f:
                self.rewrite_links_text.delete('1.0', tk.END)
                self.rewrite_links_text.insert('1.0', f.read())
            logger.info(f"Links loaded from {filepath}")
            
    def load_processed_links(self):
        filename = self.config.get("rewrite_settings", {}).get("processed_links_file", "processed_links.txt")
        path = os.path.join(APP_BASE_PATH, filename)
        if os.path.exists(path):
            with open(path, "r", encoding='utf-8') as f:
                return set(line.strip() for line in f)
        return set()

    def save_processed_link(self, filename):
        self.processed_links.add(filename)
        processed_file_path = self.config.get("rewrite_settings", {}).get("processed_links_file", "processed_links.txt")
        path = os.path.join(APP_BASE_PATH, processed_file_path)
        with open(path, "a", encoding='utf-8') as f:
            f.write(f"{filename}\n")
            
    def _run_single_rewrite_chain(self, task_num, total_tasks, task_config):
        video_title = task_config["video_title"]
        transcribed_text = task_config["transcribed_text"]
        lang_code = task_config["lang_code"]
        steps = task_config["steps"]
        lang_config = self.config["languages"][lang_code]
        lang_name = lang_code.upper()
        
        rewrite_base_dir = self.config['output_settings']['rewrite_default_dir']
        lang_output_path = os.path.join(rewrite_base_dir, video_title, lang_code.upper())
        os.makedirs(lang_output_path, exist_ok=True)
        
        temp_dir = os.path.join(lang_output_path, "temp_chunks")
        keep_temp_files = self.config['parallel_processing']['keep_temp_files']

        try:
            logger.info(f"[Rewrite Chain] Starting parallel chain for '{lang_name}' from video '{video_title}'")
            self.update_progress(f"Завд.{task_num}/{total_tasks} | {lang_name} - {self._t('step_rewrite')}...")
            
            selected_template_name = self.rewrite_template_var.get()
            rewrite_prompt_template = self.config.get("rewrite_prompt_templates", {}).get(selected_template_name, {}).get(lang_code)

            if not rewrite_prompt_template:
                logger.error(f"Rewrite prompt for language '{lang_code}' not found in template '{selected_template_name}'. Using default.")
                rewrite_prompt_template = lang_config.get("rewrite_prompt", "Rewrite the following text: {text}")

            rewritten_text = self.or_api.rewrite_text(
                transcribed_text,
                self.config["openrouter"]["rewrite_model"],
                self.config["openrouter"]["rewrite_params"],
                rewrite_prompt_template
            )
            if not rewritten_text:
                logger.error(f"Rewrite failed for {lang_name}. Stopping chain.")
                return
            
            with open(os.path.join(lang_output_path, "rewritten_text.txt"), "w", encoding='utf-8') as f: f.write(rewritten_text)
            self._send_telegram_notification('rewrite', lang_name, task_num, total_tasks)
            
            parallel_cfg = self.config.get("parallel_processing", {})
            num_parallel_chunks = parallel_cfg.get("num_chunks", 3)
            
            subs_chunk_dir = os.path.join(temp_dir, "subs"); os.makedirs(subs_chunk_dir, exist_ok=True)
            video_chunk_dir = os.path.join(temp_dir, "video"); os.makedirs(video_chunk_dir, exist_ok=True)
            
            self.update_progress(f"Завд.{task_num}/{total_tasks} | {lang_name}: {self._t('phase_audio_and_assets')}")

            raw_prompts, cta_text = None, None
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                cta_future = executor.submit(self.or_api.generate_call_to_action, rewritten_text, self.config["openrouter"]["cta_model"], self.config["openrouter"]["cta_params"], lang_name) if steps['cta'] else None
                prompts_future = executor.submit(self.or_api.generate_image_prompts, rewritten_text, self.config["openrouter"]["prompt_model"], self.config["openrouter"]["prompt_params"], lang_name) if steps['gen_prompts'] else None
                if cta_future: cta_text = cta_future.result()
                if prompts_future: raw_prompts = prompts_future.result()
            
            if cta_text: open(os.path.join(lang_output_path, "call_to_action.txt"), 'w', encoding='utf-8').write(cta_text)
            
            image_prompts = []
            if raw_prompts:
                open(os.path.join(lang_output_path, "image_prompts.txt"), 'w', encoding='utf-8').write(raw_prompts)
                image_prompts = [re.sub(r'^\s*(\d+[\.\)]|[a-zA-Z][\.\)])\s*', '', p).strip() for p in raw_prompts.splitlines() if p.strip()]
                logger.info(f"Generated {len(image_prompts)} image prompts for {lang_name}.")

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                audio_future = None
                if steps.get('audio'):
                    audio_future = executor.submit(self._prepare_parallel_audio_chunks, rewritten_text, lang_config, lang_code, temp_dir, num_parallel_chunks)
                
                image_future = None
                if steps.get('gen_images') and image_prompts:
                    images_folder = os.path.join(lang_output_path, "images"); os.makedirs(images_folder, exist_ok=True)
                    image_future = executor.submit(self._image_generation_worker, image_prompts, images_folder, lang_name, task_num, total_tasks)
                
                final_audio_chunks = []
                if audio_future:
                    final_audio_chunks = audio_future.result()
                    
                subs_chunk_paths = []
                if steps.get('create_subtitles') and final_audio_chunks:
                    subs_chunk_paths = self._sequential_subtitle_worker(final_audio_chunks, subs_chunk_dir)

                if image_future:
                    image_future.result()
            
            if not steps['create_video']: return
            
            all_images = sorted([os.path.join(lang_output_path, "images", f) for f in os.listdir(os.path.join(lang_output_path, "images")) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
            if not all_images or not final_audio_chunks or len(subs_chunk_paths) != len(final_audio_chunks):
                logger.error(f"Missing assets for video creation ({lang_name}, {video_title}). Images: {len(all_images)}, Audio: {len(final_audio_chunks)}, Subs: {len(subs_chunk_paths)}. Stopping.")
                return

            self.update_progress(f"Завд.{task_num}/{total_tasks} | {lang_name}: {self._t('phase_video_chunks')}")
            
            image_chunks = np.array_split(all_images, len(final_audio_chunks))
            video_chunk_paths = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                video_futures = {executor.submit(self._video_chunk_worker, list(image_chunks[i]), final_audio_chunks[i], subs_chunk_paths[i], os.path.join(video_chunk_dir, f"video_chunk_{i}.mp4"), i + 1, len(final_audio_chunks)): i for i in range(len(final_audio_chunks))}
                for f in concurrent.futures.as_completed(video_futures):
                    result = f.result()
                    if result: video_chunk_paths.append(result)
            
            if len(video_chunk_paths) == len(final_audio_chunks):
                final_video_path = os.path.join(lang_output_path, f"video_{sanitize_filename(video_title)}_{lang_code}.mp4")
                if self._concatenate_videos(sorted(video_chunk_paths), final_video_path):
                    logger.info(f"Successfully created final video: {final_video_path}")
                    self._send_telegram_notification('create_video', lang_name, task_num, total_tasks)
            
        finally:
             if not keep_temp_files and os.path.exists(temp_dir):
                 self.update_progress(self._t('phase_cleaning_up'))
                 shutil.rmtree(temp_dir)
                 logger.info(f"Cleaned up temp directory: {temp_dir}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if console_window == 0:
            ctypes.windll.kernel32.AllocConsole()
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            sys.stdout = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
            sys.stderr = open('CONOUT$', 'w', encoding='utf-8', buffering=1)
        except Exception as e:
            print(f"Could not set console to UTF-8: {e}")

    setup_logging()

    config = load_config()
    selected_theme = config.get("ui_settings", {}).get("theme", "darkly")
    root = ttk.Window(themename=selected_theme)
    
    app = TranslationApp(root, config)
    root.mainloop()