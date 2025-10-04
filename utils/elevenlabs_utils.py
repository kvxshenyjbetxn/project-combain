# utils/elevenlabs_utils.py

import logging
import tkinter as tk
from tkinter import messagebox

logger = logging.getLogger(__name__)

def update_elevenlabs_balance_labels(app_instance, new_balance):
    """Update ElevenLabs balance labels across all tabs in the GUI."""
    balance_text = new_balance if new_balance is not None else 'N/A'
    
    # Update balance labels using the app instance's root and translation method
    app_instance.root.after(0, lambda: app_instance.settings_el_balance_label.config(text=f"{app_instance._t('balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.chain_el_balance_label.config(text=f"{app_instance._t('elevenlabs_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.rewrite_el_balance_label.config(text=f"{app_instance._t('elevenlabs_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.queue_el_balance_label.config(text=f"{app_instance._t('elevenlabs_balance_label')}: {balance_text}"))
    
    logger.info(f"Інтерфейс оновлено: баланс ElevenLabs тепер {balance_text}")

def test_elevenlabs_connection(app_instance):
    """Test ElevenLabs API connection and update interface with results."""
    from api.elevenlabs_api import ElevenLabsAPI
    
    api_key = app_instance.el_api_key_var.get()
    temp_config = app_instance.config.copy()
    temp_config["elevenlabs"]["api_key"] = api_key
    temp_api = ElevenLabsAPI(temp_config)
    success, message = temp_api.test_connection()
    if success:
        app_instance.el_api = temp_api
        balance_text = app_instance.el_api.balance if app_instance.el_api.balance is not None else 'N/A'
        app_instance.settings_el_balance_label.config(text=f"{app_instance._t('balance_label')}: {balance_text}")
        messagebox.showinfo(app_instance._t('test_connection_title_el'), message)
    else:
        messagebox.showerror(app_instance._t('test_connection_title_el'), message)

def update_elevenlabs_info(app_instance, update_templates=True):
    """Update ElevenLabs API information including balance and templates."""
    balance = app_instance.el_api.update_balance()
    balance_text = balance if balance is not None else 'N/A'
    
    # Безпечно оновлюємо GUI тільки якщо головний цикл активний
    try:
        app_instance.root.after(0, lambda: app_instance.settings_el_balance_label.config(text=f"{app_instance._t('balance_label')}: {balance_text}"))
        app_instance.root.after(0, lambda: app_instance.chain_el_balance_label.config(text=f"{app_instance._t('elevenlabs_balance_label')}: {balance_text}"))
        app_instance.root.after(0, lambda: app_instance.rewrite_el_balance_label.config(text=f"{app_instance._t('elevenlabs_balance_label')}: {balance_text}"))
        app_instance.root.after(0, lambda: app_instance.queue_el_balance_label.config(text=f"{app_instance._t('elevenlabs_balance_label')}: {balance_text}"))
    except RuntimeError:
        # Ігноруємо помилки якщо головний цикл ще не готовий
        pass
    
    templates_len = "N/A"
    if update_templates:
        templates = app_instance.el_api.update_templates()
        if templates:
            templates_len = len(templates)
    elif app_instance.el_api.templates:
        templates_len = len(app_instance.el_api.templates)
