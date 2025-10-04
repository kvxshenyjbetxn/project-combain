# utils/googler_utils.py

import logging
from tkinter import messagebox
from api.googler_api import GooglerAPI

logger = logging.getLogger(__name__)

def test_googler_connection(app_instance):
    """Test Googler API connection and display result."""
    api_key = app_instance.googler_api_key_var.get()
    temp_config = app_instance.config.copy()
    if 'googler' not in temp_config:
        temp_config['googler'] = {}
    temp_config["googler"]["api_key"] = api_key
    temp_api = GooglerAPI(temp_config)
    success, message = temp_api.test_connection()
    
    # Update usage label if successful
    if success and hasattr(app_instance, 'settings_googler_usage_label'):
        app_instance.root.after(0, lambda: app_instance.settings_googler_usage_label.config(text=f"Usage: {message.split('Usage:')[-1].strip() if 'Usage:' in message else 'N/A'}"))
    
    if success:
        messagebox.showinfo("Googler Connection Test", message)
    else:
        messagebox.showerror("Googler Connection Test", message)
