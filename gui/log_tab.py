import tkinter as tk
import ttkbootstrap as ttk
import logging
import re

from .gui_utils import add_text_widget_bindings

# Отримуємо існуючий логер, створений у головному файлі
logger = logging.getLogger("TranslationApp")

def create_log_tab(notebook, app):
    """
    Створює вкладку "Лог" та всі її елементи.
    'notebook' - це головний записник, куди буде додано вкладку.
    'app' - це посилання на головний клас програми для доступу до його функцій та змінних.
    """
    main_log_frame = ttk.Labelframe(app.log_frame, text=app._t('main_log_label'))
    main_log_frame.pack(fill='both', expand=True, padx=5, pady=(5, 2))

    app.log_text, text_container_widget = app._create_scrolled_text(main_log_frame, state='disabled', font=("Courier New", 9))
    text_container_widget.pack(fill='both', expand=True, padx=5, pady=5)
    add_text_widget_bindings(app, app.log_text)

    # Створюємо фрейм для кнопок
    log_buttons_frame = ttk.Frame(app.log_frame)
    log_buttons_frame.pack(pady=5)

    skip_image_button_log = ttk.Button(
        log_buttons_frame,
        text=app._t('skip_image_button'),
        command=app._on_skip_image_click,
        bootstyle="warning",
        state="disabled"
    )
    skip_image_button_log.pack(side='left', padx=5)
    app.skip_image_buttons.append(skip_image_button_log)

    # Нова кнопка для перемикання сервісу
    switch_service_button_log = ttk.Button(
        log_buttons_frame,
        text=app._t('switch_service_button'),
        command=app._on_switch_service_click,
        bootstyle="info",
        state="disabled"
    )
    switch_service_button_log.pack(side='left', padx=5)
    app.switch_service_buttons.append(switch_service_button_log)

    # --- Нова кнопка регенерації іншим сервісом ---
    regenerate_alt_button_log = ttk.Button(
        log_buttons_frame,
        text=app._t('regenerate_alt_button'),
        command=app._on_regenerate_alt_click,
        bootstyle="success",
        state="disabled"
    )
    regenerate_alt_button_log.pack(side='left', padx=5)
    app.regenerate_alt_buttons.append(regenerate_alt_button_log)

    # --- Новий вибір API ---
    ttk.Label(log_buttons_frame, text=f"{app._t('image_api_label')}:").pack(side='left', padx=(10, 2))
    image_api_combo_log = ttk.Combobox(
        log_buttons_frame, 
        textvariable=app.active_image_api_var, 
        values=["pollinations", "recraft"], 
        state="readonly",
        width=12
    )
    image_api_combo_log.pack(side='left', padx=5)
    image_api_combo_log.bind("<<ComboboxSelected>>", app._on_image_api_select)
    app.image_api_selectors.append(image_api_combo_log)

    parallel_container_frame = ttk.Labelframe(app.log_frame, text=app._t('parallel_log_label'))
    parallel_container_frame.pack(fill='both', expand=True, padx=5, pady=(2, 5))

    num_chunks = app.config.get('parallel_processing', {}).get('num_chunks', 3)
    app.parallel_log_widgets = []

    for i in range(num_chunks):
        parallel_container_frame.grid_columnconfigure(i, weight=1)
        
        chunk_frame = ttk.Frame(parallel_container_frame)
        chunk_frame.grid(row=0, column=i, sticky="nsew", padx=2, pady=2)
        
        parallel_container_frame.grid_rowconfigure(0, weight=1)

        ttk.Label(chunk_frame, text=app._t('thread_label', thread_num=i + 1), bootstyle="secondary").pack(fill='x')
        
        log_widget, text_container_widget = app._create_scrolled_text(chunk_frame, state='disabled', font=("Courier New", 8))
        text_container_widget.pack(fill='both', expand=True)
        add_text_widget_bindings(app, log_widget)
        app.parallel_log_widgets.append(log_widget)

    class ContextFilter(logging.Filter):
        def filter(self, record):
            if hasattr(app.log_context, 'parallel_task'):
                record.parallel_task = app.log_context.parallel_task
                record.worker_id = app.log_context.worker_id
            return True

    class MasterLogHandler(logging.Handler):
        def __init__(self, main_text_widget, parallel_widgets, app_instance):
            super().__init__()
            self.main_text_widget = main_text_widget
            self.parallel_widgets = parallel_widgets
            self.app = app_instance
            self.worker_id_re = re.compile(r'Chunk (\d+)')

        def emit(self, record):
            try:
                if hasattr(record, 'worker_id'):
                    self.handle_parallel_log(record)
                else:
                    self.handle_main_log(record)
            except RuntimeError as e:
                if "main thread is not in main loop" in str(e):
                    # Це очікувана помилка при закритті, просто ігноруємо її
                    pass
                else:
                    # Інша, неочікувана помилка RuntimeError
                    print(f"Unexpected RuntimeError in MasterLogHandler: {e}")
            except Exception as e:
                # Будь-яка інша помилка
                print(f"Unexpected error in MasterLogHandler: {e}")

        def handle_main_log(self, record):
            msg = self.format(record)

            # Відправляємо лог у Firebase, якщо API ініціалізовано
            if hasattr(self.app, 'firebase_api') and self.app.firebase_api.is_initialized:
                self.app.firebase_api.send_log_in_thread(msg)

            def append_text():
                self.main_text_widget.configure(state='normal')
                self.main_text_widget.insert(tk.END, msg + '\n')
                self.main_text_widget.configure(state='disabled')
                self.main_text_widget.see(tk.END)
            self.main_text_widget.after(0, append_text)

        def handle_parallel_log(self, record):
            worker_id_str = getattr(record, 'worker_id', '')
            match = self.worker_id_re.search(worker_id_str)
            
            if not match:
                self.handle_main_log(record)
                return

            worker_index = int(match.group(1)) - 1
            if not (0 <= worker_index < len(self.parallel_widgets)):
                self.handle_main_log(record)
                return
            
            target_widget = self.parallel_widgets[worker_index]
            msg = record.getMessage()

            def update_widget():
                target_widget.configure(state='normal')
                clean_msg = msg.replace("PROGRESS::", "").strip()
                target_widget.insert(tk.END, clean_msg + '\n')
                target_widget.configure(state='disabled')
                target_widget.see(tk.END)

            target_widget.after(0, update_widget)

    if not app.gui_log_handler:
        app.gui_log_handler = MasterLogHandler(app.log_text, app.parallel_log_widgets, app)
        app.gui_log_handler.setLevel(logging.INFO)
        app.gui_log_handler.addFilter(ContextFilter())
        formatter = logging.Formatter('%(message)s')
        app.gui_log_handler.setFormatter(formatter)
        logger.addHandler(app.gui_log_handler)
        logger.info(app._t('log_program_started'))