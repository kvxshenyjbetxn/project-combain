# utils/openrouter_utils.py

import logging
import tkinter as tk
from tkinter import messagebox
from api.openrouter_api import OpenRouterAPI
from gui.gui_utils import CustomAskStringDialog

logger = logging.getLogger(__name__)

def update_openrouter_balance_labels(app_instance, new_balance):
    """Update OpenRouter balance labels across all tabs in the GUI."""
    balance_text = new_balance if new_balance is not None else 'N/A'
    
    # Update balance labels using the app instance's root and translation method
    app_instance.root.after(0, lambda: app_instance.settings_or_balance_label.config(text=f"{app_instance._t('openrouter_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.chain_or_balance_label.config(text=f"{app_instance._t('openrouter_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.rewrite_or_balance_label.config(text=f"{app_instance._t('openrouter_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.queue_or_balance_label.config(text=f"{app_instance._t('openrouter_balance_label')}: {balance_text}"))
    
    logger.info(f"Інтерфейс оновлено: баланс OpenRouter тепер {balance_text}")

def reset_openrouter_balance(app_instance):
    """Reset OpenRouter balance by fetching fresh data from API."""
    if not app_instance.or_api.api_key:
        logger.warning("OpenRouter -> Ключ API не встановлено, неможливо скинути баланс.")
        return
    
    # Отримуємо свіжий баланс
    balance = app_instance.or_api.get_balance()
    # Оновлюємо лейбли
    update_openrouter_balance_labels(app_instance, balance)
    logger.info("OpenRouter баланс скинуто та оновлено.")

def test_openrouter_connection(app_instance):
    """Test OpenRouter API connection and display result."""
    api_key = app_instance.or_api_key_var.get()
    temp_config = app_instance.config.copy()
    temp_config["openrouter"]["api_key"] = api_key
    temp_api = OpenRouterAPI(temp_config)
    success, message = temp_api.test_connection()
    if success:
        # Якщо з'єднання успішне, отримуємо і оновлюємо баланс
        balance = temp_api.get_balance()
        update_openrouter_balance_labels(app_instance, balance)
        messagebox.showinfo(app_instance._t('test_connection_title_or'), f"{message}\n{app_instance._t('balance_label')}: {balance if balance else 'N/A'}")
    else:
        messagebox.showerror(app_instance._t('test_connection_title_or'), message)

def populate_openrouter_widgets(app_instance):
    """Populate OpenRouter widgets with saved models."""
    models = app_instance.config["openrouter"].get("saved_models", [])
    app_instance.or_models_listbox.delete(0, tk.END)
    for model in models:
        app_instance.or_models_listbox.insert(tk.END, model)
    app_instance.or_trans_model_combo['values'] = models
    app_instance.or_prompt_model_combo['values'] = models
    app_instance.or_cta_model_combo['values'] = models
    app_instance.or_rewrite_model_combo['values'] = models

def add_openrouter_model(app_instance):
    """Add a new OpenRouter model to the configuration."""
    dialog = CustomAskStringDialog(app_instance.root, app_instance._t('add_model_title'), app_instance._t('add_model_prompt'), app_instance)
    new_model = dialog.result
    if new_model:
        models = app_instance.config["openrouter"].get("saved_models", [])
        if new_model not in models:
            models.append(new_model)
            app_instance.config["openrouter"]["saved_models"] = models
            populate_openrouter_widgets(app_instance)
        else:
            messagebox.showwarning(app_instance._t('warning_title'), app_instance._t('warning_model_exists'))

def remove_openrouter_model(app_instance):
    """Remove selected OpenRouter model from the configuration."""
    selected_indices = app_instance.or_models_listbox.curselection()
    if not selected_indices:
        messagebox.showwarning(app_instance._t('warning_title'), app_instance._t('warning_select_model_to_remove'))
        return
    selected_model = app_instance.or_models_listbox.get(selected_indices[0])
    if messagebox.askyesno(app_instance._t('confirm_title'), f"{app_instance._t('confirm_remove_model')} '{selected_model}'?"):
        app_instance.or_models_listbox.delete(selected_indices[0])
        app_instance.config["openrouter"]["saved_models"] = list(app_instance.or_models_listbox.get(0, tk.END))
        populate_openrouter_widgets(app_instance)
