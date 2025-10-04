import tkinter as tk
import ttkbootstrap as ttk

from .gui_utils import add_text_widget_bindings, create_scrollable_tab, create_scrolled_text

# --- Функції-помічники для віджетів на цій вкладці ---

def on_rewrite_language_toggle(app, lang_code, var):
    if var.get():
        add_rewrite_lang_widgets(app, lang_code)
    else:
        remove_rewrite_lang_widgets(app, lang_code)

def add_rewrite_lang_widgets(app, lang_code):
    if lang_code in app.rewrite_lang_widgets: return
    
    container = ttk.Frame(app.rewrite_lang_output_frame)
    container.pack(fill='x', padx=5, pady=2, anchor='w')
    
    ttk.Label(container, text=f"{lang_code.upper()}:", width=5).pack(side='left', padx=(0, 10))

    steps_frame = ttk.Frame(container)
    steps_frame.pack(side='left', fill='x', expand=True)

    app.rewrite_lang_step_vars[lang_code] = {
        'download': tk.BooleanVar(value=True),
        'transcribe': tk.BooleanVar(value=True),
        'rewrite': tk.BooleanVar(value=True),
        'cta': tk.BooleanVar(value=True),
        'gen_prompts': tk.BooleanVar(value=True),
        'gen_images': tk.BooleanVar(value=True),
        'audio': tk.BooleanVar(value=True),
        'create_subtitles': tk.BooleanVar(value=True),
        'create_video': tk.BooleanVar(value=True)
    }
    
    steps = {
        'download': app._t('step_download'),
        'transcribe': app._t('step_transcribe'),
        'rewrite': app._t('step_rewrite'), 
        'cta': app._t('step_cta'), 
        'gen_prompts': app._t('step_gen_prompts'), 
        'gen_images': app._t('step_gen_images'), 
        'audio': app._t('step_audio'), 
        'create_subtitles': app._t('step_create_subtitles'),
        'create_video': app._t('step_create_video')
    }
    
    for key, text in steps.items():
        cb = ttk.Checkbutton(steps_frame, text=text, variable=app.rewrite_lang_step_vars[lang_code][key], bootstyle="light-round-toggle")
        cb.pack(side='left', padx=3)
    
    app.rewrite_lang_widgets[lang_code] = {'container': container}

def remove_rewrite_lang_widgets(app, lang_code):
    if lang_code in app.rewrite_lang_widgets:
        app.rewrite_lang_widgets[lang_code]['container'].destroy()
        del app.rewrite_lang_widgets[lang_code]
        del app.rewrite_lang_step_vars[lang_code]

# --- Головна функція для створення вкладки ---

def create_rewrite_tab(notebook, app):
    """
    Створює вкладку "Рерайт" та всі її елементи.
    'notebook' - це головний записник, куди буде додано вкладку.
    'app' - це посилання на головний клас програми для доступу до його функцій та змінних.
    """
    app.rewrite_canvas, app.rewrite_scrollable_frame = create_scrollable_tab(app, app.rewrite_frame)
    
    # --- Блок для введення посилань ---
    links_frame = ttk.Labelframe(app.rewrite_scrollable_frame, text=app._t('youtube_links_label'))
    links_frame.pack(fill='x', expand=True, padx=10, pady=5)
    
    app.rewrite_links_text, text_container_widget = create_scrolled_text(app, links_frame, height=5, width=60)
    text_container_widget.pack(fill='both', expand=True, padx=5, pady=5)
    add_text_widget_bindings(app, app.rewrite_links_text)

    # Інформаційна рамка для локальних файлів
    info_frame = ttk.Labelframe(app.rewrite_scrollable_frame, text=app._t('local_audio_work_label'))
    info_frame.pack(fill='x', expand=True, padx=10, pady=5)
    ttk.Label(info_frame, text=app._t('rewrite_instructions_label'), justify='left').pack(padx=5, pady=5)
    
    options_frame = ttk.Frame(app.rewrite_scrollable_frame)
    options_frame.pack(fill='x', padx=10, pady=5)
    
    ttk.Label(options_frame, text=app._t('select_template_label')).pack(side='left', padx=(0, 5))
    app.rewrite_template_var = tk.StringVar()
    app.rewrite_template_selector = ttk.Combobox(options_frame, textvariable=app.rewrite_template_var, state="readonly")
    app.rewrite_template_selector.pack(side='left')

    lang_sel_frame = ttk.Frame(app.rewrite_scrollable_frame)
    lang_sel_frame.pack(fill='x', padx=10, pady=5)
    ttk.Label(lang_sel_frame, text=app._t('select_languages_label')).pack(side='left')
    app.rewrite_lang_checkbuttons = {}
    lang_codes = list(app.config["languages"].keys())
    for code in lang_codes:
        var = tk.BooleanVar()
        cb = ttk.Checkbutton(lang_sel_frame, text=code.upper(), variable=var,
                            command=lambda c=code, v=var: on_rewrite_language_toggle(app, c, v), bootstyle="light-round-toggle")
        cb.pack(side='left', padx=5)
        app.rewrite_lang_checkbuttons[code] = var
        
    app.rewrite_lang_output_frame = ttk.Labelframe(app.rewrite_scrollable_frame, text=app._t('paths_and_steps_label'))
    app.rewrite_lang_output_frame.pack(fill='x', padx=10, pady=5)
    app.rewrite_lang_widgets = {}

    balance_frame = ttk.Frame(app.rewrite_scrollable_frame)
    balance_frame.pack(anchor='w', padx=10, pady=5)

    app.rewrite_el_balance_label = ttk.Label(balance_frame, text=f"{app._t('elevenlabs_balance_label')}: N/A")
    app.rewrite_el_balance_label.pack(side='left', padx=(0,10))

    app.rewrite_or_balance_label = ttk.Label(balance_frame, text=f"{app._t('openrouter_balance_label')}: N/A")
    app.rewrite_or_balance_label.pack(side='left', padx=(0,10))

    app.rewrite_recraft_balance_label = ttk.Label(balance_frame, text=f"{app._t('recraft_balance_label')}: N/A")
    app.rewrite_recraft_balance_label.pack(side='left', padx=(0,10))

    app.rewrite_vm_balance_label = ttk.Label(balance_frame, text=f"{app._t('voicemaker_balance_label')}: N/A")
    app.rewrite_vm_balance_label.pack(side='left')

    refresh_button = ttk.Button(balance_frame, text="↻", command=app.update_api_balances, bootstyle="light-outline", width=2)
    refresh_button.pack(side='left', padx=5)

    buttons_frame = ttk.Frame(app.rewrite_scrollable_frame)
    buttons_frame.pack(fill='x', padx=10, pady=5)
    
    # Оновлена кнопка, яка тепер викликає універсальну функцію
    ttk.Button(buttons_frame, text=app._t('add_to_queue_button'), command=app.add_to_rewrite_queue, bootstyle="info").pack(side='left', padx=5)
    # Нова кнопка для завантаження посилань з файлу
    ttk.Button(buttons_frame, text=app._t('load_from_file_button'), command=app.load_links_from_file, bootstyle="secondary").pack(side='left', padx=5)


    # --- Image Generation API Selector ---
    ttk.Label(buttons_frame, text=f"{app._t('image_api_label')}:").pack(side='left', padx=(20, 2))
    image_api_combo_rewrite = ttk.Combobox(
        buttons_frame, 
        textvariable=app.active_image_api_var, 
        values=["pollinations", "recraft", "googler"], 
        state="readonly",
        width=12
    )
    image_api_combo_rewrite.pack(side='left', padx=5)
    image_api_combo_rewrite.bind("<<ComboboxSelected>>", app._on_image_api_select)
    app.image_api_selectors.append(image_api_combo_rewrite)

    # --- Контейнер для галереї контролю зображень ---
    app.rewrite_image_gallery_frame = ttk.Labelframe(app.rewrite_scrollable_frame, text=app._t('image_control_gallery_label'))
    # app.rewrite_image_gallery_frame.pack(fill='x', expand=True, padx=10, pady=10) # Покажемо пізніше