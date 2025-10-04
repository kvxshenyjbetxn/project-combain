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
        usage_stats = temp_api.get_usage_stats()
        if usage_stats:
            hourly = usage_stats.get('current_usage', {}).get('hourly_usage', {})
            img_usage = hourly.get('image_generation', {})
            current = img_usage.get('current_usage', 'N/A')
            limit = usage_stats.get('account_limits', {}).get('img_gen_per_hour_limit', 'N/A')
            usage_text = f"Images: {current}/{limit} per hour"
            app_instance.root.after(0, lambda: app_instance.settings_googler_usage_label.config(text=usage_text))
        else:
            app_instance.root.after(0, lambda: app_instance.settings_googler_usage_label.config(text="Usage: N/A"))
    
    if success:
        messagebox.showinfo("Googler Connection Test", message)
    else:
        messagebox.showerror("Googler Connection Test", message)

def update_googler_usage_labels(app_instance):
    """Update Googler usage labels on all tabs."""
    usage_stats = app_instance.googler_api.get_usage_stats()
    
    if usage_stats:
        hourly = usage_stats.get('current_usage', {}).get('hourly_usage', {})
        img_usage = hourly.get('image_generation', {})
        current = img_usage.get('current_usage', 'N/A')
        limit = usage_stats.get('account_limits', {}).get('img_gen_per_hour_limit', 'N/A')
        usage_text = f"{current}/{limit}"
        
        # Update all labels
        if hasattr(app_instance, 'chain_googler_balance_label'):
            app_instance.root.after(0, lambda: app_instance.chain_googler_balance_label.config(text=f"Googler Usage: {usage_text}"))
        if hasattr(app_instance, 'rewrite_googler_balance_label'):
            app_instance.root.after(0, lambda: app_instance.rewrite_googler_balance_label.config(text=f"Googler Usage: {usage_text}"))
        if hasattr(app_instance, 'queue_googler_balance_label'):
            app_instance.root.after(0, lambda: app_instance.queue_googler_balance_label.config(text=f"Googler Usage: {usage_text}"))
        if hasattr(app_instance, 'settings_googler_usage_label'):
            app_instance.root.after(0, lambda: app_instance.settings_googler_usage_label.config(text=f"Images: {usage_text} per hour"))
    else:
        usage_text = "N/A"
        if hasattr(app_instance, 'chain_googler_balance_label'):
            app_instance.root.after(0, lambda: app_instance.chain_googler_balance_label.config(text=f"Googler Usage: {usage_text}"))
        if hasattr(app_instance, 'rewrite_googler_balance_label'):
            app_instance.root.after(0, lambda: app_instance.rewrite_googler_balance_label.config(text=f"Googler Usage: {usage_text}"))
        if hasattr(app_instance, 'queue_googler_balance_label'):
            app_instance.root.after(0, lambda: app_instance.queue_googler_balance_label.config(text=f"Googler Usage: {usage_text}"))
        if hasattr(app_instance, 'settings_googler_usage_label'):
            app_instance.root.after(0, lambda: app_instance.settings_googler_usage_label.config(text=f"Usage: {usage_text}"))
