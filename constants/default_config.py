import sys

DEFAULT_CONFIG = {
    "openrouter": {
        "api_key": "",
        "translation_model": "openai/gpt-4o-mini",
        "prompt_model": "openai/gpt-4o-mini",
        "cta_model": "openai/gpt-4o-mini",
        "rewrite_model": "openai/gpt-4o-mini",
        "saved_models": [
            "openai/gpt-4o-mini",
            "google/gemini-flash-1.5",
            "anthropic/claude-3-haiku",
            "mistralai/mistral-7b-instruct"
        ],
        "translation_params": {"temperature": 0.7, "max_tokens": 1000},
        "prompt_params": {"temperature": 0.8, "max_tokens": 500},
        "cta_params": {"temperature": 0.7, "max_tokens": 200},
        "rewrite_params": {"temperature": 0.7, "max_tokens": 4000}
    },
    "pollinations": {
        "token": "",
        "model": "flux",
        "width": 1920,
        "height": 1080,
        "timeout": 6,
        "retries": 5,
        "remove_logo": True
    },
    "recraft": {
        "api_key": "",
        "model": "recraftv3",
        "style": "digital_illustration",
        "substyle": "",
        "size": "1820x1024", # Додано
        "negative_prompt": "" # Додано
    },
    "elevenlabs": {
        "api_key": "",
        "base_url": "https://voiceapi.csv666.ru"
    },
    "voicemaker": {
        "api_key": "",
        "char_limit": 2900
    },
    "speechify": {
        "api_key": "",
        "base_url": "https://api.sws.speechify.com/v1"
    },
    "telegram": {
        "enabled": False,
        "api_key": "",
        "chat_id": "",
        "notify_on": {
            "translate": True,
            "cta": False,
            "gen_prompts": False,
            "gen_images": True,
            "audio": True,
            "create_subtitles": False,
            "create_video": True,
            "download": True,
            "transcribe": True,
            "rewrite": True
        }
    },
    "parallel_processing": {
        "enabled": True,
        "num_chunks": 3,
        "keep_temp_files": False
    },
    "rewrite_settings": {
        "download_threads": 4,
        "processed_links_file": "processed_links.txt"
    },
    "montage": {
        "whisper_model": "base",
        "ffmpeg_path": "",
        "motion_enabled": True,
        "motion_type": "Гойдання (знак нескінченності)",
        "motion_intensity": 5.0,
        "zoom_enabled": True,
        "zoom_intensity": 10.0,
        "zoom_speed": 1.0,
        "transition_effect": "fade",
        "font_size": 48,
        "output_framerate": 30,
        "codec": {
            "video_codec": "h264_amf (AMD H.264)" if sys.platform == 'win32' else 'libx264 (CPU)',
            "x264_crf": 23,
            "nvenc_cq": 23,
            "amf_usage": "transcoding",
            "amf_rc": "cqp",
            "amf_quality": "balanced",
            "amf_bitrate": "8000k",
            "vt_bitrate": "8000k"
        }
    },
    "output_settings": {
        "use_default_dir": False,
        "default_dir": "",
        "rewrite_default_dir": "",
    },
    "rewrite_prompt_templates": {
        "Default": {
            "ua": "Перефразуй наступний текст українською мовою, зберігаючи основний зміст, але роблячи його унікальним: {text}"
        }
    },
    "languages": {
        "ua": {
            "prompt": "Переклади наступний текст українською мовою: {text}",
            "rewrite_prompt": "Перефразуй наступний текст українською мовою, зберігаючи основний зміст, але роблячи його унікальним: {text}",
            "tts_service": "elevenlabs",
            "elevenlabs_template_uuid": None,
            "voicemaker_voice_id": "ai3-uk-UA-Olena",
            "voicemaker_engine": "neural",
            "speechify_voice_id": "anatoly",
            "speechify_model": "simba-multilingual",
            "speechify_language": "Ukrainian",
            "speechify_emotion": "Без емоцій",
            "speechify_pitch": 0,
            "speechify_rate": 0
        }
    },
    "default_prompts": {
        "translation": "Translate the following text to {language}: {text}",
        "image_prompt_generation": "Based on the following text, generate 3 detailed image prompts in English, one per line, without any numbering or prefixes:\n{text}",
        "call_to_action": "Based on the following text, write a short and engaging call to action for a YouTube video, encouraging viewers to watch until the end. Keep it under 150 characters:\n{text}"
    },
    "ui_settings": {
        "language": "ua",
        "theme": "darkly",
        "image_generation_api": "pollinations",
        "main_text_height": 150,
        "prompt_text_height": 80,
        "lang_text_height": 75,
        "cta_text_height": 80,
        "rewrite_prompt_height": 75,
        "queue_column_widths": {
            "task_details": 400,
            "time": 150,
            "status": 100
        },
        "image_control_enabled": False
    }
}