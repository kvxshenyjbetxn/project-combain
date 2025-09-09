import tkinter as tk
import ttkbootstrap as ttk
import sys

# Константи, які потрібні цьому файлу
from constants.default_config import DEFAULT_CONFIG
from constants.recraft_substyles import RECRAFT_SUBSTYLES

from .gui_utils import add_text_widget_bindings

# --- Головна функція для створення вкладки ---

def create_settings_tab(notebook, app):
    """
    Створює вкладку "Налаштування" та всі її під-вкладки.
    """
    settings_notebook = ttk.Notebook(app.settings_frame, bootstyle="light")
    settings_notebook.pack(fill='both', expand=True, padx=5, pady=5)

    api_tab = ttk.Frame(settings_notebook)
    languages_tab = ttk.Frame(settings_notebook)
    prompts_tab = ttk.Frame(settings_notebook)
    montage_tab = ttk.Frame(settings_notebook)
    other_tab = ttk.Frame(settings_notebook)

    settings_notebook.add(api_tab, text=app._t('api_tab_label'))
    settings_notebook.add(languages_tab, text=app._t('language_settings_label'))
    settings_notebook.add(prompts_tab, text=app._t('prompts_tab_label'))
    settings_notebook.add(montage_tab, text=app._t('montage_tab_label'))
    settings_notebook.add(other_tab, text=app._t('other_tab_label'))

    create_api_settings_subtabs(api_tab, app)
    create_language_settings_tab(languages_tab, app)
    create_prompts_settings_tab(prompts_tab, app)
    create_montage_settings_tab(montage_tab, app)
    create_other_settings_tab(other_tab, app)
    
    ttk.Button(app.settings_frame, text=app._t('save_settings_button'), command=app.save_settings, bootstyle="primary").pack(pady=10)
    
    app.populate_openrouter_widgets()

# --- Функції для створення під-вкладок ---

def create_api_settings_subtabs(parent_tab, app):
    api_notebook = ttk.Notebook(parent_tab, bootstyle="secondary")
    api_notebook.pack(fill="both", expand=True, padx=5, pady=5)
    
    or_tab = ttk.Frame(api_notebook)
    audio_tab = ttk.Frame(api_notebook)
    image_tab = ttk.Frame(api_notebook)
    firebase_tab = ttk.Frame(api_notebook)

    api_notebook.add(or_tab, text=app._t('openrouter_tab_label'))
    api_notebook.add(audio_tab, text=app._t('audio_tab_label'))
    api_notebook.add(image_tab, text=app._t('image_tab_label'))
    api_notebook.add(firebase_tab, text="Firebase")

    # --- OpenRouter Settings ---
    _, or_scroll_frame = app._create_scrollable_tab(or_tab)
    or_frame = ttk.Labelframe(or_scroll_frame, text=app._t('openrouter_settings_label'))
    or_frame.pack(fill='x', padx=10, pady=5)
    or_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(or_frame, text=app._t('api_key_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.or_api_key_var = tk.StringVar(value=app.config["openrouter"]["api_key"])
    or_api_key_entry = ttk.Entry(or_frame, textvariable=app.or_api_key_var, width=50, show="*")
    or_api_key_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, or_api_key_entry)
    ttk.Button(or_frame, text=app._t('test_connection_button'), command=app.test_openrouter_connection, bootstyle="secondary-outline").grid(row=0, column=2, padx=5, pady=5)
    
    models_frame = ttk.Labelframe(or_scroll_frame, text=app._t('saved_models_label'), bootstyle="secondary")
    models_frame.pack(fill='x', padx=10, pady=5)
    models_frame.grid_columnconfigure(0, weight=1)
    app.or_models_listbox = tk.Listbox(models_frame, height=5, relief="flat", highlightthickness=0)
    app.or_models_listbox.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    add_text_widget_bindings(app, app.or_models_listbox)
    models_btn_frame = ttk.Frame(models_frame)
    models_btn_frame.grid(row=0, column=1, sticky='ns', padx=5, pady=5)
    ttk.Button(models_btn_frame, text=app._t('add_button'), command=app.add_openrouter_model, bootstyle="info-outline").pack(fill='x', pady=2)
    ttk.Button(models_btn_frame, text=app._t('remove_button'), command=app.remove_openrouter_model, bootstyle="danger-outline").pack(fill='x', pady=2)

    # --- Audio API Settings ---
    audio_notebook = ttk.Notebook(audio_tab, bootstyle="info")
    audio_notebook.pack(fill="both", expand=True, padx=5, pady=5)
    el_tab = ttk.Frame(audio_notebook)
    vm_tab = ttk.Frame(audio_notebook)
    speechify_tab = ttk.Frame(audio_notebook)
    audio_notebook.add(el_tab, text=app._t('elevenlabs_tab_label'))
    audio_notebook.add(vm_tab, text=app._t('voicemaker_tab_label'))
    audio_notebook.add(speechify_tab, text=app._t('speechify_tab_label'))

    _, el_scroll_frame = app._create_scrollable_tab(el_tab)
    el_frame = ttk.Labelframe(el_scroll_frame, text=app._t('elevenlabs_settings_label'))
    el_frame.pack(fill='x', padx=10, pady=5)
    el_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(el_frame, text=app._t('api_key_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.el_api_key_var = tk.StringVar(value=app.config["elevenlabs"]["api_key"])
    el_api_key_entry = ttk.Entry(el_frame, textvariable=app.el_api_key_var, width=50, show="*")
    el_api_key_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, el_api_key_entry)
    ttk.Button(el_frame, text=app._t('test_connection_button'), command=app.test_elevenlabs_connection, bootstyle="secondary-outline").grid(row=0, column=2, padx=5, pady=5)
    app.settings_el_balance_label = ttk.Label(el_frame, text=f"{app._t('balance_label')}: N/A")
    app.settings_el_balance_label.grid(row=1, column=0, columnspan=3, sticky='w', padx=5, pady=5)

    _, vm_scroll_frame = app._create_scrollable_tab(vm_tab)
    vm_frame = ttk.Labelframe(vm_scroll_frame, text=app._t('voicemaker_settings_label'))
    vm_frame.pack(fill='x', padx=10, pady=5)
    vm_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(vm_frame, text=app._t('api_key_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.vm_api_key_var = tk.StringVar(value=app.config.get("voicemaker", {}).get("api_key", ""))
    vm_api_key_entry = ttk.Entry(vm_frame, textvariable=app.vm_api_key_var, width=50, show="*")
    vm_api_key_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, vm_api_key_entry)
    ttk.Button(vm_frame, text=app._t('test_connection_button'), command=app.test_voicemaker_connection, bootstyle="secondary-outline").grid(row=0, column=2, padx=5, pady=5)
    
    # ВИПРАВЛЕНО ТУТ: була помилка app.settings_el_balance_label -> app.settings_vm_balance_label
    app.settings_vm_balance_label = ttk.Label(vm_frame, text=f"{app._t('balance_label')}: N/A")
    app.settings_vm_balance_label.grid(row=1, column=0, columnspan=3, sticky='w', padx=5, pady=5)

    # Нове поле для ліміту символів
    ttk.Label(vm_frame, text=app._t('char_limit_label')).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    app.vm_char_limit_var = tk.IntVar(value=app.config.get("voicemaker", {}).get("char_limit", 9900))
    vm_char_limit_spinbox = ttk.Spinbox(vm_frame, from_=1000, to=10000, increment=100, textvariable=app.vm_char_limit_var, width=10)
    vm_char_limit_spinbox.grid(row=2, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, vm_char_limit_spinbox)

    # --- Speechify Settings ---
    _, speechify_scroll_frame = app._create_scrollable_tab(speechify_tab)
    speechify_frame = ttk.Labelframe(speechify_scroll_frame, text=app._t('speechify_settings_label'))
    speechify_frame.pack(fill='x', padx=10, pady=5)
    speechify_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(speechify_frame, text=app._t('api_key_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.speechify_api_key_var = tk.StringVar(value=app.config.get("speechify", {}).get("api_key", ""))
    speechify_api_key_entry = ttk.Entry(speechify_frame, textvariable=app.speechify_api_key_var, width=50, show="*")
    speechify_api_key_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, speechify_api_key_entry)
    ttk.Button(speechify_frame, text=app._t('test_connection_button'), command=app.test_speechify_connection, bootstyle="secondary-outline").grid(row=0, column=2, padx=5, pady=5)

    # --- Image API Settings ---
    image_notebook = ttk.Notebook(image_tab, bootstyle="info")
    image_notebook.pack(fill="both", expand=True, padx=5, pady=5)
    poll_tab = ttk.Frame(image_notebook)
    recraft_tab = ttk.Frame(image_notebook)
    image_notebook.add(poll_tab, text=app._t('pollinations_tab_label'))
    image_notebook.add(recraft_tab, text=app._t('recraft_tab_label'))

    # --- Pollinations Settings ---
    _, poll_scroll_frame = app._create_scrollable_tab(poll_tab)
    poll_frame = ttk.Labelframe(poll_scroll_frame, text=app._t('pollinations_settings_label'))
    poll_frame.pack(fill='x', padx=10, pady=5)
    poll_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(poll_frame, text=app._t('api_key_optional_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.poll_token_var = tk.StringVar(value=app.config["pollinations"].get("token", ""))
    poll_token_entry = ttk.Entry(poll_frame, textvariable=app.poll_token_var, width=50)
    poll_token_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, poll_token_entry)
    ttk.Button(poll_frame, text=app._t('test_connection_button'), command=app.test_pollinations_connection, bootstyle="secondary-outline").grid(row=0, column=2, padx=5, pady=5)
    ttk.Label(poll_frame, text=app._t('model_label')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.poll_model_var = tk.StringVar(value=app.config["pollinations"]["model"])
    app.poll_available_models = ["flux", "flux-realism", "flux-3d", "flux-cablyai", "dall-e-3", "midjourney", "boreal"]
    app.poll_model_dropdown = ttk.Combobox(poll_frame, textvariable=app.poll_model_var, values=app.poll_available_models, state="readonly")
    app.poll_model_dropdown.grid(row=1, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, app.poll_model_dropdown)
    if app.poll_model_var.get() not in app.poll_available_models: app.poll_model_var.set(app.poll_available_models[0])
    ttk.Label(poll_frame, text=app._t('width_label')).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    app.poll_width_var = tk.IntVar(value=app.config["pollinations"]["width"])
    poll_width_spinbox = ttk.Spinbox(poll_frame, from_=256, to=4096, increment=64, textvariable=app.poll_width_var, width=10)
    poll_width_spinbox.grid(row=2, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, poll_width_spinbox)
    ttk.Label(poll_frame, text=app._t('height_label')).grid(row=3, column=0, sticky='w', padx=5, pady=5)
    app.poll_height_var = tk.IntVar(value=app.config["pollinations"]["height"])
    poll_height_spinbox = ttk.Spinbox(poll_frame, from_=256, to=4096, increment=64, textvariable=app.poll_height_var, width=10)
    poll_height_spinbox.grid(row=3, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, poll_height_spinbox)

    ttk.Label(poll_frame, text=app._t('timeout_label')).grid(row=4, column=0, sticky='w', padx=5, pady=5)
    app.poll_timeout_var = tk.IntVar(value=app.config["pollinations"]["timeout"])
    poll_timeout_spinbox = ttk.Spinbox(poll_frame, from_=1, to=30, textvariable=app.poll_timeout_var, width=10)
    poll_timeout_spinbox.grid(row=4, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, poll_timeout_spinbox)

    app.poll_remove_logo_var = tk.BooleanVar(value=app.config["pollinations"]["remove_logo"])
    ttk.Checkbutton(poll_frame, variable=app.poll_remove_logo_var, text=app._t('remove_logo_label'), bootstyle="light-round-toggle").grid(row=6, column=0, sticky='w', padx=5, pady=5)

    # --- Recraft Settings ---
    _, recraft_scroll_frame = app._create_scrollable_tab(recraft_tab)
    recraft_frame = ttk.Labelframe(recraft_scroll_frame, text=app._t('recraft_settings_label'))
    recraft_frame.pack(fill='x', padx=10, pady=5)
    recraft_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(recraft_frame, text=app._t('api_key_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.recraft_api_key_var = tk.StringVar(value=app.config.get("recraft", {}).get("api_key", ""))
    recraft_api_key_entry = ttk.Entry(recraft_frame, textvariable=app.recraft_api_key_var, width=50, show="*")
    recraft_api_key_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, recraft_api_key_entry)
    ttk.Button(recraft_frame, text=app._t('test_connection_button'), command=app.test_recraft_connection, bootstyle="secondary-outline").grid(row=0, column=2, padx=5, pady=5)

    app.settings_recraft_balance_label = ttk.Label(recraft_frame, text=f"{app._t('balance_label')}: N/A")
    app.settings_recraft_balance_label.grid(row=1, column=0, columnspan=3, sticky='w', padx=5, pady=5)

    ttk.Label(recraft_frame, text=app._t('recraft_model_label')).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    app.recraft_model_var = tk.StringVar(value=app.config.get("recraft", {}).get("model", "recraftv3"))
    recraft_model_combo = ttk.Combobox(recraft_frame, textvariable=app.recraft_model_var, values=["recraftv3", "recraftv2"], state="readonly")
    recraft_model_combo.grid(row=2, column=1, sticky='ew', padx=5, pady=5)
    recraft_model_combo.bind("<<ComboboxSelected>>", app._update_recraft_substyles)
    
    ttk.Label(recraft_frame, text=app._t('recraft_style_label')).grid(row=3, column=0, sticky='w', padx=5, pady=5)
    app.recraft_style_var = tk.StringVar(value=app.config.get("recraft", {}).get("style", "digital_illustration"))
    recraft_style_combo = ttk.Combobox(recraft_frame, textvariable=app.recraft_style_var, values=["realistic_image", "digital_illustration", "vector_illustration", "icon", "logo_raster"], state="readonly")
    recraft_style_combo.grid(row=3, column=1, sticky='ew', padx=5, pady=5)
    recraft_style_combo.bind("<<ComboboxSelected>>", app._update_recraft_substyles)

    ttk.Label(recraft_frame, text=app._t('recraft_substyle_label')).grid(row=4, column=0, sticky='w', padx=5, pady=5)
    app.recraft_substyle_var = tk.StringVar(value=app.config.get("recraft", {}).get("substyle", ""))
    app.recraft_substyle_combo = ttk.Combobox(recraft_frame, textvariable=app.recraft_substyle_var, state="readonly")
    app.recraft_substyle_combo.grid(row=4, column=1, sticky='ew', padx=5, pady=5)
    
    ttk.Label(recraft_frame, text=app._t('recraft_size_label')).grid(row=5, column=0, sticky='w', padx=5, pady=5)
    app.recraft_size_var = tk.StringVar(value=app.config.get("recraft", {}).get("size", "1820x1024"))
    recraft_size_combo = ttk.Combobox(recraft_frame, textvariable=app.recraft_size_var, values=["1820x1024 (16:9)", "1024x1820 (9:16)"], state="readonly")
    recraft_size_combo.grid(row=5, column=1, sticky='ew', padx=5, pady=5)

    ttk.Label(recraft_frame, text=app._t('recraft_negative_prompt_label')).grid(row=6, column=0, sticky='w', padx=5, pady=5)
    app.recraft_negative_prompt_var = tk.StringVar(value=app.config.get("recraft", {}).get("negative_prompt", ""))
    recraft_negative_prompt_entry = ttk.Entry(recraft_frame, textvariable=app.recraft_negative_prompt_var)
    recraft_negative_prompt_entry.grid(row=6, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, recraft_negative_prompt_entry)

    # --- Firebase Settings ---
    create_firebase_settings_tab(firebase_tab, app)

def create_firebase_settings_tab(parent_tab, app):
    """Створює вкладку з налаштуваннями Firebase."""
    _, firebase_scroll_frame = app._create_scrollable_tab(parent_tab)
    
    # Основні налаштування Firebase
    firebase_frame = ttk.Labelframe(firebase_scroll_frame, text=app._t('firebase_connection_label'))
    firebase_frame.pack(fill='x', padx=10, pady=5)
    firebase_frame.grid_columnconfigure(1, weight=1)
    
    # User ID для синхронізації
    ttk.Label(firebase_frame, text=app._t('your_user_id_label'), font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    user_id = getattr(app.firebase_api, 'user_id', 'Not available')
    app.firebase_user_id_var = tk.StringVar(value=user_id)
    user_id_entry = ttk.Entry(firebase_frame, textvariable=app.firebase_user_id_var, state='readonly', width=30)
    user_id_entry.grid(row=0, column=1, sticky='w', padx=5, pady=5)
    
    # Кнопка копіювання
    def copy_user_id():
        app.root.clipboard_clear()
        app.root.clipboard_append(user_id)
        print(f"[INFO] User ID '{user_id}' скопійовано в буфер обміну!")
    
    ttk.Button(firebase_frame, text=app._t('copy_button'), command=copy_user_id, bootstyle="info-outline").grid(row=0, column=2, padx=5, pady=5)
    
    # Інструкції
    instructions = ttk.Label(firebase_frame, 
                           text=app._t('firebase_instructions_text'),
                           font=('TkDefaultFont', 9),
                           foreground='gray')
    instructions.grid(row=1, column=0, columnspan=3, sticky='w', padx=5, pady=(10, 5))
    
    # Статистика
    stats_frame = ttk.Labelframe(firebase_scroll_frame, text=app._t('statistics_label'))
    stats_frame.pack(fill='x', padx=10, pady=5)
    stats_frame.grid_columnconfigure(1, weight=1)
    
    app.firebase_logs_stat_var = tk.StringVar(value=app._t('loading_label_text').replace('\n', ' '))
    app.firebase_images_stat_var = tk.StringVar(value=app._t('loading_label_text').replace('\n', ' '))
    
    ttk.Label(stats_frame, text=app._t('logs_label')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
    ttk.Label(stats_frame, textvariable=app.firebase_logs_stat_var).grid(row=0, column=1, sticky='w', padx=5, pady=2)
    
    ttk.Label(stats_frame, text=app._t('images_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
    ttk.Label(stats_frame, textvariable=app.firebase_images_stat_var).grid(row=1, column=1, sticky='w', padx=5, pady=2)
    
    # Кнопки керування
    control_frame = ttk.Labelframe(firebase_scroll_frame, text=app._t('data_management_label'))
    control_frame.pack(fill='x', padx=10, pady=5)
    
    ttk.Button(control_frame, text=app._t('clear_logs_button'), command=app.clear_firebase_logs, bootstyle="warning-outline").pack(side=tk.LEFT, padx=5, pady=5)
    ttk.Button(control_frame, text=app._t('clear_images_button'), command=app.clear_firebase_images, bootstyle="danger-outline").pack(side=tk.LEFT, padx=5, pady=5)
    ttk.Button(control_frame, text=app._t('refresh_stats_button_firebase'), command=app.refresh_firebase_stats, bootstyle="secondary-outline").pack(side=tk.LEFT, padx=5, pady=5)
    
    # Оновлюємо статистику при відкритті
    app.refresh_firebase_stats()

def create_language_settings_tab(parent_tab, app):
    canvas, scrollable_frame = app._create_scrollable_tab(parent_tab)
    
    lang_frame = ttk.Labelframe(scrollable_frame, text=app._t('language_settings_label'))
    lang_frame.pack(fill='both', expand=True, padx=10, pady=5)
    
    list_frame = ttk.Frame(lang_frame)
    list_frame.pack(side='left', fill='y', padx=5, pady=5)

    app.lang_listbox = tk.Listbox(list_frame, relief="flat", highlightthickness=0, width=15)
    app.lang_listbox.pack(side='top', fill='y', expand=True)
    add_text_widget_bindings(app, app.lang_listbox)
    app.lang_listbox.bind('<<ListboxSelect>>', app.on_language_select)
    
    lang_btn_frame = ttk.Frame(list_frame)
    lang_btn_frame.pack(side='bottom', fill='x', pady=5)
    ttk.Button(lang_btn_frame, text=app._t('add_button'), command=app.add_language, bootstyle="info-outline").pack(fill='x', pady=2)
    ttk.Button(lang_btn_frame, text=app._t('remove_button'), command=app.remove_language, bootstyle="danger-outline").pack(fill='x', pady=2)
    
    app.lang_details_frame = ttk.Frame(lang_frame)
    app.lang_details_frame.pack(side='right', fill='both', expand=True, padx=5, pady=5)
    app.selected_lang_code = None
    
    app.lang_details_frame.canvas = canvas
    
    app.populate_language_list()

def create_prompts_settings_tab(parent_tab, app):
    canvas, scrollable_frame = app._create_scrollable_tab(parent_tab)

    trans_prompt_frame = ttk.Labelframe(scrollable_frame, text=app._t("translation_model_label"))
    trans_prompt_frame.pack(fill='x', padx=10, pady=5)
    trans_prompt_frame.grid_columnconfigure(1, weight=1)

    ttk.Label(trans_prompt_frame, text=app._t('model_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.or_trans_model_var = tk.StringVar(value=app.config["openrouter"]["translation_model"])
    app.or_trans_model_combo = ttk.Combobox(trans_prompt_frame, textvariable=app.or_trans_model_var)
    app.or_trans_model_combo.grid(row=0, column=1, columnspan=2, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, app.or_trans_model_combo)

    ttk.Label(trans_prompt_frame, text="Temperature:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.trans_temp_var = tk.DoubleVar(value=app.config["openrouter"]["translation_params"].get("temperature", 0.7))
    trans_temp_spinbox = ttk.Spinbox(trans_prompt_frame, from_=0.0, to=2.0, increment=0.1, textvariable=app.trans_temp_var, width=10)
    trans_temp_spinbox.grid(row=1, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, trans_temp_spinbox)

    ttk.Label(trans_prompt_frame, text=app._t('max_tokens_label')).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    app.trans_tokens_var = tk.IntVar(value=app.config["openrouter"]["translation_params"].get("max_tokens", 1000))
    trans_tokens_spinbox = ttk.Spinbox(trans_prompt_frame, from_=1, to=128000, textvariable=app.trans_tokens_var, width=10)
    trans_tokens_spinbox.grid(row=2, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, trans_tokens_spinbox)
    
    rewrite_frame = ttk.Labelframe(scrollable_frame, text=app._t("rewrite_model_label"))
    rewrite_frame.pack(fill='x', padx=10, pady=5)
    rewrite_frame.grid_columnconfigure(1, weight=1)

    ttk.Label(rewrite_frame, text=app._t('model_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.or_rewrite_model_var = tk.StringVar(value=app.config["openrouter"].get("rewrite_model", "openai/gpt-4o-mini"))
    app.or_rewrite_model_combo = ttk.Combobox(rewrite_frame, textvariable=app.or_rewrite_model_var)
    app.or_rewrite_model_combo.grid(row=0, column=1, columnspan=2, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, app.or_rewrite_model_combo)

    ttk.Label(rewrite_frame, text=app._t('temperature_label')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.rewrite_temp_var = tk.DoubleVar(value=app.config["openrouter"]["rewrite_params"].get("temperature", 0.7))
    rewrite_temp_spinbox = ttk.Spinbox(rewrite_frame, from_=0.0, to=2.0, increment=0.1, textvariable=app.rewrite_temp_var, width=10)
    rewrite_temp_spinbox.grid(row=1, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, rewrite_temp_spinbox)

    ttk.Label(rewrite_frame, text=app._t('max_tokens_label')).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    app.rewrite_tokens_var = tk.IntVar(value=app.config["openrouter"]["rewrite_params"].get("max_tokens", 4000))
    rewrite_tokens_spinbox = ttk.Spinbox(rewrite_frame, from_=1, to=128000, textvariable=app.rewrite_tokens_var, width=10)
    rewrite_tokens_spinbox.grid(row=2, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, rewrite_tokens_spinbox)

    prompt_gen_frame = ttk.Labelframe(scrollable_frame, text=app._t('image_prompt_settings_label'))
    prompt_gen_frame.pack(fill='x', padx=10, pady=5)
    prompt_gen_frame.grid_columnconfigure(1, weight=1)
    
    ttk.Label(prompt_gen_frame, text=app._t('prompt_label')).grid(row=0, column=0, sticky='nw', padx=5, pady=5)
    
    prompt_container = ttk.Frame(prompt_gen_frame)
    prompt_container.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
    
    initial_prompt_height = app.config.get("ui_settings", {}).get("prompt_text_height", 80)
    app.prompt_text_frame = ttk.Frame(prompt_container, height=initial_prompt_height)
    app.prompt_text_frame.pack(fill="x")
    app.prompt_text_frame.pack_propagate(False)

    app.prompt_gen_prompt_text, text_container_widget = app._create_scrolled_text(app.prompt_text_frame, height=4, width=60, relief="flat", insertbackground="white")
    text_container_widget.pack(fill="both", expand=True)
    add_text_widget_bindings(app, app.prompt_gen_prompt_text)

    prompt_grip = ttk.Frame(prompt_container, height=8, bootstyle="secondary", cursor="sb_v_double_arrow")
    prompt_grip.pack(fill="x")

    def start_resize_prompt(event):
        prompt_grip.startY = event.y
        prompt_grip.start_height = app.prompt_text_frame.winfo_height()

    def do_resize_prompt(event):
        new_height = prompt_grip.start_height + (event.y - prompt_grip.startY)
        if 50 <= new_height <= 400:
            app.prompt_text_frame.config(height=new_height)
            canvas.update_idletasks()
            canvas.config(scrollregion=canvas.bbox("all"))

    prompt_grip.bind("<ButtonPress-1>", start_resize_prompt)
    prompt_grip.bind("<B1-Motion>", do_resize_prompt)

    app.prompt_gen_prompt_text.insert(tk.END, app.config.get("default_prompts", {}).get("image_prompt_generation", DEFAULT_CONFIG["default_prompts"]["image_prompt_generation"]))

    ttk.Label(prompt_gen_frame, text=app._t('prompt_gen_model_label')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.or_prompt_model_var = tk.StringVar(value=app.config["openrouter"]["prompt_model"])
    app.or_prompt_model_combo = ttk.Combobox(prompt_gen_frame, textvariable=app.or_prompt_model_var)
    app.or_prompt_model_combo.grid(row=1, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, app.or_prompt_model_combo)

    ttk.Label(prompt_gen_frame, text=app._t('temperature_label')).grid(row=2, column=0, sticky='w', padx=5, pady=5) 
    app.prompt_gen_temp_var = tk.DoubleVar(value=app.config["openrouter"]["prompt_params"].get("temperature", 0.8))
    prompt_gen_temp_spinbox = ttk.Spinbox(prompt_gen_frame, from_=0.0, to=2.0, increment=0.1, textvariable=app.prompt_gen_temp_var, width=10)
    prompt_gen_temp_spinbox.grid(row=2, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, prompt_gen_temp_spinbox)
    
    ttk.Label(prompt_gen_frame, text=app._t('max_tokens_label')).grid(row=3, column=0, sticky='w', padx=5, pady=5)
    app.prompt_gen_tokens_var = tk.IntVar(value=app.config["openrouter"]["prompt_params"].get("max_tokens", 500))
    prompt_gen_tokens_spinbox = ttk.Spinbox(prompt_gen_frame, from_=1, to=128000, textvariable=app.prompt_gen_tokens_var, width=10)
    prompt_gen_tokens_spinbox.grid(row=3, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, prompt_gen_tokens_spinbox)

    cta_frame = ttk.Labelframe(scrollable_frame, text=app._t('cta_settings_label'))
    cta_frame.pack(fill='x', padx=10, pady=5)
    cta_frame.grid_columnconfigure(1, weight=1)

    ttk.Label(cta_frame, text=app._t('prompt_label')).grid(row=0, column=0, sticky='nw', padx=5, pady=5)
    
    cta_container = ttk.Frame(cta_frame)
    cta_container.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
    
    initial_cta_height = app.config.get("ui_settings", {}).get("cta_text_height", 80)
    app.cta_text_frame = ttk.Frame(cta_container, height=initial_cta_height)
    app.cta_text_frame.pack(fill="x")
    app.cta_text_frame.pack_propagate(False)

    app.cta_prompt_text, text_container_widget = app._create_scrolled_text(app.cta_text_frame, height=4, width=60, relief="flat", insertbackground="white")
    text_container_widget.pack(fill="both", expand=True)
    add_text_widget_bindings(app, app.cta_prompt_text)

    cta_grip = ttk.Frame(cta_container, height=8, bootstyle="secondary", cursor="sb_v_double_arrow")
    cta_grip.pack(fill="x")

    def start_resize_cta(event):
        cta_grip.startY = event.y
        cta_grip.start_height = app.cta_text_frame.winfo_height()

    def do_resize_cta(event):
        new_height = cta_grip.start_height + (event.y - cta_grip.startY)
        if 50 <= new_height <= 400:
            app.cta_text_frame.config(height=new_height)
            canvas.update_idletasks()
            canvas.config(scrollregion=canvas.bbox("all"))

    cta_grip.bind("<ButtonPress-1>", start_resize_cta)
    cta_grip.bind("<B1-Motion>", do_resize_cta)

    app.cta_prompt_text.insert(tk.END, app.config.get("default_prompts", {}).get("call_to_action", DEFAULT_CONFIG["default_prompts"]["call_to_action"]))

    ttk.Label(cta_frame, text=app._t('model_label')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.or_cta_model_var = tk.StringVar(value=app.config["openrouter"]["cta_model"])
    app.or_cta_model_combo = ttk.Combobox(cta_frame, textvariable=app.or_cta_model_var, values=app.config["openrouter"].get("saved_models", []))
    app.or_cta_model_combo.grid(row=1, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, app.or_cta_model_combo)

    ttk.Label(cta_frame, text=app._t('temperature_label')).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    app.cta_temp_var = tk.DoubleVar(value=app.config["openrouter"]["cta_params"].get("temperature", 0.7))
    cta_temp_spinbox = ttk.Spinbox(cta_frame, from_=0.0, to=2.0, increment=0.1, textvariable=app.cta_temp_var, width=10)
    cta_temp_spinbox.grid(row=2, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, cta_temp_spinbox)

    ttk.Label(cta_frame, text=app._t('max_tokens_label')).grid(row=3, column=0, sticky='w', padx=5, pady=5)
    app.cta_tokens_var = tk.IntVar(value=app.config["openrouter"]["cta_params"].get("max_tokens", 200))
    cta_tokens_spinbox = ttk.Spinbox(cta_frame, from_=1, to=8000, textvariable=app.cta_tokens_var, width=10)
    cta_tokens_spinbox.grid(row=3, column=1, sticky='w', padx=5, pady=5)
    add_text_widget_bindings(app, cta_tokens_spinbox)

def create_montage_settings_tab(parent_tab, app):
    _, scrollable_frame = app._create_scrollable_tab(parent_tab)

    parallel_cfg = app.config.get('parallel_processing', DEFAULT_CONFIG['parallel_processing'])
    p_frame = ttk.Labelframe(scrollable_frame, text=app._t('parallel_settings_label'))
    p_frame.pack(fill='x', padx=10, pady=5)
    p_frame.grid_columnconfigure(1, weight=1)
    app.parallel_enabled_var = tk.BooleanVar(value=parallel_cfg.get('enabled', False))
    ttk.Checkbutton(p_frame, variable=app.parallel_enabled_var, text=app._t('enable_parallel_label'), bootstyle="light-round-toggle").grid(row=0, column=0, columnspan=2, sticky='w', padx=5, pady=5)
    ttk.Label(p_frame, text=app._t('num_chunks_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
    app.parallel_num_chunks_var = tk.IntVar(value=parallel_cfg.get('num_chunks', 3))
    ttk.Spinbox(p_frame, from_=1, to=20, textvariable=app.parallel_num_chunks_var, width=10).grid(row=1, column=1, sticky='w', padx=5, pady=2)
    app.parallel_keep_temps_var = tk.BooleanVar(value=parallel_cfg.get('keep_temp_files', False))
    ttk.Checkbutton(p_frame, variable=app.parallel_keep_temps_var, text=app._t('keep_temp_files_label'), bootstyle="light-round-toggle").grid(row=2, column=0, columnspan=2, sticky='w', padx=5, pady=5)
    
    montage_cfg = app.config.get('montage', {})
    montage_frame = ttk.Labelframe(scrollable_frame, text=app._t('montage_settings_label'))
    montage_frame.pack(fill='x', padx=10, pady=5)
    montage_frame.grid_columnconfigure(1, weight=1)
    
    ffmpeg_file_types = (("FFmpeg Executable", "ffmpeg.exe"), ("All files", "*.*")) if sys.platform == "win32" else (("FFmpeg Executable", "ffmpeg"), ("All files", "*"))
    ffmpeg_dialog_title = app._t('select_ffmpeg_path_title') if sys.platform == "win32" else "Select FFmpeg executable"
    
    ttk.Label(montage_frame, text=app._t('ffmpeg_path_label')).grid(row=0, column=0, sticky='w', padx=5, pady=2)
    app.montage_ffmpeg_path_var = tk.StringVar(value=montage_cfg.get('ffmpeg_path', ''))
    ffmpeg_entry = ttk.Entry(montage_frame, textvariable=app.montage_ffmpeg_path_var)
    ffmpeg_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, ffmpeg_entry)
    ttk.Button(montage_frame, text=app._t('browse_button'), command=lambda: app.select_ffmpeg_path(ffmpeg_dialog_title, ffmpeg_file_types), bootstyle="secondary-outline").grid(row=0, column=2, padx=5, pady=2)
    
    ttk.Label(montage_frame, text=app._t('whisper_model_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
    app.montage_whisper_model_var = tk.StringVar(value=montage_cfg.get('whisper_model', 'base'))
    whisper_models = ["tiny", "base", "small", "medium", "large"]
    whisper_combo = ttk.Combobox(montage_frame, textvariable=app.montage_whisper_model_var, values=whisper_models)
    whisper_combo.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, whisper_combo)
    ttk.Label(montage_frame, text=app._t('output_framerate_label')).grid(row=2, column=0, sticky='w', padx=5, pady=2)
    app.montage_output_framerate_var = tk.IntVar(value=montage_cfg.get('output_framerate', 30))
    framerate_combo = ttk.Combobox(montage_frame, textvariable=app.montage_output_framerate_var, values=[30, 60], state="readonly")
    framerate_combo.grid(row=2, column=1, sticky='w', padx=5, pady=2)
    add_text_widget_bindings(app, framerate_combo)
    
    motion_frame = ttk.Labelframe(montage_frame, text=app._t('motion_settings_label'), bootstyle="secondary")
    motion_frame.grid(row=3, column=0, columnspan=3, sticky='ew', padx=5, pady=5)
    motion_frame.grid_columnconfigure(1, weight=1)
    app.montage_motion_enabled_var = tk.BooleanVar(value=montage_cfg.get('motion_enabled', True))
    ttk.Checkbutton(motion_frame, text=app._t('enable_motion_label'), variable=app.montage_motion_enabled_var, bootstyle="light-round-toggle").grid(row=0, column=0, columnspan=2, sticky='w', padx=5)
    ttk.Label(motion_frame, text=app._t('motion_type_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
    app.montage_motion_type_var = tk.StringVar(value=montage_cfg.get('motion_type'))
    
    motion_options = [
        app._t('motion_type_swing_lr'), 
        app._t('motion_type_swing_ud'), 
        app._t('motion_type_infinity'), 
        app._t('motion_type_random')
    ]
    motion_combo = ttk.Combobox(motion_frame, textvariable=app.montage_motion_type_var, values=motion_options, state="readonly")
    motion_combo.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, motion_combo)
    ttk.Label(motion_frame, text=app._t('motion_intensity_label')).grid(row=2, column=0, sticky='w', padx=5, pady=2)
    app.montage_motion_intensity_var = tk.DoubleVar(value=montage_cfg.get('motion_intensity'))
    ttk.Scale(motion_frame, from_=0, to=20, orient=tk.HORIZONTAL, variable=app.montage_motion_intensity_var).grid(row=2, column=1, sticky='ew', padx=5, pady=2)
    
    zoom_frame = ttk.Labelframe(montage_frame, text=app._t('zoom_settings_label'), bootstyle="secondary")
    zoom_frame.grid(row=4, column=0, columnspan=3, sticky='ew', padx=5, pady=5)
    zoom_frame.grid_columnconfigure(1, weight=1)
    app.montage_zoom_enabled_var = tk.BooleanVar(value=montage_cfg.get('zoom_enabled', True))
    ttk.Checkbutton(zoom_frame, text=app._t('enable_zoom_label'), variable=app.montage_zoom_enabled_var, bootstyle="light-round-toggle").grid(row=0, column=0, columnspan=2, sticky='w', padx=5)
    ttk.Label(zoom_frame, text=app._t('zoom_intensity_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
    app.montage_zoom_intensity_var = tk.DoubleVar(value=montage_cfg.get('zoom_intensity'))
    ttk.Scale(zoom_frame, from_=0, to=20, orient=tk.HORIZONTAL, variable=app.montage_zoom_intensity_var).grid(row=1, column=1, sticky='ew', padx=5, pady=2)
    ttk.Label(zoom_frame, text=app._t('zoom_speed_label')).grid(row=2, column=0, sticky='w', padx=5, pady=2)
    app.montage_zoom_speed_var = tk.DoubleVar(value=montage_cfg.get('zoom_speed'))
    ttk.Scale(zoom_frame, from_=0.5, to=10, orient=tk.HORIZONTAL, variable=app.montage_zoom_speed_var).grid(row=2, column=1, sticky='ew', padx=5, pady=2)
    
    ttk.Label(montage_frame, text=app._t('transition_effect_label')).grid(row=5, column=0, sticky='w', padx=5, pady=2)
    app.montage_transition_var = tk.StringVar(value=montage_cfg.get('transition_effect'))
    
    transitions = [app._t('transition_none'), "fade", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown", "circleopen", "dissolve"]
    transition_combo = ttk.Combobox(montage_frame, textvariable=app.montage_transition_var, values=transitions, state="readonly")
    transition_combo.grid(row=5, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, transition_combo)
    ttk.Label(montage_frame, text=app._t('font_size_label')).grid(row=6, column=0, sticky='w', padx=5, pady=2)
    app.montage_font_size_var = tk.IntVar(value=montage_cfg.get('font_size'))
    font_size_spinbox = ttk.Spinbox(montage_frame, from_=10, to=200, textvariable=app.montage_font_size_var, width=10)
    font_size_spinbox.grid(row=6, column=1, sticky='w', padx=5, pady=2)
    add_text_widget_bindings(app, font_size_spinbox)

    codec_cfg = montage_cfg.get('codec', {})
    codec_frame = ttk.Labelframe(scrollable_frame, text=app._t('montage_codec_settings_label'))
    codec_frame.pack(fill='x', padx=10, pady=5)
    
    if sys.platform == "darwin":
        app.codec_options = {
            "libx264 (CPU)": "libx264",
            "h264_videotoolbox (Apple H.264)": "h264_videotoolbox",
            "hevc_videotoolbox (Apple H.265/HEVC)": "hevc_videotoolbox",
        }
    else:
        app.codec_options = {
            "libx264 (CPU)": "libx264",
            "h264_amf (AMD H.264)": "h264_amf",
            "hevc_amf (AMD H.265)": "hevc_amf",
            "av1_amf (AMD AV1)": "av1_amf",
            "h264_nvenc (NVIDIA H.264)": "h264_nvenc",
            "hevc_nvenc (NVIDIA H.265)": "hevc_nvenc",
        }
    
    app.codec_video_codec_var = tk.StringVar(value=codec_cfg.get('video_codec'))
    app.codec_x264_crf_var = tk.IntVar(value=codec_cfg.get('x264_crf'))
    app.codec_nvenc_cq_var = tk.IntVar(value=codec_cfg.get('nvenc_cq'))
    app.codec_amf_usage_var = tk.StringVar(value=codec_cfg.get('amf_usage'))
    app.codec_amf_quality_var = tk.StringVar(value=codec_cfg.get('amf_quality'))
    app.codec_amf_rc_var = tk.StringVar(value=codec_cfg.get('amf_rc'))
    app.codec_amf_bitrate_var = tk.StringVar(value=codec_cfg.get('amf_bitrate'))
    app.codec_vt_bitrate_var = tk.StringVar(value=codec_cfg.get('vt_bitrate', '8000k'))

    f_codec = ttk.Frame(codec_frame); f_codec.pack(fill='x', pady=5)
    ttk.Label(f_codec, text=app._t('video_codec_label'), width=15).pack(side='left', padx=5)
    app.codec_menu = ttk.Combobox(f_codec, textvariable=app.codec_video_codec_var, values=list(app.codec_options.keys()), state="readonly", width=35)
    app.codec_menu.pack(side='left', padx=5)
    add_text_widget_bindings(app, app.codec_menu)
    app.codec_menu.bind("<<ComboboxSelected>>", app.update_codec_settings_ui)

    app.x264_settings_frame = ttk.Labelframe(codec_frame, text=app._t('x264_settings_label'), bootstyle="secondary")
    app.amf_settings_frame = ttk.Labelframe(codec_frame, text=app._t('amf_settings_label'), bootstyle="secondary")
    app.nvenc_settings_frame = ttk.Labelframe(codec_frame, text=app._t('nvenc_settings_label'), bootstyle="secondary")
    app.vt_settings_frame = ttk.Labelframe(codec_frame, text=app._t('apple_vt_settings_label'), bootstyle="secondary")

    f = ttk.Frame(app.x264_settings_frame); f.pack(fill='x', pady=2, padx=5)
    ttk.Label(f, text=app._t('crf_label')).pack(side="left", padx=(0,5))
    ttk.Scale(f, from_=0, to=51, orient=tk.HORIZONTAL, variable=app.codec_x264_crf_var, length=300).pack(side="left", fill="x", expand=True)
    
    f = ttk.Frame(app.amf_settings_frame); f.pack(fill='x', pady=2, padx=5)
    ttk.Label(f, text=app._t('usage_label'), width=15, anchor='w').pack(side='left')
    amf_usage_combo = ttk.Combobox(f, textvariable=app.codec_amf_usage_var, values=['transcoding', 'ultralowlatency', 'lowlatency', 'webcam', 'high_quality'], state="readonly", width=20)
    amf_usage_combo.pack(side='left', padx=5)
    add_text_widget_bindings(app, amf_usage_combo)
    
    f = ttk.Frame(app.amf_settings_frame); f.pack(fill='x', pady=2, padx=5)
    ttk.Label(f, text=app._t('quality_label'), width=15, anchor='w').pack(side='left')
    amf_quality_combo = ttk.Combobox(f, textvariable=app.codec_amf_quality_var, values=['speed', 'balanced', 'quality', 'high_quality'], state="readonly", width=20)
    amf_quality_combo.pack(side='left', padx=5)
    add_text_widget_bindings(app, amf_quality_combo)
    
    f = ttk.Frame(app.amf_settings_frame); f.pack(fill='x', pady=2, padx=5)
    ttk.Label(f, text=app._t('rate_control_label'), width=15, anchor='w').pack(side='left')
    amf_rc_combo = ttk.Combobox(f, textvariable=app.codec_amf_rc_var, values=['cqp', 'cbr', 'vbr_peak', 'vbr_latency', 'qvbr'], state="readonly", width=20)
    amf_rc_combo.pack(side='left', padx=5)
    add_text_widget_bindings(app, amf_rc_combo)
    
    f = ttk.Frame(app.amf_settings_frame); f.pack(fill='x', pady=2, padx=5)
    ttk.Label(f, text=app._t('bitrate_label'), width=20, anchor='w').pack(side='left')
    amf_bitrate_entry = ttk.Entry(f, textvariable=app.codec_amf_bitrate_var, width=22)
    amf_bitrate_entry.pack(side='left', padx=5)
    add_text_widget_bindings(app, amf_bitrate_entry)
    
    f = ttk.Frame(app.nvenc_settings_frame); f.pack(fill='x', pady=2, padx=5)
    ttk.Label(f, text=app._t('cq_label')).pack(side="left", padx=(0,5))
    ttk.Scale(f, from_=0, to=51, orient=tk.HORIZONTAL, variable=app.codec_nvenc_cq_var, length=300).pack(side="left", fill="x", expand=True)

    f = ttk.Frame(app.vt_settings_frame); f.pack(fill='x', pady=2, padx=5)
    ttk.Label(f, text=app._t('bitrate_label'), width=15, anchor='w').pack(side='left')
    vt_bitrate_entry = ttk.Entry(f, textvariable=app.codec_vt_bitrate_var, width=22)
    vt_bitrate_entry.pack(side='left', padx=5)
    add_text_widget_bindings(app, vt_bitrate_entry)

    # --- Кнопка попереднього перегляду ---
    preview_frame = ttk.Frame(scrollable_frame)
    preview_frame.pack(fill='x', padx=10, pady=10)
    
    app.preview_button = ttk.Button(
        preview_frame, 
        text=app._t('preview_button_text'), 
        command=app._preview_montage, 
        bootstyle="info"
    )
    app.preview_button.pack()

    app.update_codec_settings_ui()

def create_other_settings_tab(parent_tab, app):
    _, scrollable_frame = app._create_scrollable_tab(parent_tab)

    general_frame = ttk.Labelframe(scrollable_frame, text=app._t('general_settings_label'))
    general_frame.pack(fill='x', padx=10, pady=5)
    general_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(general_frame, text=app._t('language_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.language_var = tk.StringVar(value="Українська" if app.lang == "ua" else "English")
    lang_combo = ttk.Combobox(general_frame, textvariable=app.language_var, values=["Українська", "English"], state="readonly")
    lang_combo.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, lang_combo)
    lang_combo.bind("<<ComboboxSelected>>", app.change_language)

    ttk.Label(general_frame, text=app._t('theme_label')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    app.theme_var = tk.StringVar()
    
    theme_display_names = [app._t('theme_darkly'), app._t('theme_cyborg'), app._t('theme_litera')]
    theme_combo = ttk.Combobox(general_frame, textvariable=app.theme_var, values=theme_display_names, state="readonly")
    theme_combo.grid(row=1, column=1, sticky='ew', padx=5, pady=5)
    add_text_widget_bindings(app, theme_combo)
    theme_combo.bind("<<ComboboxSelected>>", app.on_theme_changed)
    
    theme_combo['values'] = list(app.theme_map_to_display.values())
    
    # Встановлюємо відображуване значення
    current_theme_key = app.config.get("ui_settings", {}).get("theme", "darkly")
    display_value = app.theme_map_to_display.get(current_theme_key, app._t('theme_darkly'))
    app.theme_var.set(display_value)

    app.image_control_var = tk.BooleanVar(value=app.config.get("ui_settings", {}).get("image_control_enabled", False))
    ttk.Checkbutton(general_frame, variable=app.image_control_var, text=app._t('image_control_label')).grid(row=3, column=0, columnspan=2, sticky='w', padx=5, pady=5)

    # --- Нові налаштування авто-перемикання ---
    auto_switch_frame = ttk.Frame(general_frame)
    auto_switch_frame.grid(row=4, column=0, columnspan=3, sticky='w', padx=5, pady=5)

    app.auto_switch_var = tk.BooleanVar(value=app.config.get("ui_settings", {}).get("auto_switch_service_on_fail", False))
    ttk.Checkbutton(auto_switch_frame, variable=app.auto_switch_var, text=app._t('auto_switch_service_label')).pack(side='left', anchor='w')
    
    ttk.Label(auto_switch_frame, text=app._t('retry_limit_label')).pack(side='left', padx=(10, 2))
    app.auto_switch_retries_var = tk.IntVar(value=app.config.get("ui_settings", {}).get("auto_switch_retry_limit", 10))
    ttk.Spinbox(auto_switch_frame, from_=1, to=50, textvariable=app.auto_switch_retries_var, width=5).pack(side='left')


    output_cfg = app.config.get('output_settings', DEFAULT_CONFIG['output_settings'])
    output_frame = ttk.Labelframe(scrollable_frame, text=app._t('output_settings_label'))
    output_frame.pack(fill='x', padx=10, pady=5)
    output_frame.grid_columnconfigure(1, weight=1)

    app.output_use_default_var = tk.BooleanVar(value=output_cfg.get('use_default_dir', False))
    use_default_cb = ttk.Checkbutton(output_frame, variable=app.output_use_default_var, text=app._t('use_default_dir_label'), bootstyle="light-round-toggle", command=app.toggle_default_dir_widgets)
    use_default_cb.grid(row=0, column=0, columnspan=3, sticky='w', padx=5, pady=5)

    ttk.Label(output_frame, text=app._t('default_dir_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
    app.output_default_dir_var = tk.StringVar(value=output_cfg.get('default_dir', ''))
    app.output_default_dir_entry = ttk.Entry(output_frame, textvariable=app.output_default_dir_var)
    app.output_default_dir_entry.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, app.output_default_dir_entry)
    app.output_default_dir_button = ttk.Button(output_frame, text=app._t('browse_button'), command=app.browse_default_dir, bootstyle="secondary-outline")
    app.output_default_dir_button.grid(row=1, column=2, padx=5, pady=2)

    ttk.Label(output_frame, text=app._t('rewrite_default_dir_label')).grid(row=2, column=0, sticky='w', padx=5, pady=2)
    app.output_rewrite_default_dir_var = tk.StringVar(value=output_cfg.get('rewrite_default_dir', ''))
    app.output_rewrite_default_dir_entry = ttk.Entry(output_frame, textvariable=app.output_rewrite_default_dir_var)
    app.output_rewrite_default_dir_entry.grid(row=2, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, app.output_rewrite_default_dir_entry)
    app.output_rewrite_default_dir_button = ttk.Button(output_frame, text=app._t('browse_button'), command=app.browse_rewrite_default_dir, bootstyle="secondary-outline")
    app.output_rewrite_default_dir_button.grid(row=2, column=2, padx=5, pady=2)
    
    app.toggle_default_dir_widgets()

    # (Firebase settings moved exclusively to API tab – duplicate section removed)

    templates_frame = ttk.Labelframe(scrollable_frame, text=app._t('rewrite_templates_label'))
    templates_frame.pack(fill='x', padx=10, pady=5)
    templates_frame.grid_columnconfigure(0, weight=1)

    app.rewrite_templates_listbox = tk.Listbox(templates_frame, height=5, relief="flat", highlightthickness=0)
    app.rewrite_templates_listbox.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
    add_text_widget_bindings(app, app.rewrite_templates_listbox)
    
    templates_btn_frame = ttk.Frame(templates_frame)
    templates_btn_frame.grid(row=0, column=1, sticky='ns', padx=5, pady=5)
    ttk.Button(templates_btn_frame, text=app._t('add_button'), command=app.add_rewrite_template, bootstyle="info-outline").pack(fill='x', pady=2)
    ttk.Button(templates_btn_frame, text=app._t('remove_button'), command=app.remove_rewrite_template, bootstyle="danger-outline").pack(fill='x', pady=2)

    rewrite_cfg = app.config.get('rewrite_settings', DEFAULT_CONFIG['rewrite_settings'])
    rewrite_settings_frame = ttk.Labelframe(scrollable_frame, text=app._t('rewrite_settings_label'))
    rewrite_settings_frame.pack(fill='x', padx=10, pady=5)
    rewrite_settings_frame.grid_columnconfigure(1, weight=1)
    ttk.Label(rewrite_settings_frame, text=app._t('download_threads_label')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    app.rewrite_download_threads_var = tk.IntVar(value=rewrite_cfg.get('download_threads', 4))
    ttk.Spinbox(rewrite_settings_frame, from_=1, to=20, textvariable=app.rewrite_download_threads_var, width=10).grid(row=0, column=1, sticky='w', padx=5, pady=5)
    
    tg_cfg = app.config.get('telegram', DEFAULT_CONFIG['telegram'])
    tg_frame = ttk.Labelframe(scrollable_frame, text=app._t('telegram_settings_label'))
    tg_frame.pack(fill='x', padx=10, pady=5)
    tg_frame.grid_columnconfigure(1, weight=1)

    app.tg_enabled_var = tk.BooleanVar(value=tg_cfg.get('enabled', False))
    ttk.Checkbutton(tg_frame, variable=app.tg_enabled_var, text=app._t('enable_telegram_label'), bootstyle="light-round-toggle").grid(row=0, column=0, columnspan=3, sticky='w', padx=5, pady=5)

    ttk.Label(tg_frame, text=app._t('api_key_label')).grid(row=1, column=0, sticky='w', padx=5, pady=2)
    app.tg_api_key_var = tk.StringVar(value=tg_cfg.get('api_key', ''))
    tg_api_key_entry = ttk.Entry(tg_frame, textvariable=app.tg_api_key_var, show="*")
    tg_api_key_entry.grid(row=1, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, tg_api_key_entry)

    ttk.Label(tg_frame, text=app._t('chat_id_label')).grid(row=2, column=0, sticky='w', padx=5, pady=2)
    app.tg_chat_id_var = tk.StringVar(value=tg_cfg.get('chat_id', ''))
    tg_chat_id_entry = ttk.Entry(tg_frame, textvariable=app.tg_chat_id_var)
    tg_chat_id_entry.grid(row=2, column=1, sticky='ew', padx=5, pady=2)
    add_text_widget_bindings(app, tg_chat_id_entry)
    
    ttk.Button(tg_frame, text=app._t('test_telegram_button'), command=app.test_telegram_connection, bootstyle="secondary-outline").grid(row=1, column=2, rowspan=2, padx=5, pady=2, sticky='ns')

    # Новий віджет для вибору режиму звіту
    ttk.Label(tg_frame, text=app._t('report_timing_label')).grid(row=3, column=0, sticky='w', padx=5, pady=5)
    app.tg_report_timing_var = tk.StringVar(value=tg_cfg.get('report_timing', 'per_task'))
    report_timing_combo = ttk.Combobox(tg_frame, textvariable=app.tg_report_timing_var, 
                                       values=['per_task', 'per_language'], 
                                       state="readonly")
    report_timing_combo.grid(row=3, column=1, sticky='ew', padx=5, pady=5)
    # Перекладаємо значення для відображення
    app.report_timing_display_map = {
        'per_task': app._t('report_timing_per_task'),
        'per_language': app._t('report_timing_per_language')
    }
    report_timing_combo['values'] = list(app.report_timing_display_map.values())
    
    # Встановлюємо відображуване значення
    current_timing_key = app.tg_report_timing_var.get()
    display_value = app.report_timing_display_map.get(current_timing_key, app._t('report_timing_per_task'))
    app.tg_report_timing_var.set(display_value)