# utils/voicemaker_utils.py

import logging
import tkinter as tk
from tkinter import messagebox

logger = logging.getLogger(__name__)

def update_voicemaker_balance_labels(app_instance, new_balance):
    """Update VoiceMaker balance labels across all tabs in the GUI."""
    balance_text = new_balance if new_balance is not None else 'N/A'
    
    # Update balance labels using the app instance's root and translation method
    app_instance.root.after(0, lambda: app_instance.settings_vm_balance_label.config(text=f"{app_instance._t('balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.chain_vm_balance_label.config(text=f"{app_instance._t('voicemaker_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.rewrite_vm_balance_label.config(text=f"{app_instance._t('voicemaker_balance_label')}: {balance_text}"))
    app_instance.root.after(0, lambda: app_instance.queue_vm_balance_label.config(text=f"{app_instance._t('voicemaker_balance_label')}: {balance_text}"))
    
    logger.info(f"Інтерфейс оновлено: баланс VoiceMaker тепер {balance_text}")

def test_voicemaker_connection(app_instance):
    """Test Voicemaker API connection and update interface with results."""
    from api.voicemaker_api import VoiceMakerAPI
    from utils import save_config
    
    api_key = app_instance.vm_api_key_var.get()
    temp_config = {"voicemaker": {"api_key": api_key}}
    temp_api = VoiceMakerAPI(temp_config)
    balance = temp_api.get_balance()
    if balance is not None:
        if 'voicemaker' not in app_instance.config: 
            app_instance.config['voicemaker'] = {}
        app_instance.config['voicemaker']['last_known_balance'] = balance
        save_config(app_instance.config)
        
        # Використовуємо нову utility функцію для оновлення лейблів
        update_voicemaker_balance_labels(app_instance, balance)
        
        message = f"З'єднання з Voicemaker успішне.\nЗалишилось символів: {balance}"
        messagebox.showinfo(app_instance._t('test_connection_title_vm'), message)
    else:
        message = "Не вдалося перевірити з'єднання або отримати баланс Voicemaker."
        messagebox.showerror(app_instance._t('test_connection_title_vm'), message)
