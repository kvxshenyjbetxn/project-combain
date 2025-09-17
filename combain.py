# Standard library imports
import tkinter as tk
from tkinter import ttk as classic_ttk, scrolledtext, messagebox, filedialog, simpledialog
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
from queue import Queue

# Third-party imports
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from PIL import Image, ImageTk
import whisper
import ffmpeg

# API modules
from api.elevenlabs_api import ElevenLabsAPI
from api.montage_api import MontageAPI
from api.openrouter_api import OpenRouterAPI
from api.pollinations_api import PollinationsAPI
from api.recraft_api import RecraftAPI
from api.telegram_api import TelegramAPI
from api.voicemaker_api import VoiceMakerAPI
from api.speechify_api import SpeechifyAPI
from api.firebase_api import FirebaseAPI

# Core modules
from core.workflow import WorkflowManager

# GUI modules
from gui.task_tab import create_task_tab
from gui.rewrite_tab import create_rewrite_tab
from gui.log_tab import create_log_tab
from gui.settings_tab import create_settings_tab
from gui.gui_utils import add_text_widget_bindings, CustomAskStringDialog, AskTemplateDialog, AdvancedRegenerateDialog, create_scrollable_tab, create_scrolled_text

# Application constants
from constants.app_settings import (
    APP_BASE_PATH,
    CONFIG_FILE,
    TRANSLATIONS_FILE,
    DETAILED_LOG_FILE,
    SPEECHIFY_CHAR_LIMIT
)

from constants.default_config import DEFAULT_CONFIG
from constants.voicemaker_voices import VOICEMAKER_VOICES
from constants.recraft_substyles import RECRAFT_SUBSTYLES
from constants.speechify_voices import LANG_VOICE_MAP, SPEECHIFY_EMOTIONS

from utils import (
    setup_logging,
    load_config,
    save_config,
    load_translations,
    sanitize_filename,
    setup_ffmpeg_path,
    chunk_text,
    chunk_text_voicemaker,
    chunk_text_speechify,
    concatenate_audio_files,
    suppress_stdout_stderr,
    clear_user_logs,
    clear_user_images,
    refresh_user_stats,
    refresh_firebase_stats,
    clear_firebase_logs,
    clear_firebase_images,
    update_elevenlabs_balance_labels,
    test_elevenlabs_connection,
    update_elevenlabs_info,
    update_recraft_balance_labels,
    test_recraft_connection,
    update_recraft_substyles,
    send_telegram_error_notification,
    send_task_completion_report,
    test_telegram_connection,
    test_openrouter_connection,
    populate_openrouter_widgets,
    add_openrouter_model,
    remove_openrouter_model,
    test_pollinations_connection,
    test_voicemaker_connection,
    test_speechify_connection
)

from utils.settings_utils import save_settings as save_settings_util

from utils.media_utils import concatenate_videos, video_chunk_worker

# Configure logging
logger = logging.getLogger("TranslationApp")


# Main application logic
class TranslationApp:
    """Main application class handling the translation and content generation workflow."""
    
    def _check_dependencies(self):
        """Check for all required libraries before startup."""
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
        """Initialize the application with configuration and setup APIs."""
        self.root = root
        self.config = config
        self.translations = load_translations()
        self.lang = self.config.get("ui_settings", {}).get("language", "ua")
        self.APP_BASE_PATH = APP_BASE_PATH # Додаємо константу як атрибут класу
        
        # Check dependencies first
        self._check_dependencies()

        self.log_context = threading.local()
        self.translations = load_translations()
        self.lang = self.config.get("ui_settings", {}).get("language", "ua")
        self.log_context = threading.local()
        self.speechify_lang_voice_map = LANG_VOICE_MAP
        
        setup_ffmpeg_path(self.config)

        self.root.title(self._t("window_title"))
        try:
            icon_image = tk.PhotoImage(file='icon.png')
            self.root.iconphoto(False, icon_image)
        except tk.TclError as e:
            logger.warning(f"Could not load application icon: {e}")
        self.root.geometry("1100x800")
        
        # Initialize API services
        self.or_api = OpenRouterAPI(self.config)
        self.poll_api = PollinationsAPI(self.config, self)
        self.el_api = ElevenLabsAPI(self.config)
        self.vm_api = VoiceMakerAPI(self.config)
        self.recraft_api = RecraftAPI(self.config)
        self.tg_api = TelegramAPI(self.config)
        self.firebase_api = FirebaseAPI(self.config)
        self.speechify_api = SpeechifyAPI(self.config)
        self.montage_api = MontageAPI(self.config, self, self.update_progress_for_montage)
        self.workflow_manager = WorkflowManager(self)

        # Unified Queue management
        self.task_queue = []
        self.is_processing_queue = False
        self.is_shutting_down = False
        self.dynamic_scrollbars = []

        self.processed_links = self.load_processed_links()

        self.pause_event = threading.Event()
        self.pause_event.set()
        self.shutdown_event = threading.Event()

        # Telegram polling variables
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
        
        # Нові змінні для детального підрахунку прогресу
        self.total_individual_steps = 0
        self.completed_individual_steps = 0

        self.gui_log_handler = None
        self.scrollable_canvases = []
        
        # Сховище для прогресу відео-чанків
        self.video_chunk_progress = {}
        self.video_progress_lock = threading.Lock()
        
        # Task status tracking for reports
        self.task_completion_status = {}

        # Image gallery variables
        self.image_gallery_frame = None
        self.continue_button = None
        self.image_control_active = threading.Event()
        self.command_listener_thread = None
        self.stop_command_listener = threading.Event()
        self.image_id_to_path_map = {}
        self.command_queue = Queue()
        
        # Theme mapping dictionaries
        self.theme_map_to_display = {
            "darkly": self._t('theme_darkly'), 
            "cyborg": self._t('theme_cyborg'), 
            "litera": self._t('theme_litera')
        }
        self.theme_map_to_internal = {v: k for k, v in self.theme_map_to_display.items()}


        self.setup_gui()
        self.setup_global_bindings() 
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.populate_rewrite_template_widgets()
        self.display_saved_balances()
        self.refresh_widget_colors()
        
        # Ініціалізація статистики користувача
        if hasattr(self, 'user_stats_label'):
            self.refresh_user_stats()
        
        # Clear old gallery images on startup if auto-clear is enabled
        if self.firebase_api.is_initialized and self.config.get("firebase", {}).get("auto_clear_gallery", True):
            self.firebase_api.clear_images()
            #logger.info("Auto-cleared old gallery images from Firebase on application startup")
            
        # Clear montage ready status on startup
        if self.firebase_api.is_initialized:
            self.firebase_api.clear_montage_ready_status()
            #logger.info("Cleared montage ready status on application startup")
            
        # Відкладаємо оновлення балансів до моменту коли GUI буде готовий
        self.root.after(1000, self.update_startup_balances)

    def display_saved_balances(self):
        vm_balance = self.config.get("voicemaker", {}).get("last_known_balance")
        vm_text = vm_balance if vm_balance is not None else "N/A"
        
        self.settings_vm_balance_label.config(text=f"{self._t('balance_label')}: {vm_text}")
        self.chain_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}")
        self.rewrite_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}")
        self.queue_vm_balance_label.config(text=f"{self._t('voicemaker_balance_label')}: {vm_text}")

    def _t(self, key, **kwargs):
        translation = self.translations.get(self.lang, {}).get(key, key)
        return translation.format(**kwargs)
    
    def _escape_markdown(self, text: str) -> str:
        """Safely escape special characters for Telegram MarkdownV2."""
        escape_chars = r'\_*[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

    def _on_skip_image_click(self):
        logger.warning("User clicked 'Skip Image'.")
        self.skip_image_event.set()
        self._update_button_states(is_processing=True, is_image_stuck=False)

    def _on_regenerate_alt_click(self):
        logger.warning("User clicked 'Try Alternative Service'.")
        self.regenerate_alt_service_event.set()
        self._update_button_states(is_processing=True, is_image_stuck=False)

    def _on_image_api_select(self, event=None):
        """Synchronize API selection across all tabs and save settings."""
        new_api = self.active_image_api_var.get()
        self.config["ui_settings"]["image_generation_api"] = new_api
        self.active_image_api = new_api
        logger.info(f"Default image generation API set to: {new_api}")
        save_config(self.config)

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
        """Enable only the skip button."""
        for button in self.skip_image_buttons:
            if button:
                self.root.after(0, lambda b=button: b.config(state="normal"))

    def disable_skip_button(self):
        """Disable only the skip button."""
        for button in self.skip_image_buttons:
            if button:
                self.root.after(0, lambda b=button: b.config(state="disabled"))
                
    def _command_listener_worker(self):
        self.firebase_api.listen_for_commands(self._handle_firebase_command)

    def _handle_firebase_command(self, event):
        # Обробляємо як dict, так і об'єкти з атрибутами
        if isinstance(event, dict):
            event_path = event.get('path', '/')
            event_data = event.get('data')
            event_type = event.get('event', 'put')
        else:
            event_path = getattr(event, 'path', '/')
            event_data = getattr(event, 'data', None)
            event_type = getattr(event, 'event_type', 'put')
            
        if self.is_shutting_down or event_path == "/" and event_data is None:
            return

        if event_type == 'put' and event_path != '/':
            command_id = event_path.strip('/')
            command_data = event_data
            
            # Кладемо команду в чергу
            self.command_queue.put((command_id, command_data))

    def _process_command_queue(self):
        """Обробити команди з черги в основному потоці GUI."""
        try:
            while not self.command_queue.empty():
                command_id, command_data = self.command_queue.get_nowait()
                
                # ВИПРАВЛЕННЯ: Ігноруємо порожні дані, які приходять після видалення команди
                if command_data is None:
                    continue

                logger.info(f"Firebase -> Обробка команди з черги: {command_id} з даними: {command_data}")

                # Видаляємо команду одразу, щоб уникнути повторної обробки
                self.firebase_api.commands_ref.child(command_id).delete()

                command = command_data.get("command")
                image_id = command_data.get("imageId")

                if command == "delete":
                    self._delete_image_by_id(image_id)
                elif command == "regenerate":
                    new_prompt = command_data.get("newPrompt")
                    service_override = command_data.get("serviceOverride")
                    model_override = command_data.get("modelOverride")
                    style_override = command_data.get("styleOverride")
                    self._regenerate_image_by_id(image_id, new_prompt, service_override, model_override, style_override)
                elif command == "continue_montage":
                    logger.info("Firebase -> Отримано команду продовження монтажу з мобільного додатку")
                    self._continue_montage_from_mobile()
        
        finally:
            # Перезапускаємо таймер для наступної перевірки
            if not self.stop_command_listener.is_set():
                self.root.after(200, self._process_command_queue)

    def _delete_image_by_id(self, image_id):
        if image_id in self.image_id_to_path_map:
            path = self.image_id_to_path_map[image_id]
            logger.info(f"Виконання команди 'delete' для {image_id} (шлях: {path})")
            self._delete_image(path)
        else:
            logger.warning(f"Не вдалося знайти локальний шлях для зображення ID {image_id}")
    
    def _regenerate_image_by_id(self, image_id, new_prompt=None, service_override=None, model_override=None, style_override=None):
        if image_id in self.image_id_to_path_map:
            path = self.image_id_to_path_map[image_id]
            logger.info(f"Виконання команди 'regenerate' для {image_id} (шлях: {path})")
            
            # Якщо прийшов новий промпт, оновлюємо його в мапі
            if new_prompt:
                self.image_prompts_map[path] = new_prompt
                logger.info(f"Оновлено промпт для {os.path.basename(path)}: {new_prompt}")

            # Створюємо словник параметрів для regeneration
            regen_params = {
                'new_prompt': new_prompt,
                'use_random_seed': not new_prompt
            }
            
            # Додаємо параметри сервісу та моделі, якщо вони задані
            if service_override:
                regen_params['service_override'] = service_override
                logger.info(f"Використовується сервіс: {service_override}")
            if model_override:
                regen_params['model_override'] = model_override
                logger.info(f"Використовується модель: {model_override}")
            if style_override:
                regen_params['style_override'] = style_override
                logger.info(f"Використовується стиль: {style_override}")

            self._regenerate_image(path, **regen_params)
        else:
            logger.warning(f"Could not find local path for image regeneration ID {image_id}")

    def clear_gallery_manually(self):
        """Manually clear all images from Firebase gallery."""
        if not self.firebase_api.is_initialized:
            messagebox.showwarning(self._t('warning_title'), "Firebase is not initialized")
            return
            
        result = messagebox.askyesno(
            "Clear Gallery", 
            "Are you sure you want to clear all images from the gallery?\n\nThis action cannot be undone."
        )
        
        if result:
            try:
                self.firebase_api.clear_images()
                # Also clear local gallery mapping
                self.image_id_to_path_map.clear()
                messagebox.showinfo("Success", "Gallery cleared successfully!")
                logger.info("Manual gallery clearing completed")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to clear gallery: {e}")
                logger.error(f"Manual gallery clearing failed: {e}")

    def on_closing(self):
        # Enable "quiet mode"
        self.is_shutting_down = True
        self.shutdown_event.set() 
        #logger.info("Application shutdown: saving UI settings...")

        # Зупиняємо аудіо воркер пул
        if hasattr(self, 'workflow_manager') and self.workflow_manager:
            self.workflow_manager.shutdown()

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
                #logger.info("Очищення файлів попереднього перегляду...")
                for filename in os.listdir(preview_folder):
                    if filename.startswith("preview_video_") and filename.endswith(".mp4"):
                        file_path = os.path.join(preview_folder, filename)
                        os.remove(file_path)
                        logger.debug(f"Видалено: {file_path}")
        except Exception as e:
            logger.error(f"Помилка при очищенні папки 'preview': {e}")

        # 2. Зупиняємо слухач команд та очищуємо Firebase
        self.stop_command_listener.set()
        if self.command_listener_thread:
            self.command_listener_thread.join(timeout=2)

        if hasattr(self, 'firebase_api') and self.firebase_api.is_initialized:
            self.firebase_api.clear_logs()
            self.firebase_api.clear_images()
            self.firebase_api.clear_commands()
            self.firebase_api.clear_montage_ready_status()  # Очищуємо статус готовності до монтажу
            time.sleep(1) # Невелика затримка, щоб запити напевно пішли

        logger.info("Програму закрито.")
        self.root.destroy()
        
    def _update_elevenlabs_balance_labels(self, new_balance):
        """Update ElevenLabs balance labels - delegates to utility function."""
        update_elevenlabs_balance_labels(self, new_balance)

    def _update_recraft_balance_labels(self, new_balance):
        """Update Recraft balance labels - delegates to utility function."""
        update_recraft_balance_labels(self, new_balance)

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
                    # Перевіряємо чи потрібна прокрутка для цього канвасу
                    canvas = parent
                    canvas_height = canvas.winfo_height()
                    scroll_region = canvas.cget('scrollregion')
                    
                    if scroll_region:
                        # Розбираємо scrollregion (x1, y1, x2, y2)
                        region_coords = scroll_region.split()
                        if len(region_coords) >= 4:
                            content_height = float(region_coords[3]) - float(region_coords[1])
                            
                            # Дозволяємо прокрутку тільки якщо контент більший за канвас
                            if content_height > canvas_height:
                                delta = 0
                                if sys.platform == "darwin": 
                                    delta = event.delta
                                elif event.num == 4: 
                                    delta = -1
                                elif event.num == 5: 
                                    delta = 1
                                elif event.delta: 
                                    delta = -1 * int(event.delta / 120)
                                if delta != 0:
                                    canvas.yview_scroll(delta, "units")
                    return 
                if parent == self.root: 
                    break
                parent = parent.master
        except (KeyError, AttributeError, ValueError):
            pass

    def _on_tab_changed(self, event):
        """Обробник зміни вкладок для скидання прокрутки"""
        try:
            # Отримуємо поточну активну вкладку
            current_tab = self.notebook.select()
            current_tab_widget = self.notebook.nametowidget(current_tab)
            
            # Знаходимо всі канваси в поточній вкладці
            for canvas in self.scrollable_canvases:
                try:
                    # Перевіряємо чи канвас належить поточній вкладці
                    parent = canvas.master
                    while parent and parent != self.root:
                        if parent == current_tab_widget:
                            # Оновлюємо скрол-регіон
                            canvas.update_idletasks()
                            canvas.configure(scrollregion=canvas.bbox("all"))
                            
                            # Скидаємо прокрутку вгору
                            canvas.yview_moveto(0)
                            break
                        parent = parent.master
                except:
                    continue
                    
            # Викликаємо функції оновлення скролу, якщо вони є
            if hasattr(self, 'update_scroll_functions'):
                for update_func in self.update_scroll_functions:
                    try:
                        update_func()
                    except:
                        continue
        except:
            pass

    def setup_gui(self):
        self.notebook = ttk.Notebook(self.root, bootstyle="dark")
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # 1. Ініціалізуємо всі фрейми для вкладок
        self.chain_frame = ttk.Frame(self.notebook)
        self.rewrite_frame = ttk.Frame(self.notebook)
        self.queue_frame = ttk.Frame(self.notebook)
        self.settings_frame = ttk.Frame(self.notebook)
        self.log_frame = ttk.Frame(self.notebook)

        # Імпортуємо функції для створення вмісту вкладок
        from gui.task_tab import create_task_tab
        from gui.rewrite_tab import create_rewrite_tab
        from gui.queue_tab import create_queue_tab
        from gui.log_tab import create_log_tab
        from gui.settings_tab import create_settings_tab

        # 2. Додаємо фрейми як вкладки до notebook У ПРАВИЛЬНОМУ ПОРЯДКУ
        # Функція create_task_tab вже містить notebook.add, тому її залишаємо
        create_task_tab(self.notebook, self) 
        self.notebook.add(self.rewrite_frame, text=self._t('rewrite_tab'))
        self.notebook.add(self.queue_frame, text=self._t('task_queue_tab'))
        self.notebook.add(self.settings_frame, text=self._t('settings_tab'))
        self.notebook.add(self.log_frame, text=self._t('log_tab'))

        # 3. Заповнюємо вмістом фрейми, які ще не заповнені
        create_rewrite_tab(self.notebook, self)
        create_queue_tab(self.notebook, self)
        create_settings_tab(self.notebook, self)
        create_log_tab(self.notebook, self)

        # Додаємо обробник зміни вкладок для скидання прокрутки
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Image gallery frame setup (initially hidden)
        self.image_gallery_frame = ttk.Frame(self.root)
        self.continue_button = ttk.Button(self.image_gallery_frame, text=self._t('continue_button'), command=self.continue_processing_after_image_control, bootstyle="success")

        # Запускаємо періодичне оновлення GUI для прогресу
        self.start_periodic_progress_update()

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

        default_task_name = f"{self._t('task_label')} {len(self.task_queue) + 1}"
        dialog = CustomAskStringDialog(self.root, 
                                       self._t('add_task_title', default="Введіть назву завдання"), 
                                       self._t('add_task_prompt', default="Назва завдання:"), 
                                       self, 
                                       initial_value=default_task_name)
        
        task_name = dialog.result
        if not task_name:
            return False

        task_config = {
            "type": "Translate",
            "task_name": task_name,
            "input_text": self.input_text.get("1.0", tk.END).strip(),
            "selected_langs": selected_langs,
            "steps": task_steps,
            "timestamp": time.time(),
            "lang_output_paths": lang_output_paths
        }

        self.task_queue.insert(0, task_config) # Додаємо завдання на початок черги
        self.update_queue_display()
        logger.info(f"Додано нове завдання '{task_name}' на початок черги. Загальна кількість: {len(self.task_queue)}")
        
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
            
            # Оновлюємо скрол-регіон після видалення елементів
            if hasattr(self, 'update_scroll_functions'):
                for update_func in self.update_scroll_functions:
                    update_func()

    def update_queue_display(self):
        if not hasattr(self, 'queue_tree'):
            return
        
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        for i, task in enumerate(self.task_queue):
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(task['timestamp']))
            task_name = task.get('task_name', f"{self._t('task_label')} {i+1}")
            
            total_progress = self._calculate_task_progress(i)
            progress_text = f"({total_progress}%)" if total_progress > 0 else ""
            
            task_type = task.get('type', 'N/A')
            task_node = self.queue_tree.insert("", "end", iid=f"task_{i}",
                                             text=f"{task_name} {progress_text}",
                                             values=(task_type, self._t('status_pending'), timestamp), open=True)
            
            for lang_code in task['selected_langs']:
                # Визначаємо чи це завдання рерайту чи перекладу
                task_type = task.get('type', 'Translate')
                if task_type == 'Rewrite':
                    # Для завдань рерайту завжди використовуємо стандартну папку
                    lang_path_display = self._t('use_default_rewrite_dir_label')
                else:
                    # Для завдань перекладу перевіряємо налаштування
                    use_default_dir = self.config.get("output_settings", {}).get("use_default_dir", False)
                    lang_path_display = self._t('use_default_dir_label') if use_default_dir else task.get('lang_output_paths', {}).get(lang_code, '...')
                
                lang_progress = self._calculate_language_progress(i, lang_code)
                lang_progress_text = f"({lang_progress}%)" if lang_progress > 0 else ""
                
                lang_node = self.queue_tree.insert(task_node, "end", 
                                                 text=f"{lang_code.upper()} {lang_progress_text}", 
                                                 values=("", ""), open=True)
                
                self.queue_tree.insert(lang_node, "end", text=f"{self._t('path_label')}: {lang_path_display}", values=("", ""))
                
                for step_key, enabled in task['steps'][lang_code].items():
                    if enabled:
                        step_name = self._t(f'step_name_{step_key}')
                        status_text = self._get_unified_step_status(i, lang_code, step_key, task_type)
                        
                        if status_text:
                            step_text = f"{step_name}: {status_text}"
                        else:
                            step_text = step_name
                        
                        self.queue_tree.insert(lang_node, "end", text=step_text, values=("", ""))
                        
        if self.task_queue:
            last_task_id = f"task_{len(self.task_queue) - 1}"
            if self.queue_tree.exists(last_task_id):
                self.queue_tree.see(last_task_id)
                self.queue_tree.item(last_task_id, open=True)
                for child in self.queue_tree.get_children(last_task_id):
                    self.queue_tree.item(child, open=True)

    def _calculate_task_progress(self, task_index):
        """Розраховує загальний прогрес завдання у відсотках"""
        if not hasattr(self, 'task_completion_status'):
            return 0
        
        task = self.task_queue[task_index] if task_index < len(self.task_queue) else None
        if not task:
            return 0
        
        total_steps = 0
        completed_steps = 0
        
        for lang_code in task['selected_langs']:
            status_key = f"{task_index}_{lang_code}"
            if status_key in self.task_completion_status:
                for step_status in self.task_completion_status[status_key]['steps'].values():
                    total_steps += 1
                    if step_status == "✅":
                        completed_steps += 1
        
        return int((completed_steps / total_steps * 100)) if total_steps > 0 else 0
    
    def _calculate_language_progress(self, task_index, lang_code):
        """Розраховує прогрес для конкретної мови у відсотках"""
        if not hasattr(self, 'task_completion_status'):
            return 0
        
        status_key = f"{task_index}_{lang_code}"
        if status_key not in self.task_completion_status:
            return 0
        
        steps = self.task_completion_status[status_key]['steps']
        total_steps = len(steps)
        completed_steps = sum(1 for status in steps.values() if status == "✅")
        
        return int((completed_steps / total_steps * 100)) if total_steps > 0 else 0
    
    def update_task_status_display(self, task_index=None, lang_code=None, step_key=None, status=None):
        """Оновлює статус конкретного кроку в єдиній черзі завдань."""
        if not hasattr(self, 'queue_tree'):
            return

        # Незалежно від параметрів, ми просто викликаємо повне оновлення
        # відображення черги, оскільки це найнадійніший спосіб.
        try:
            # Оновлюємо відображення після короткої затримки, щоб уникнути зависання UI
            self.root.after(100, self.update_queue_display)
        except Exception as e:
            # Ігноруємо помилки, якщо GUI недоступний під час закриття
            if "invalid command name" not in str(e):
                 logger.warning(f"Помилка під час планування оновлення GUI: {e}")


    def update_rewrite_task_status_display(self, task_index=None, lang_code=None, step_key=None, status=None):
        """Оновлює статус конкретного кроку рерайт-завдання в черзі (псевдонім для update_task_status_display)."""
        # Ця функція тепер просто викликає основну, оскільки інтерфейс черги єдиний.
        self.update_task_status_display(task_index, lang_code, step_key, status)

    def process_queue(self):
        if self.is_processing_queue:
            messagebox.showinfo(self._t('queue_title'), self._t('info_queue_processing'))
            return
        if not self.task_queue:
            messagebox.showinfo(self._t('queue_title'), self._t('info_queue_empty'))
            return
        
        self.is_processing_queue = True
        
        if hasattr(self, 'pause_resume_button'):
            self.pause_resume_button.config(state="normal")
        
        # Запускаємо обробку єдиної черги
        thread = threading.Thread(target=self.workflow_manager.process_unified_queue, args=(self.task_queue,))
        thread.daemon = True
        thread.start()

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
        self.image_id_to_path_map.clear() # Очищуємо мапу на початку

    def _add_image_to_gallery(self, image_path, task_key):
        container_info = self.gallery_lang_containers.get(task_key)
        if not container_info: return

        main_container = container_info['main_container']
        
        # Dynamic layout system for gallery images
        try:
            # Calculate actual dimensions for the future image frame
            temp_frame = ttk.Frame(main_container)
            temp_frame.update_idletasks()
            frame_width = temp_frame.winfo_reqwidth() + 200
            temp_frame.destroy()
            
            container_width = self.active_gallery_canvas.winfo_width() - 20

            # Check if a new row is needed
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

    def _check_app_state(self):
        """Перевіряє, чи не зупинено програму. Повертає False, якщо треба зупинити потік."""
        if self.shutdown_event.is_set():
            return False
        
        if not self.pause_event.is_set():
            # Автоматично визначаємо тип черги
            queue_type = 'rewrite' if self.is_processing_rewrite_queue else 'main'
            self.update_progress(self._t('status_paused'), queue_type=queue_type)
            self.pause_event.wait()
            if self.shutdown_event.is_set(): # Перевіряємо знову після паузи
                return False
            # Не відновлюємо попередній текст
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
                    if self.el_api.wait_for_elevenlabs_task(self, task_id, audio_file_path):
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
        """Негайно відправляє сповіщення про помилку - delegates to utility function."""
        send_telegram_error_notification(self, task_name, lang_code, step, error_details)

    def send_task_completion_report(self, task_config, single_lang_code=None):
        """Формує та відправляє фінальний звіт по завершенню всього завдання або однієї мови - delegates to utility function."""
        send_task_completion_report(self, task_config, single_lang_code)

    def update_progress(self, text, increment_step=False, queue_type='main'):
        if increment_step:
            self.current_queue_step += 1
        
        # Оновлюємо тільки прогрес-бар без тексту
        progress_percent = min(100, (self.current_queue_step / self.total_queue_steps) * 100) if self.total_queue_steps > 0 else 0
        
        # Оскільки тепер прогрес-бар єдиний, ми завжди оновлюємо self.progress_var
        # і ігноруємо 'queue_type' для цього віджета.
        if hasattr(self, 'progress_var'):
            self.root.after(0, lambda: self.progress_var.set(progress_percent))
    
    def update_progress_for_montage(self, message, task_key=None, chunk_index=None, progress=None):
        logger.info(f"[Montage Progress] {message}")
        if task_key and chunk_index is not None and progress is not None:
            with self.video_progress_lock:
                if task_key not in self.video_chunk_progress:
                    self.video_chunk_progress[task_key] = {}
                self.video_chunk_progress[task_key][chunk_index] = progress

                # Розрахунок середнього прогресу для завдання
                total_progress = sum(self.video_chunk_progress[task_key].values())
                num_active_chunks = len(self.video_chunk_progress[task_key])
                average_progress = total_progress / num_active_chunks if num_active_chunks > 0 else 0
                
                # Оновлення статусу в task_completion_status
                task_index, lang_code = task_key
                status_key = f"{task_index}_{lang_code}"
                if status_key in self.task_completion_status:
                    self.task_completion_status[status_key]['video_progress'] = average_progress

# Test connection methods
    def test_openrouter_connection(self):
        """Test OpenRouter connection - delegates to utility function."""
        test_openrouter_connection(self)

    def reset_openrouter_balance(self):
        """Reset OpenRouter balance - delegates to utility function."""
        from utils.openrouter_utils import reset_openrouter_balance
        reset_openrouter_balance(self)

    def test_pollinations_connection(self):
        """Test Pollinations connection - delegates to utility function."""
        test_pollinations_connection(self)

    def test_elevenlabs_connection(self):
        """Test ElevenLabs connection - delegates to utility function."""
        test_elevenlabs_connection(self)

    def test_voicemaker_connection(self):
        """Test Voicemaker connection - delegates to utility function."""
        test_voicemaker_connection(self)

    def test_recraft_connection(self):
        """Test Recraft connection - delegates to utility function."""
        test_recraft_connection(self)

    def test_telegram_connection(self):
        """Test Telegram connection - delegates to utility function."""
        test_telegram_connection(self)

    def test_speechify_connection(self):
        """Test Speechify connection - delegates to utility function."""
        test_speechify_connection(self)

    def _update_recraft_substyles(self, event=None):
        """Update Recraft substyles - delegates to utility function."""
        update_recraft_substyles(self, event)

    def save_settings(self):
        """Зберігає всі налаштування додатку через утиліту settings_utils."""
        save_settings_util(self)

    def update_elevenlabs_info(self, update_templates=True):
        """Update ElevenLabs API information - delegates to utility function."""
        update_elevenlabs_info(self, update_templates)

    def update_api_balances(self):
        def update_thread():
            self.update_elevenlabs_info(update_templates=False)
            
            # Оновлюємо баланс OpenRouter
            or_balance = self.or_api.get_balance()
            from utils.openrouter_utils import update_openrouter_balance_labels
            update_openrouter_balance_labels(self, or_balance)
            logger.info(f"OpenRouter balance updated: {or_balance}")
            
            recraft_balance = self.recraft_api.get_balance()
            recraft_text = recraft_balance if recraft_balance is not None else 'N/A'
            self.root.after(0, lambda: self.settings_recraft_balance_label.config(text=f"{self._t('balance_label')}: {recraft_text}"))
            self.root.after(0, lambda: self.chain_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
            self.root.after(0, lambda: self.rewrite_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
            self.root.after(0, lambda: self.queue_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
            logger.info(f"Recraft balance updated: {recraft_balance}")

            vm_balance = self.vm_api.get_balance()
            if vm_balance is not None:
                if 'voicemaker' not in self.config: self.config['voicemaker'] = {}
                self.config['voicemaker']['last_known_balance'] = vm_balance
                save_config(self.config)
            
            # Використовуємо utility функцію для оновлення VoiceMaker балансів
            from utils.voicemaker_utils import update_voicemaker_balance_labels
            update_voicemaker_balance_labels(self, vm_balance)
            logger.info(f"Voicemaker balance updated: {vm_balance}")

        threading.Thread(target=update_thread, daemon=True).start()

    def update_startup_balances(self):
        def update_thread():
            try:
                # Перевіряємо чи головний потік ще активний
                if hasattr(self.root, 'after'):
                    self.update_elevenlabs_info(update_templates=True)
                    
                    # Оновлюємо баланс OpenRouter
                    or_balance = self.or_api.get_balance()
                    from utils.openrouter_utils import update_openrouter_balance_labels
                    update_openrouter_balance_labels(self, or_balance)
                    #logger.info(f"OpenRouter startup balance updated: {or_balance}")
                    
                    recraft_balance = self.recraft_api.get_balance()
                    recraft_text = recraft_balance if recraft_balance is not None else 'N/A'
                    
                    # Безпечно оновлюємо GUI тільки якщо головний цикл активний
                    try:
                        self.root.after(0, lambda: self.settings_recraft_balance_label.config(text=f"{self._t('balance_label')}: {recraft_text}"))
                        self.root.after(0, lambda: self.chain_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
                        self.root.after(0, lambda: self.rewrite_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
                        self.root.after(0, lambda: self.queue_recraft_balance_label.config(text=f"{self._t('recraft_balance_label')}: {recraft_text}"))
                    except RuntimeError:
                        # Ігноруємо помилки якщо головний цикл ще не готовий
                        pass
            except Exception as e:
                logger.error(f"Error updating startup balances: {e}")
        
        threading.Thread(target=update_thread, daemon=True).start()

    def update_char_count(self, event=None):
        text = self.input_text.get("1.0", tk.END)
        char_count = len(text) - 1
        self.char_count_label.config(text=f"{self._t('chars_label')}: {char_count}")

    def toggle_pause_resume(self):
        if self.pause_event.is_set():
            self.pause_event.clear()
            # Оновлюємо кнопку на основній вкладці
            if hasattr(self, 'pause_resume_button'):
                self.pause_resume_button.config(text=self._t('resume_button'))
            # Оновлюємо кнопку на вкладці рерайт
            if hasattr(self, 'rewrite_pause_resume_button'):
                self.rewrite_pause_resume_button.config(text=self._t('resume_button'))
            self.update_progress(self._t('status_pausing'))
            logger.info("Pause requested. The process will pause after the current step.")
        else:
            # Оновлюємо кнопку на основній вкладці
            if hasattr(self, 'pause_resume_button'):
                self.pause_resume_button.config(text=self._t('pause_button'))
            # Оновлюємо кнопку на вкладці рерайт
            if hasattr(self, 'rewrite_pause_resume_button'):
                self.rewrite_pause_resume_button.config(text=self._t('pause_button'))
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
                # Video remains in folder for user access
                self.root.after(0, lambda: self.preview_button.config(state="normal", text=self._t('preview_button_text')))

        threading.Thread(target=preview_thread, daemon=True).start()

    def continue_processing_after_image_control(self):
        logger.info("Continue button pressed. Resuming final video processing. Gallery remains visible.")
        
        # Очищуємо статус готовності до монтажу
        if self.firebase_api and self.firebase_api.is_initialized:
            self.firebase_api.clear_montage_ready_status()
        
        # Ховаємо лише саму кнопку "Продовжити", щоб уникнути повторних натискань
        if hasattr(self, 'continue_button') and self.continue_button and self.continue_button.winfo_ismapped():
            self.continue_button.pack_forget()
            
        self.image_control_active.set() # Знімає блокування з потоку обробки

    def _continue_montage_from_mobile(self):
        """Обробляє команду продовження монтажу з мобільного додатку."""
        logger.info("Продовження монтажу з мобільного додатку.")
        
        # Очищуємо статус готовності до монтажу
        if self.firebase_api and self.firebase_api.is_initialized:
            self.firebase_api.clear_montage_ready_status()
        
        # Ховаємо кнопку "Продовжити", якщо вона є
        if hasattr(self, 'continue_button') and self.continue_button and self.continue_button.winfo_ismapped():
            self.continue_button.pack_forget()
            
        # Знімаємо блокування з потоку обробки (так само як і в desktop версії)
        self.image_control_active.set()
        
        # Надсилаємо лог про продовження монтажу
        if self.firebase_api and self.firebase_api.is_initialized:
            self.firebase_api.send_log_in_thread("✅ Монтаж продовжено з мобільного додатку")

    def _delete_image(self, image_path):
        """Видаляє зображення з диску та з галереї."""
        try:
            # Знаходимо ID зображення перед видаленням
            image_id_to_remove = next((id for id, path in self.image_id_to_path_map.items() if path == image_path), None)
            
            if os.path.exists(image_path):
                os.remove(image_path)
                logger.info(f"Image deleted from disk: {image_path}")
                
            if image_path in self.image_widgets:
                self.image_widgets[image_path].destroy()
                del self.image_widgets[image_path]
                logger.info(f"Image widget removed from gallery")
            
            # Видаляємо з Firebase
            if image_id_to_remove and self.firebase_api.is_initialized:
                self.firebase_api.delete_image_from_db(image_id_to_remove)
                self.firebase_api.delete_image_from_storage(image_id_to_remove)
                # Видаляємо з локальної мапи
                del self.image_id_to_path_map[image_id_to_remove]
                logger.info(f"Image removed from Firebase: {image_id_to_remove}")
                
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
            
            if active_api_name == "pollinations":
                random_seed = random.randint(0, 2**32 - 1)
                api_params['seed'] = random_seed
                logger.info(f"Regenerating image {os.path.basename(image_path)} with new seed: {random_seed}")
            elif use_random_seed:
                random_seed = random.randint(0, 2**32 - 1)
                api_params['seed'] = random_seed
                logger.info(f"Regenerating image {os.path.basename(image_path)} with new seed: {random_seed}")

            logger.info(f"[{active_api_name.capitalize()}] Regenerating image for prompt: {prompt_to_use}")
            
            success = False
            
            if active_api_name == "pollinations":
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

                # --- ОНОВЛЕННЯ ЗОБРАЖЕННЯ В FIREBASE ---
                image_id_to_update = next((id for id, path in self.image_id_to_path_map.items() if path == image_path), None)
                if image_id_to_update and self.firebase_api.is_initialized:
                    remote_path = f"gallery_images/{image_id_to_update}.jpg"
                    # Завантажуємо оновлений файл на те ж місце в Storage
                    new_url = self.firebase_api.upload_image_and_get_url(image_path, remote_path)
                    if new_url:
                        # Оновлюємо посилання та timestamp в базі даних
                        self.firebase_api.update_image_in_db(image_id_to_update, new_url)

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
        """Populate OpenRouter widgets - delegates to utility function."""
        populate_openrouter_widgets(self)

    def add_openrouter_model(self):
        """Add OpenRouter model - delegates to utility function."""
        add_openrouter_model(self)

    def remove_openrouter_model(self):
        """Remove OpenRouter model - delegates to utility function."""
        remove_openrouter_model(self)

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
        self.lang_prompt_text, text_container_widget = create_scrolled_text(self, self.lang_prompt_frame, height=3, width=60, relief="flat", insertbackground="white")
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
        self.rewrite_prompt_text, text_container_widget = create_scrolled_text(self, self.rewrite_prompt_frame, height=3, width=60, relief="flat", insertbackground="white")
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
        self.speechify_voice_frame = ttk.Frame(self.lang_details_frame)

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
        self.speechify_voice_frame.pack_forget()
        if service == 'elevenlabs':
            self.el_voice_frame.pack(fill='x', pady=5)
        elif service == 'voicemaker':
            self.vm_voice_frame.pack(fill='x', pady=5)
        elif service == 'speechify':
            self.speechify_voice_frame.pack(fill='x', pady=5) 

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

    def _generate_single_audio_chunk(self, text_chunk, output_path, lang_config, lang_code):
        """Простий метод для генерації одного аудіо фрагменту."""
        tts_service = lang_config.get("tts_service", "elevenlabs")
        
        try:
            if tts_service == "elevenlabs":
                task_id = self.el_api.create_audio_task(text_chunk, lang_config.get("elevenlabs_template_uuid"))
                if task_id and task_id != "INSUFFICIENT_BALANCE":
                    return self.el_api.wait_for_elevenlabs_task(self, task_id, output_path)
                    
            elif tts_service == "voicemaker":
                voice_id = lang_config.get("voicemaker_voice_id")
                engine = lang_config.get("voicemaker_engine")
                success, _ = self.vm_api.generate_audio(text_chunk, voice_id, engine, lang_code, output_path)
                return success
                
            elif tts_service == "speechify":
                success, _ = self.speechify_api.generate_audio_streaming(
                    text=text_chunk,
                    voice_id=lang_config.get("speechify_voice_id"),
                    model=lang_config.get("speechify_model"),
                    output_path=output_path,
                    emotion=lang_config.get("speechify_emotion"),
                    pitch=lang_config.get("speechify_pitch", 0),
                    rate=lang_config.get("speechify_rate", 0)
                )
                return success
                
            return False
        except Exception as e:
            logger.exception(f"Помилка генерації аудіо фрагменту: {e}")
            return False

    def _prepare_parallel_audio_chunks(self, text_to_process, lang_config, lang_code, temp_dir, num_parallel_chunks):
        """
        ЗАСТАРІЛИЙ МЕТОД: Цей метод використовується для старої логіки аудіо обробки.
        Новий метод знаходиться в core.audio_pipeline.AudioWorkerPool.
        Залишений для сумісності зі старими частинами коду.
        """
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
        
        # Заглушка: використовуємо простий спосіб без воркер пулу для старої логіки
        for i, chunk in enumerate(text_chunks):
            output_path = os.path.join(temp_audio_dir, f"chunk_{i}.mp3")
            success = self._generate_single_audio_chunk(chunk, output_path, lang_config, lang_code)
            if success:
                audio_chunks_paths.append(output_path)
        
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

# Rewrite functionality
    def add_to_rewrite_queue(self):
        # --- Універсальна логіка для мов та налаштувань ---
        selected_langs = [code for code, var in self.rewrite_lang_checkbuttons.items() if var.get()]
        if not selected_langs:
            messagebox.showwarning(self._t('warning_title'), self._t('warning_no_lang'))
            return

        output_cfg = self.config.get("output_settings", {})
        if not output_cfg.get("rewrite_default_dir") or not os.path.isdir(output_cfg.get("rewrite_default_dir")):
            messagebox.showwarning(self._t('warning_title'), self._t('warning_invalid_rewrite_dir'))
            return

        tasks_to_add = []
        
        # --- Обробка посилань з текстового поля ---
        links_text = self.rewrite_links_text.get("1.0", tk.END).strip()
        if links_text:
            links = [link.strip() for link in links_text.split('\n') if link.strip()]
            for link in links:
                task_name = f"{self._t('rewrite_task_prefix')}: {link}"
                steps = {lang: {key: var.get() for key, var in self.rewrite_lang_step_vars[lang].items()} for lang in selected_langs}
                
                task_config = {
                    "type": "Rewrite", "source_type": "url", "task_name": task_name, "url": link,
                    "selected_langs": selected_langs, "steps": steps, "timestamp": time.time(),
                }
                tasks_to_add.append(task_config)

        # --- Обробка локальних файлів ---
        video_folder = os.path.join(APP_BASE_PATH, "video")
        if not os.path.isdir(video_folder):
            os.makedirs(video_folder)
            messagebox.showinfo(self._t('folder_created_title'), self._t('folder_created_message'))
        else:
            self.processed_links = self.load_processed_links()
            for filename in os.listdir(video_folder):
                if filename.lower().endswith(".mp3") and filename not in self.processed_links:
                    file_path = os.path.join(video_folder, filename)
                    task_name = f"{self._t('rewrite_task_prefix')}: {os.path.splitext(filename)[0]}"
                    steps = {lang: {key: var.get() for key, var in self.rewrite_lang_step_vars[lang].items()} for lang in selected_langs}

                    task_config = {
                        "type": "Rewrite", "source_type": "local_file", "task_name": task_name,
                        "mp3_path": file_path, "original_filename": filename, "selected_langs": selected_langs,
                        "steps": steps, "timestamp": time.time(),
                    }
                    tasks_to_add.append(task_config)

        # --- Фінальне повідомлення та оновлення ---
        if tasks_to_add:
            # Додаємо всі нові завдання на початок черги, зберігаючи їх порядок
            self.task_queue = tasks_to_add + self.task_queue
            self.update_queue_display()
            # messagebox.showinfo(self._t('queue_title'), self._t('info_new_tasks_added', count=len(tasks_to_add)))
        else:
            messagebox.showinfo(self._t('queue_title'), self._t('info_no_new_files_or_links'))

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
                    image_future = executor.submit(self.workflow_manager._image_generation_worker, image_prompts, images_folder, lang_name, task_num, total_tasks)
                
                final_audio_chunks = []
                if audio_future:
                    final_audio_chunks = audio_future.result()
                    
                subs_chunk_paths = []
                if steps.get('create_subtitles') and final_audio_chunks:
                    subs_chunk_paths = self.workflow_manager._sequential_subtitle_worker(final_audio_chunks, subs_chunk_dir)

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
                video_futures = {executor.submit(video_chunk_worker, self, list(image_chunks[i]), final_audio_chunks[i], subs_chunk_paths[i], os.path.join(video_chunk_dir, f"video_chunk_{i}.mp4"), i + 1, len(final_audio_chunks)): i for i in range(len(final_audio_chunks))}
                for f in concurrent.futures.as_completed(video_futures):
                    result = f.result()
                    if result: video_chunk_paths.append(result)
            
            if len(video_chunk_paths) == len(final_audio_chunks):
                final_video_path = os.path.join(lang_output_path, f"video_{sanitize_filename(video_title)}_{lang_code}.mp4")
                if concatenate_videos(self, sorted(video_chunk_paths), final_video_path):
                    logger.info(f"Successfully created final video: {final_video_path}")
                    self._send_telegram_notification('create_video', lang_name, task_num, total_tasks)
            
        finally:
             if not keep_temp_files and os.path.exists(temp_dir):
                 self.update_progress(self._t('phase_cleaning_up'))
                 shutil.rmtree(temp_dir)
                 logger.info(f"Cleaned up temp directory: {temp_dir}")

    def clear_user_logs(self):
        """Очищує логи поточного користувача."""
        clear_user_logs(self)

    def clear_user_images(self):
        """Очищує зображення поточного користувача."""
        clear_user_images(self)

    def refresh_user_stats(self):
        """Оновлює статистику поточного користувача та відображення User ID."""
        refresh_user_stats(self)

    def refresh_firebase_stats(self):
        """Оновлює статистику Firebase."""
        refresh_firebase_stats(self)

    def clear_firebase_logs(self):
        """Очищає логи Firebase."""
        clear_firebase_logs(self)

    def clear_firebase_images(self):
        """Очищає зображення Firebase."""
        clear_firebase_images(self)\
    
    def update_progress_for_montage(self, message, task_key=None, chunk_index=None, progress=None):
        logger.info(f"[Montage Progress] {message}")
        if task_key is not None and chunk_index is not None and progress is not None:
            with self.video_progress_lock:
                if task_key not in self.video_chunk_progress:
                    self.video_chunk_progress[task_key] = {}
                self.video_chunk_progress[task_key][chunk_index] = progress

    def start_periodic_progress_update(self):
        """Запускає таймер для періодичного оновлення GUI."""
        self._update_video_progress_display_periodic()
        # Плануємо наступний виклик через 5 секунд
        self.root.after(5000, self.start_periodic_progress_update)

    def _update_video_progress_display_periodic(self):
        """Оновлює відображення черг, якщо вони в процесі обробки."""
        if self.is_processing_queue:
            self.update_queue_display()

    def _get_unified_step_status(self, task_index, lang_code, step_key, task_type):
        """Отримує статус конкретного кроку з єдиної логіки."""
        if not hasattr(self, 'task_completion_status'):
            return ""

        is_rewrite = task_type == 'Rewrite'
        status_key_prefix = "rewrite_" if is_rewrite else ""
        status_key = f"{status_key_prefix}{task_index}_{lang_code}"

        if status_key not in self.task_completion_status:
            return ""

        status_info = self.task_completion_status[status_key]
        step_name_key_map = {
            'translate': self._t('step_name_translate'),
            'cta': self._t('step_name_cta'),
            'gen_prompts': self._t('step_name_gen_prompts'),
            'gen_images': self._t('step_name_gen_images'),
            'audio': self._t('step_name_audio'),
            'create_subtitles': self._t('step_name_create_subtitles'),
            'create_video': self._t('step_name_create_video'),
            'download': self._t('step_name_download'),
            'transcribe': self._t('step_name_transcribe'),
            'rewrite': self._t('step_name_rewrite_text'),
        }
        step_name_key = step_name_key_map.get(step_key)
        
        if not step_name_key:
            return "" # Невідомий крок

        status = status_info.get('steps', {}).get(step_name_key, "")

        # Спеціальна логіка для кроків з лічильником
        if step_key == 'gen_images':
            # Статус для gen_images тепер встановлюється напряму в воркері,
            # тому просто повертаємо його.
            return status

        elif step_key == 'audio':
            total = status_info.get('total_audio', 0)
            done = status_info.get('audio_generated', 0)
            return f"{done}/{total}" if total > 0 else status

        elif step_key == 'create_subtitles':
            total = status_info.get('total_subs', 0)
            done = status_info.get('subs_generated', 0)
            return f"{done}/{total}" if total > 0 else status
        
        elif step_key == 'create_video':
            if status == "В процесі":
                with self.video_progress_lock:
                    task_key_tuple = (task_index, lang_code)
                    progress_dict = self.video_chunk_progress.get(task_key_tuple, {})
                    if progress_dict:
                        valid_progress_values = [v for v in progress_dict.values() if isinstance(v, (int, float))]
                        if valid_progress_values:
                            avg_progress = sum(valid_progress_values) / len(valid_progress_values)
                            return f"{avg_progress:.1f}%"
                        else:
                            return "0.0%"
                    else:
                        return "0.0%"
            elif status == "Готово":
                return "100.0%" # Залишаємо 100% після завершення
            return status

        # Для всіх інших кроків просто повертаємо їх текстовий статус
        return status

    def increment_and_update_progress(self, queue_type='main'):
        """Збільшує лічильник виконаних кроків та оновлює прогрес-бар."""
        self.completed_individual_steps += 1
        self.update_individual_progress(queue_type)

    def update_individual_progress(self, queue_type='main'):
        """Обчислює та встановлює відсоток виконання для прогрес-бару та тексту."""
        if self.total_individual_steps > 0:
            progress_percent = min(100.0, (self.completed_individual_steps / self.total_individual_steps) * 100.0)
        else:
            progress_percent = 0.0

        # Використовуємо єдиний прогрес-бар для всіх типів черг, оскільки вкладка одна
        progress_var = self.progress_var
        label_var = self.progress_label_var

        # Оновлюємо GUI в основному потоці
        self.root.after(0, lambda: progress_var.set(progress_percent))
        self.root.after(0, lambda: label_var.set(f"{int(progress_percent)}%"))

if __name__ == "__main__":
    """Main entry point for the Content Translation and Generation Application.
    
    This application provides a comprehensive workflow for:
    - Text translation using OpenRouter API
    - Image generation with Pollinations/Recraft APIs
    - Text-to-speech conversion with multiple providers
    - Video montage and subtitle creation
    - Firebase integration for remote control
    - Telegram notifications and reporting
    """
    # Configure Windows console for UTF-8 support
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