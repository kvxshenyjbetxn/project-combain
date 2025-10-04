"""
Speechify utility functions for the translation application.
"""

import tkinter.messagebox as messagebox
from api.speechify_api import SpeechifyAPI


def test_speechify_connection(app):
    """Test Speechify API connection functionality."""
    api_key = app.speechify_api_key_var.get()
    temp_config = {"speechify": {"api_key": api_key}}
    temp_api = SpeechifyAPI(temp_config)
    success, message = temp_api.test_connection()
    if success:
        messagebox.showinfo(app._t('test_connection_title_speechify'), message)
    else:
        messagebox.showerror(app._t('test_connection_title_speechify'), message)
