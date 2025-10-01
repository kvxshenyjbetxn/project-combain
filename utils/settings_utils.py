# utils/settings_utils.py

import tkinter as tk
from tkinter import messagebox
from utils.config_utils import save_config, setup_ffmpeg_path
from api.elevenlabs_api import ElevenLabsAPI
from api.montage_api import MontageAPI
from api.openrouter_api import OpenRouterAPI
from api.pollinations_api import PollinationsAPI
from api.recraft_api import RecraftAPI
from api.telegram_api import TelegramAPI
from api.voicemaker_api import VoiceMakerAPI
from api.speechify_api import SpeechifyAPI
from api.firebase_api import FirebaseAPI


def save_settings(app_instance):
    """
    Зберігає всі налаштування додатку.
    
    Args:
        app_instance: Екземпляр класу TranslationApp
    """
    app = app_instance
    
    # Parallel processing settings
    if 'parallel_processing' not in app.config: 
        app.config['parallel_processing'] = {}
    app.config['parallel_processing']['enabled'] = app.parallel_enabled_var.get()
    app.config['parallel_processing']['num_chunks'] = app.parallel_num_chunks_var.get()
    app.config['parallel_processing']['keep_temp_files'] = app.parallel_keep_temps_var.get()
    
    # OpenRouter settings
    app.config["openrouter"]["api_key"] = app.or_api_key_var.get()
    app.config["openrouter"]["translation_model"] = app.or_trans_model_var.get()
    app.config["openrouter"]["prompt_model"] = app.or_prompt_model_var.get()
    app.config["openrouter"]["cta_model"] = app.or_cta_model_var.get()
    app.config["openrouter"]["rewrite_model"] = app.or_rewrite_model_var.get()
    app.config["openrouter"]["saved_models"] = list(app.or_models_listbox.get(0, tk.END))
    app.config["openrouter"]["translation_params"]["temperature"] = app.trans_temp_var.get()
    app.config["openrouter"]["translation_params"]["max_tokens"] = app.trans_tokens_var.get()
    app.config["openrouter"]["rewrite_params"]["temperature"] = app.rewrite_temp_var.get()
    app.config["openrouter"]["rewrite_params"]["max_tokens"] = app.rewrite_tokens_var.get()
    app.config["openrouter"]["prompt_params"]["temperature"] = app.prompt_gen_temp_var.get()
    app.config["openrouter"]["prompt_params"]["max_tokens"] = app.prompt_gen_tokens_var.get()
    app.config["openrouter"]["cta_params"]["temperature"] = app.cta_temp_var.get()
    app.config["openrouter"]["cta_params"]["max_tokens"] = app.cta_tokens_var.get()
    
    # Default prompts
    app.config["default_prompts"]["image_prompt_generation"] = app.prompt_gen_prompt_text.get("1.0", tk.END).strip()
    app.config["default_prompts"]["call_to_action"] = app.cta_prompt_text.get("1.0", tk.END).strip()
    
    # Pollinations settings
    app.config["pollinations"]["token"] = app.poll_token_var.get()
    app.config["pollinations"]["model"] = app.poll_model_var.get()
    app.config["pollinations"]["width"] = app.poll_width_var.get()
    app.config["pollinations"]["height"] = app.poll_height_var.get()
    app.config["pollinations"]["timeout"] = app.poll_timeout_var.get()
    app.config['ui_settings']['image_generation_api'] = app.active_image_api_var.get()
    app.config["pollinations"]["remove_logo"] = app.poll_remove_logo_var.get()
    
    # Recraft settings
    if 'recraft' not in app.config: 
        app.config['recraft'] = {}
    app.config['recraft']['api_key'] = app.recraft_api_key_var.get()
    app.config['recraft']['model'] = app.recraft_model_var.get()
    app.config['recraft']['style'] = app.recraft_style_var.get()
    app.config['recraft']['substyle'] = app.recraft_substyle_var.get()
    app.config['recraft']['size'] = app.recraft_size_var.get().split(' ')[0]
    app.config['recraft']['negative_prompt'] = app.recraft_negative_prompt_var.get()
    
    # ElevenLabs settings
    app.config["elevenlabs"]["api_key"] = app.el_api_key_var.get()
    
    # VoiceMaker settings
    if 'voicemaker' not in app.config: 
        app.config['voicemaker'] = {}
    app.config['voicemaker']['api_key'] = app.vm_api_key_var.get()
    app.config['voicemaker']['char_limit'] = app.vm_char_limit_var.get()

    # Speechify configuration
    if 'speechify' not in app.config: 
        app.config['speechify'] = {}
    app.config['speechify']['api_key'] = app.speechify_api_key_var.get()
    
    # Output settings
    if 'output_settings' not in app.config: 
        app.config['output_settings'] = {}
    app.config['output_settings']['use_default_dir'] = app.output_use_default_var.get()
    app.config['output_settings']['default_dir'] = app.output_default_dir_var.get()
    app.config['output_settings']['rewrite_default_dir'] = app.output_rewrite_default_dir_var.get()
    
    # Rewrite settings
    if 'rewrite_settings' not in app.config: 
        app.config['rewrite_settings'] = {}
    app.config['rewrite_settings']['download_threads'] = app.rewrite_download_threads_var.get()
    
    # Telegram settings
    if 'telegram' not in app.config: 
        app.config['telegram'] = {}
    app.config['telegram']['enabled'] = app.tg_enabled_var.get()
    
    # Firebase settings
    if 'firebase' not in app.config:
        app.config['firebase'] = {}
    app.config['firebase']['enabled'] = app.firebase_enabled_var.get()
    app.config['telegram']['api_key'] = app.tg_api_key_var.get()
    app.config['telegram']['chat_id'] = app.tg_chat_id_var.get()

    # Firebase settings
    if 'firebase' not in app.config: 
        app.config['firebase'] = {}
    app.config['firebase']['auto_clear_gallery'] = app.firebase_auto_clear_gallery_var.get()

    # Зберігаємо нове налаштування режиму звіту
    display_value = app.tg_report_timing_var.get()
    # Знаходимо ключ ('per_task' або 'per_language') за відображуваним значенням
    internal_value = next((k for k, v in app.report_timing_display_map.items() if v == display_value), 'per_task')
    app.config['telegram']['report_timing'] = internal_value
    # Видаляємо збереження старих налаштувань notify_on
    if 'notify_on' in app.config['telegram']:
        del app.config['telegram']['notify_on']
    
    # Montage settings
    if 'montage' not in app.config: 
        app.config['montage'] = {}
    app.config['montage']['ffmpeg_path'] = app.montage_ffmpeg_path_var.get()
    app.config['montage']['whisper_model'] = app.montage_whisper_model_var.get()
    app.config['montage']['motion_enabled'] = app.montage_motion_enabled_var.get()
    app.config['montage']['motion_type'] = app.montage_motion_type_var.get()
    app.config['montage']['motion_intensity'] = app.montage_motion_intensity_var.get()
    app.config['montage']['zoom_enabled'] = app.montage_zoom_enabled_var.get()
    app.config['montage']['zoom_intensity'] = app.montage_zoom_intensity_var.get()
    app.config['montage']['zoom_speed'] = app.montage_zoom_speed_var.get()
    app.config['montage']['transition_effect'] = app.montage_transition_var.get()
    app.config['montage']['font_size'] = app.montage_font_size_var.get()
    app.config['montage']['font_style'] = app.montage_font_style_var.get()
    app.config['montage']['output_framerate'] = app.montage_output_framerate_var.get()
    
    # Codec settings
    if 'codec' not in app.config['montage']: 
        app.config['montage']['codec'] = {}
    app.config['montage']['codec']['video_codec'] = app.codec_video_codec_var.get()
    app.config['montage']['codec']['x264_crf'] = app.codec_x264_crf_var.get()
    app.config['montage']['codec']['nvenc_cq'] = app.codec_nvenc_cq_var.get()
    app.config['montage']['codec']['amf_usage'] = app.codec_amf_usage_var.get()
    app.config['montage']['codec']['amf_quality'] = app.codec_amf_quality_var.get()
    app.config['montage']['codec']['amf_rc'] = app.codec_amf_rc_var.get()
    app.config['montage']['codec']['amf_bitrate'] = app.codec_amf_bitrate_var.get()
    app.config['montage']['codec']['vt_bitrate'] = app.codec_vt_bitrate_var.get()
    
    # Rewrite prompt templates
    if "rewrite_prompt_templates" not in app.config:
        app.config["rewrite_prompt_templates"] = {}
    current_templates = list(app.rewrite_templates_listbox.get(0, tk.END))
    for template_name in list(app.config["rewrite_prompt_templates"].keys()):
        if template_name not in current_templates:
            del app.config["rewrite_prompt_templates"][template_name]
    for template_name in current_templates:
        if template_name not in app.config["rewrite_prompt_templates"]:
             app.config["rewrite_prompt_templates"][template_name] = {}
    
    # UI settings
    if 'ui_settings' not in app.config: 
        app.config['ui_settings'] = {}
    app.config['ui_settings']['image_generation_api'] = app.active_image_api_var.get()
    
    selected_display_name = app.theme_var.get()
    app.config['ui_settings']['theme'] = app.theme_map_to_internal.get(selected_display_name, "darkly")
    
    app.config['ui_settings']['image_control_enabled'] = app.image_control_var.get()
    app.config['ui_settings']['auto_switch_service_on_fail'] = app.auto_switch_var.get()
    app.config['ui_settings']['auto_switch_retry_limit'] = app.auto_switch_retries_var.get()

    # Зберігаємо конфігурацію
    save_config(app.config)
    
    # Перестворюємо API об'єкти з новими налаштуваннями
    app.or_api = OpenRouterAPI(app.config)
    app.poll_api = PollinationsAPI(app.config, app)
    app.recraft_api = RecraftAPI(app.config)
    app.el_api = ElevenLabsAPI(app.config)
    app.vm_api = VoiceMakerAPI(app.config)
    app.tg_api = TelegramAPI(app.config)
    app.firebase_api = FirebaseAPI(app.config)
    app.speechify_api = SpeechifyAPI(app.config)
    app.montage_api = MontageAPI(app.config, app, app.update_progress_for_montage)
    
    # Налаштовуємо шлях до ffmpeg
    setup_ffmpeg_path(app.config)
    
    # Оновлюємо інтерфейс
    if app.selected_lang_code:
        app.update_language_voice_dropdowns(app.selected_lang_code)
    app.update_path_widgets_state()
    
    # Показуємо повідомлення про успішне збереження
    messagebox.showinfo(app._t('saved_title'), app._t('info_settings_saved'))
