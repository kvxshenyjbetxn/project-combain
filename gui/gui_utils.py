# gui/gui_utils.py
import tkinter as tk
import ttkbootstrap as ttk
import sys
from tkinter import scrolledtext

def add_text_widget_bindings(app, widget):
    widget.bind("<Button-3>", lambda event: create_context_menu(app, event))
    if sys.platform == "darwin":
        widget.bind("<Button-2>", lambda event: create_context_menu(app, event))
        widget.bind("<Control-Button-1>", lambda event: create_context_menu(app, event))

def paste_to_entry(app, widget):
    try:
        clipboard_content = app.root.clipboard_get()
        widget.delete(0, tk.END)
        widget.insert(0, clipboard_content)
    except tk.TclError:
        pass
    return "break"

def create_context_menu(app, event):
    widget = event.widget
    menu = tk.Menu(widget, tearoff=0)
    
    if isinstance(widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Listbox)):
        menu.add_command(label=app._t('context_cut'), command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label=app._t('context_copy'), command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label=app._t('context_paste'), command=lambda: paste_to_entry(app, widget))
    elif isinstance(widget, (scrolledtext.ScrolledText, tk.Text)):
        menu.add_command(label=app._t('context_cut'), command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label=app._t('context_copy'), command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label=app._t('context_paste'), command=lambda: widget.event_generate("<<Paste>>"))
    
    menu.tk_popup(event.x_root, event.y_root)