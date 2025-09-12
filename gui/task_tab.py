import tkinter as tk
import ttkbootstrap as ttk
from tkinter import filedialog

from .gui_utils import add_text_widget_bindings

# --- Функції-помічники для віджетів на цій вкладці ---

def on_language_checkbox_toggle(app, lang_code, var):
    if var.get():
        add_language_output_path_widgets(app, lang_code)
    else:
        # ВИПРАВЛЕНО: Тепер ми викликаємо функцію як метод об'єкта 'app'
        app.remove_language_output_path_widgets(lang_code)
    
    # Оновлюємо скрол-регіон після зміни
    if hasattr(app, 'update_scroll_functions'):
        for update_func in app.update_scroll_functions:
            update_func()

def add_language_output_path_widgets(app, lang_code):
    if lang_code in app.lang_widgets:
        return
    
    container_frame = ttk.Frame(app.lang_output_frame)
    container_frame.pack(fill='x', padx=5, pady=2, anchor='w')

    path_frame = ttk.Frame(container_frame)
    path_frame.pack(fill='x')
    
    lang_label = ttk.Label(path_frame, text=f"{lang_code.upper()}:")
    lang_label.pack(side='left')
    path_var = tk.StringVar()
    app.lang_output_path_vars[lang_code] = path_var
    path_entry = ttk.Entry(path_frame, textvariable=path_var, width=50)
    path_entry.pack(side='left', expand=True, fill='x', padx=5)
    add_text_widget_bindings(app, path_entry)
    browse_btn = ttk.Button(path_frame, text=app._t('browse_button'),
                           command=lambda c=lang_code: browse_language_output_path(app, c), bootstyle="secondary-outline")
    browse_btn.pack(side='left', padx=5)
    
    steps_frame = ttk.Frame(container_frame)
    steps_frame.pack(fill='x', padx=20, pady=2)

    app.lang_step_vars[lang_code] = {
        'translate': tk.BooleanVar(value=True),
        'cta': tk.BooleanVar(value=True),
        'gen_prompts': tk.BooleanVar(value=True),
        'gen_images': tk.BooleanVar(value=True),
        'audio': tk.BooleanVar(value=True),
        'create_subtitles': tk.BooleanVar(value=True),
        'create_video': tk.BooleanVar(value=True)
    }
    app.lang_step_checkboxes[lang_code] = {}

    steps = {
        'translate': app._t('step_translate'), 'cta': app._t('step_cta'), 
        'gen_prompts': app._t('step_gen_prompts'), 'gen_images': app._t('step_gen_images'), 
        'audio': app._t('step_audio'),
        'create_subtitles': app._t('step_create_subtitles'),
        'create_video': app._t('step_create_video')
    }

    for key, text in steps.items():
        cb = ttk.Checkbutton(steps_frame, text=text, variable=app.lang_step_vars[lang_code][key],
                            bootstyle="light-round-toggle")
        cb.pack(side='left', padx=5)
        app.lang_step_checkboxes[lang_code][key] = cb
    
    app.lang_widgets[lang_code] = {
        'container': container_frame,
        'entry': path_entry,
        'button': browse_btn
    }
    app.update_path_widgets_state()
    
    # Оновлюємо скрол-регіон після додавання нових елементів
    if hasattr(app, 'update_scroll_functions'):
        for update_func in app.update_scroll_functions:
            update_func()

def browse_language_output_path(app, lang_code):
    folder = filedialog.askdirectory()
    if folder:
        if lang_code in app.lang_output_path_vars:
            app.lang_output_path_vars[lang_code].set(folder)

# --- Головна функція для створення вкладки ---

def create_task_tab(notebook, app):
    """
    Створює вкладку "Створення Завдання" та всі її елементи.
    'notebook' - це головний записник, куди буде додано вкладку.
    'app' - це посилання на головний клас програми для доступу до його функцій та змінних.
    """
    from gui.gui_utils import create_scrollable_tab, create_scrolled_text
    
    app.chain_frame = ttk.Frame(notebook)
    notebook.add(app.chain_frame, text=app._t('create_task_tab'))
    
    app.chain_canvas, app.chain_scrollable_frame = create_scrollable_tab(app, app.chain_frame)
    
    input_frame = ttk.Labelframe(app.chain_scrollable_frame, text=app._t('input_text_label'))
    input_frame.pack(fill='x', expand=True, padx=10, pady=5)
    
    text_info_frame = ttk.Frame(input_frame)
    text_info_frame.pack(fill='x', padx=5, pady=5)
    app.char_count_label = ttk.Label(text_info_frame, text=app._t('chars_label') + ": 0")
    app.char_count_label.pack(side='left')
    
    text_container = ttk.Frame(input_frame)
    text_container.pack(fill="both", expand=True, padx=5, pady=5)

    initial_height = app.config.get("ui_settings", {}).get("main_text_height", 150)
    app.main_text_frame = ttk.Frame(text_container, height=initial_height)
    app.main_text_frame.pack(fill="x", expand=False)
    app.main_text_frame.pack_propagate(False)

    app.input_text, text_container_widget = create_scrolled_text(app, app.main_text_frame, height=10, relief="flat", insertbackground="white")
    text_container_widget.pack(fill='both', expand=True)
    add_text_widget_bindings(app, app.input_text)

    grip = ttk.Frame(text_container, height=8, bootstyle="secondary", cursor="sb_v_double_arrow")
    grip.pack(fill="x")

    def start_resize(event):
        grip.startY = event.y
        grip.start_height = app.main_text_frame.winfo_height()

    def do_resize(event):
        new_height = grip.start_height + (event.y - grip.startY)
        if 50 <= new_height <= app.root.winfo_height() * 0.8:
            app.main_text_frame.config(height=new_height)
            app.chain_canvas.update_idletasks()
            app.chain_canvas.config(scrollregion=app.chain_canvas.bbox("all"))

    grip.bind("<ButtonPress-1>", start_resize)
    grip.bind("<B1-Motion>", do_resize)
    
    app.input_text.bind("<KeyRelease>", app.update_char_count)
    app.input_text.bind("<Button-1>", app.update_char_count)

    lang_sel_frame = ttk.Frame(app.chain_scrollable_frame)
    lang_sel_frame.pack(fill='x', padx=10, pady=5)
    ttk.Label(lang_sel_frame, text=app._t('select_languages_label')).pack(side='left')
    app.lang_checkbuttons = {}
    lang_codes = list(app.config["languages"].keys())
    for i, code in enumerate(lang_codes):
        var = tk.BooleanVar()
        cb = ttk.Checkbutton(lang_sel_frame, text=code.upper(), variable=var,
                            command=lambda c=code, v=var: on_language_checkbox_toggle(app, c, v), bootstyle="light-round-toggle")
        cb.pack(side='left', padx=5)
        app.lang_checkbuttons[code] = var
        
    app.lang_output_frame = ttk.Labelframe(app.chain_scrollable_frame, text=app._t('paths_and_steps_label'))
    app.lang_output_frame.pack(fill='x', padx=10, pady=5)
    
    balance_frame = ttk.Frame(app.chain_scrollable_frame)
    balance_frame.pack(anchor='w', padx=10, pady=5)
    app.chain_el_balance_label = ttk.Label(balance_frame, text=f"{app._t('elevenlabs_balance_label')}: N/A")
    app.chain_el_balance_label.pack(side='left', padx=(0,10))

    app.chain_recraft_balance_label = ttk.Label(balance_frame, text=f"{app._t('recraft_balance_label')}: N/A")
    app.chain_recraft_balance_label.pack(side='left', padx=(0,10))
    
    app.chain_vm_balance_label = ttk.Label(balance_frame, text=f"{app._t('voicemaker_balance_label')}: N/A")
    app.chain_vm_balance_label.pack(side='left')

    refresh_button = ttk.Button(balance_frame, text="↻", command=app.update_api_balances, bootstyle="light-outline", width=2)
    refresh_button.pack(side='left', padx=5)
    
    buttons_frame = ttk.Frame(app.chain_scrollable_frame)
    buttons_frame.pack(fill='x', padx=10, pady=5)
    
    ttk.Button(buttons_frame, text=app._t('add_to_queue_button'), command=app.add_to_queue, bootstyle="info").pack(side='left', padx=5)
    
    # Переносимо кнопки управління чергою на рівень з "Додати в чергу"
    ttk.Button(buttons_frame, text=app._t('process_queue_button'), command=app.process_queue, bootstyle="success").pack(side='left', padx=5)
    
    app.pause_resume_button = ttk.Button(buttons_frame, text=app._t('pause_button'), command=app.toggle_pause_resume, bootstyle="warning", state="disabled")
    app.pause_resume_button.pack(side='left', padx=5)
    
    ttk.Button(buttons_frame, text=app._t('clear_queue_button'), command=app.clear_queue, bootstyle="danger").pack(side='left', padx=5)
    
    app.progress_var = tk.DoubleVar()
    app.progress_bar = ttk.Progressbar(app.chain_scrollable_frame, variable=app.progress_var, maximum=100, bootstyle="success-striped")
    app.progress_bar.pack(fill='x', padx=10, pady=5)
    # Створюємо фрейм для кнопок під прогрес-баром
    chain_buttons_frame = ttk.Frame(app.chain_scrollable_frame)
    chain_buttons_frame.pack(pady=5)

    skip_image_button_chain = ttk.Button(
        chain_buttons_frame,
        text=app._t('skip_image_button'),
        command=app._on_skip_image_click,
        bootstyle="warning",
        state="disabled"
    )
    skip_image_button_chain.pack(side='left', padx=5)
    app.skip_image_buttons.append(skip_image_button_chain)
    
    # Нова кнопка для перемикання сервісу
    switch_service_button_chain = ttk.Button(
        chain_buttons_frame,
        text=app._t('switch_service_button'),
        command=app._on_switch_service_click,
        bootstyle="info",
        state="disabled"
    )
    switch_service_button_chain.pack(side='left', padx=5)
    app.switch_service_buttons.append(switch_service_button_chain)

    # --- Нова кнопка регенерації іншим сервісом ---
    regenerate_alt_button_chain = ttk.Button(
        chain_buttons_frame,
        text=app._t('regenerate_alt_button'),
        command=app._on_regenerate_alt_click,
        bootstyle="success",
        state="disabled"
    )
    regenerate_alt_button_chain.pack(side='left', padx=5)
    app.regenerate_alt_buttons.append(regenerate_alt_button_chain)

    # --- Новий вибір API ---
    ttk.Label(chain_buttons_frame, text=f"{app._t('image_api_label')}:").pack(side='left', padx=(10, 2))
    image_api_combo_chain = ttk.Combobox(
        chain_buttons_frame, 
        textvariable=app.active_image_api_var, 
        values=["pollinations", "recraft"], 
        state="readonly",
        width=12
    )
    image_api_combo_chain.pack(side='left', padx=5)
    image_api_combo_chain.bind("<<ComboboxSelected>>", app._on_image_api_select)
    app.image_api_selectors.append(image_api_combo_chain)
    
    queue_main_frame = ttk.Labelframe(app.chain_scrollable_frame, text=app._t('task_queue_tab'))
    queue_main_frame.pack(fill='x', expand=True, padx=10, pady=10)


    
    queue_list_frame = ttk.Frame(queue_main_frame)
    queue_list_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
    columns = ("status", "time")
    app.queue_tree = ttk.Treeview(queue_list_frame, columns=columns, show='tree headings', bootstyle="dark")
    
    # Початкова висота - використовуємо збережену або мінімальну за замовчуванням
    saved_height = app.config.get("ui_settings", {}).get("queue_height", 5)
    app.queue_tree.configure(height=saved_height)
    
    style = ttk.Style()
    style.configure("Treeview.Heading", relief="groove", borderwidth=1, padding=(5,5))
    
    saved_widths = app.config.get("ui_settings", {}).get("queue_column_widths", {})
    
    app.queue_tree.heading("#0", text=app._t('task_details_column'))
    app.queue_tree.column("#0", width=saved_widths.get('task_details', 400), anchor='w')
    
    app.queue_tree.heading('status', text=app._t('queue_status_col'))
    app.queue_tree.column('status', width=saved_widths.get('status', 100), anchor='w')
    app.queue_tree.heading('time', text=app._t('queue_time_col'))
    app.queue_tree.column('time', width=saved_widths.get('time', 150), anchor='w')

    app.queue_scrollbar = ttk.Scrollbar(queue_list_frame, orient="vertical", command=app.queue_tree.yview)
    app.dynamic_scrollbars.append(app.queue_scrollbar)
    app.queue_tree.configure(yscrollcommand=app.queue_scrollbar.set)
    app.queue_tree.pack(side="left", fill="both", expand=True)
    app.queue_scrollbar.pack(side="right", fill="y")
    
    app.queue_tree.bind("<Double-1>", app.edit_task_name)
    
    app.update_queue_display()

    # --- Контейнер для галереї контролю зображень ---
    app.chain_image_gallery_frame = ttk.Labelframe(app.chain_scrollable_frame, text=app._t('image_control_gallery_label'))
    # app.chain_image_gallery_frame.pack(fill='x', expand=True, padx=10, pady=10) # Покажемо пізніше