# utils/pollinations_utils.py

import logging
from tkinter import messagebox
from api.pollinations_api import PollinationsAPI

logger = logging.getLogger(__name__)

def test_pollinations_connection(app_instance):
    """Test Pollinations API connection and display result."""
    token = app_instance.poll_token_var.get()
    model = app_instance.poll_model_var.get()
    temp_config = app_instance.config.copy()
    temp_config["pollinations"]["token"] = token
    temp_config["pollinations"]["model"] = model
    temp_api = PollinationsAPI(temp_config, app_instance)
    success, message = temp_api.test_connection()
    if success:
        messagebox.showinfo(app_instance._t('test_connection_title_poll'), message)
    else:
        messagebox.showerror(app_instance._t('test_connection_title_poll'), message)
