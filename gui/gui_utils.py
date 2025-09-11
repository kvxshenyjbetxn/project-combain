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


def create_scrollable_tab(app, parent_tab):
    """Create a scrollable tab with dynamic theming."""
    theme_name = app.root.style.theme_use()
    if theme_name == 'cyborg': 
        canvas_bg = "#060606"
    elif theme_name == 'darkly': 
        canvas_bg = "#222222"
    else: 
        canvas_bg = "#ffffff"

    canvas = tk.Canvas(parent_tab, highlightthickness=0, bg=canvas_bg)
    scrollbar = ttk.Scrollbar(parent_tab, orient="vertical", command=canvas.yview)
    app.dynamic_scrollbars.append(scrollbar)

    scrollable_frame = ttk.Frame(canvas)
    frame_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

    def configure_canvas(event):
        # ВИПРАВЛЕНО: Прибираємо умову і завжди розтягуємо внутрішній фрейм
        # на всю ширину канвасу. Це робить поведінку стабільною.
        canvas.itemconfig(frame_id, width=event.width)
        canvas.configure(scrollregion=canvas.bbox("all"))

    def configure_scrollable_frame(event):
        # Оновлюємо скролрегіон, коли змінюється розмір контенту
        canvas.configure(scrollregion=canvas.bbox("all"))

    canvas.bind('<Configure>', configure_canvas)
    scrollable_frame.bind('<Configure>', configure_scrollable_frame)
    
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    app.scrollable_canvases.append(canvas)
    return canvas, scrollable_frame


def create_scrolled_text(app, parent, **kwargs):
    """Create a scrolled text widget with dynamic theming."""
    container = ttk.Frame(parent)
    scrollbar = ttk.Scrollbar(container, orient="vertical")
    app.dynamic_scrollbars.append(scrollbar)
    text_widget = tk.Text(container, yscrollcommand=scrollbar.set, **kwargs)
    scrollbar.config(command=text_widget.yview)
    scrollbar.pack(side="right", fill="y")
    text_widget.pack(side="left", fill="both", expand=True)
    return text_widget, container


class CustomAskStringDialog(tk.Toplevel):
    """Custom dialog for string input with app-specific styling and bindings."""
    
    def __init__(self, parent, title, prompt, app_instance, initial_value=""):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.app = app_instance 
        self.result = None
        body = ttk.Frame(self)
        self.initial_focus = self.body(body, prompt, initial_value)
        body.pack(padx=10, pady=10)
        self.buttonbox()
        self.grab_set()
        if not self.initial_focus:
            self.initial_focus = self
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        self.initial_focus.focus_set()
        self.wait_window(self)

    def body(self, master, prompt, initial_value=""):
        ttk.Label(master, text=prompt).pack(pady=(0, 5))
        self.entry = ttk.Entry(master, width=50)
        self.entry.pack(pady=(0, 10))
        self.entry.insert(0, initial_value)
        add_text_widget_bindings(self.app, self.entry)
        return self.entry

    def buttonbox(self):
        box = ttk.Frame(self)
        ok_button = ttk.Button(box, text=self.app._t('ok_button'), width=10, command=self.ok, bootstyle="success")
        ok_button.pack(side=tk.LEFT, padx=5, pady=5)
        cancel_button = ttk.Button(box, text=self.app._t('cancel_button'), width=10, command=self.cancel, bootstyle="secondary")
        cancel_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def ok(self, event=None):
        if self.entry:
            self.result = self.entry.get()
        self.withdraw()
        self.update_idletasks()
        self.destroy()

    def cancel(self, event=None):
        self.result = None
        self.destroy()


class AskTemplateDialog(tk.Toplevel):
    """Dialog for selecting templates from a predefined list."""
    
    def __init__(self, parent, title, templates, app_instance):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.app = app_instance
        self.result = None
        
        body = ttk.Frame(self)
        self.initial_focus = self.body(body, templates)
        body.pack(padx=10, pady=10)
        
        self.buttonbox()
        self.grab_set()
        
        if not self.initial_focus:
            self.initial_focus = self
        
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        self.initial_focus.focus_set()
        self.wait_window(self)

    def body(self, master, templates):
        ttk.Label(master, text=self.app._t('select_template_prompt')).pack(pady=(0, 5))
        self.template_var = tk.StringVar()
        if templates:
            self.template_var.set(templates[0])
        self.combobox = ttk.Combobox(master, textvariable=self.template_var, values=templates, state="readonly", width=40)
        self.combobox.pack(pady=(0, 10))
        return self.combobox

    def buttonbox(self):
        box = ttk.Frame(self)
        ok_button = ttk.Button(box, text="OK", width=10, command=self.ok, bootstyle="success")
        ok_button.pack(side=tk.LEFT, padx=5, pady=5)
        cancel_button = ttk.Button(box, text=self.app._t('cancel_button'), width=10, command=self.cancel, bootstyle="secondary")
        cancel_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def ok(self, event=None):
        self.result = self.template_var.get()
        self.destroy()

    def cancel(self, event=None):
        self.destroy()

class AdvancedRegenerateDialog(tk.Toplevel):
    """Advanced dialog for image regeneration with prompt editing and service selection."""
    
    def __init__(self, parent, title, app_instance, initial_prompt=""):
        super().__init__(parent)
        self.transient(parent)
        self.title(title)
        self.app = app_instance
        self.result = None

        body = ttk.Frame(self)
        self.initial_focus = self.body(body, initial_prompt)
        body.pack(padx=10, pady=10, fill="both", expand=True)

        self.buttonbox()
        self.grab_set()

        self.protocol("WM_DELETE_WINDOW", self.cancel)
        parent.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"600x400+{x}+{y}")
        self.initial_focus.focus_set()
        self.wait_window(self)

    def body(self, master, initial_prompt):
        master.columnconfigure(1, weight=1)

        # Prompt Entry
        ttk.Label(master, text=self.app._t('prompt_label')).grid(row=0, column=0, sticky='nw', padx=5, pady=5)
        self.prompt_text, text_container = create_scrolled_text(self.app, master, height=10, width=60)
        text_container.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        master.rowconfigure(0, weight=1)
        self.prompt_text.insert(tk.END, initial_prompt)
        add_text_widget_bindings(self.app, self.prompt_text)

        # API Service Selector
        ttk.Label(master, text=self.app._t('service_label')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.api_var = tk.StringVar(value=self.app.config.get("ui_settings", {}).get("image_generation_api", "pollinations"))
        api_combo = ttk.Combobox(master, textvariable=self.api_var, values=["pollinations", "recraft"], state="readonly")
        api_combo.grid(row=1, column=1, sticky="ew", padx=5, pady=5)
        api_combo.bind("<<ComboboxSelected>>", self.update_model_options)

        # Model Options Frame
        self.model_frame = ttk.Frame(master)
        self.model_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        self.model_frame.columnconfigure(1, weight=1)
        self.update_model_options()

        return self.prompt_text

    def update_model_options(self, event=None):
        for widget in self.model_frame.winfo_children():
            widget.destroy()

        service = self.api_var.get()
        if service == "pollinations":
            ttk.Label(self.model_frame, text=self.app._t('model_label')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
            self.poll_model_var = tk.StringVar(value=self.app.config["pollinations"]["model"])
            poll_model_dropdown = ttk.Combobox(self.model_frame, textvariable=self.poll_model_var, values=self.app.poll_available_models, state="readonly")
            poll_model_dropdown.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
        elif service == "recraft":
            ttk.Label(self.model_frame, text=self.app._t('recraft_model_label')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
            self.recraft_model_var = tk.StringVar(value=self.app.config["recraft"]["model"])
            recraft_model_combo = ttk.Combobox(self.model_frame, textvariable=self.recraft_model_var, values=["recraftv3", "recraftv2"], state="readonly")
            recraft_model_combo.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
            
            ttk.Label(self.model_frame, text=self.app._t('recraft_style_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
            self.recraft_style_var = tk.StringVar(value=self.app.config["recraft"]["style"])
            recraft_style_combo = ttk.Combobox(self.model_frame, textvariable=self.recraft_style_var, values=["realistic_image", "digital_illustration", "vector_illustration", "icon", "logo_raster"], state="readonly")
            recraft_style_combo.grid(row=1, column=1, sticky='ew', padx=5, pady=2)

    def buttonbox(self):
        box = ttk.Frame(self)
        ok_button = ttk.Button(box, text="OK", width=10, command=self.ok, bootstyle="success")
        ok_button.pack(side=tk.LEFT, padx=5, pady=5)
        cancel_button = ttk.Button(box, text=self.app._t('cancel_button'), width=10, command=self.cancel, bootstyle="secondary")
        cancel_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack(pady=5)

    def ok(self, event=None):
        self.result = {
            "prompt": self.prompt_text.get("1.0", tk.END).strip(),
            "service": self.api_var.get()
        }
        if self.result["service"] == "pollinations":
            self.result["model"] = self.poll_model_var.get()
        elif self.result["service"] == "recraft":
            self.result["model"] = self.recraft_model_var.get()
            self.result["style"] = self.recraft_style_var.get()
        self.destroy()

    def cancel(self, event=None):
        self.destroy()