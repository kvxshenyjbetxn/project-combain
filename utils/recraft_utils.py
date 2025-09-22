# utils/recraft_utils.py

import logging
import tkinter as tk
from tkinter import messagebox
from constants.recraft_substyles import RECRAFT_SUBSTYLES

logger = logging.getLogger(__name__)

def update_recraft_balance_labels(app_instance, new_balance):
    """Update Recraft balance labels across all tabs in the GUI."""
    balance_text = new_balance if new_balance is not None else 'N/A'
    
    # Update balance labels using the app instance's root and translation method
    app_instance.root.after(0, lambda: app_instance.settings_recraft_balance_label.config(text=f"{app_instance._t('balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.chain_recraft_balance_label.config(text=f"{app_instance._t('recraft_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.rewrite_recraft_balance_label.config(text=f"{app_instance._t('recraft_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.queue_recraft_balance_label.config(text=f"{app_instance._t('recraft_balance_label')}: {balance_text}"))
    
    logger.info(f"Інтерфейс оновлено: баланс Recraft тепер {balance_text}")

def test_recraft_connection(app_instance):
    """Test Recraft API connection and display results."""
    from api.recraft_api import RecraftAPI
    
    api_key = app_instance.recraft_api_key_var.get()
    temp_config = {"recraft": {"api_key": api_key}}
    temp_api = RecraftAPI(temp_config)
    success, message = temp_api.test_connection()
    if success:
        messagebox.showinfo(app_instance._t('test_connection_title_recraft'), message)
    else:
        messagebox.showerror(app_instance._t('test_connection_title_recraft'), message)

def update_recraft_substyles(app_instance, event=None):
    """Update available Recraft substyles based on selected model and style."""
    selected_model = app_instance.recraft_model_var.get()
    selected_style = app_instance.recraft_style_var.get()
    substyles = RECRAFT_SUBSTYLES.get(selected_model, {}).get(selected_style, [])
    current_substyle = app_instance.recraft_substyle_var.get()
    app_instance.recraft_substyle_combo['values'] = substyles
    if not substyles:
        app_instance.recraft_substyle_var.set("")
        app_instance.recraft_substyle_combo.config(state="disabled")
    else:
        app_instance.recraft_substyle_combo.config(state="readonly")
        if current_substyle not in substyles:
            app_instance.recraft_substyle_var.set("")
