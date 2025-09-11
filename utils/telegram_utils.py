# utils/telegram_utils.py

import logging
import tkinter as tk
from tkinter import messagebox

logger = logging.getLogger(__name__)

def send_telegram_error_notification(app_instance, task_name, lang_code, step, error_details):
    """Негайно відправляє сповіщення про помилку."""
    message = (
        f"❌ *Виникла помилка під час виконання\\!* ❌\n\n"
        f"*Завдання:* {app_instance._escape_markdown(task_name)}\n"
        f"*Мова:* {app_instance._escape_markdown(lang_code.upper())}\n"
        f"*Етап:* {app_instance._escape_markdown(step)}\n"
        f"*Помилка:* {app_instance._escape_markdown(error_details)}"
    )
    app_instance.tg_api.send_message_in_thread(message)

def send_task_completion_report(app_instance, task_config, single_lang_code=None):
    """Формує та відправляє фінальний звіт по завершенню всього завдання або однієї мови."""
    task_name = app_instance._escape_markdown(task_config.get('task_name', 'Невідоме завдання'))
    
    langs_to_report = [single_lang_code] if single_lang_code else task_config['selected_langs']
    
    # Визначаємо заголовок
    if single_lang_code:
        escaped_lang_code = app_instance._escape_markdown(single_lang_code.upper())
        report_lines = [f"✅ *Завдання \"{task_name}\" для мови {escaped_lang_code} завершено\\!* ✅\n"]
    else:
        report_lines = [f"✅ *Завдання \"{task_name}\" повністю завершено\\!* ✅\n"]

    task_key_prefix = f"{task_config['task_index']}_"

    for lang_code in langs_to_report:
        task_key = task_key_prefix + lang_code
        status = app_instance.task_completion_status.get(task_key)
        if not status: continue

        report_lines.append(app_instance._escape_markdown(f"---"))
        lang_flags = {"it": "🇮🇹", "ro": "🇷🇴", "ua": "🇺🇦", "en": "🇬🇧", "pl": "🇵🇱", "de": "🇩🇪", "fr": "🇫🇷", "es": "🇪🇸"}
        flag = lang_flags.get(lang_code.lower(), "")
        escaped_lang_code = app_instance._escape_markdown(lang_code.upper())
        report_lines.append(f"{flag} *Мова: {escaped_lang_code}*")
        report_lines.append(app_instance._escape_markdown(f"---"))

        # Проходимо по ключах та значеннях правильно
        for step_name, result_icon in status['steps'].items():
            escaped_step_name = app_instance._escape_markdown(step_name)
            
            # Спеціальна логіка для кроку генерації зображень
            if step_name == app_instance._t('step_name_gen_images'):
                images_generated = status.get("images_generated", 0)
                total_images = status.get("total_images", 0)
                count_text = app_instance._escape_markdown(f"({images_generated}/{total_images} шт.)")
                
                # Визначаємо іконку на основі реальних даних, а не попередньо встановленої
                current_icon = result_icon
                if total_images > 0: # Якщо зображення планувались
                    if images_generated == total_images:
                        current_icon = "✅"
                    elif images_generated > 0:
                        current_icon = "⚠️" # Частково виконано
                    else:
                        current_icon = "❌"
                
                # Якщо крок був пропущений (total_images == 0), іконка залишиться "⚪️"
                if current_icon == "❌":
                    report_lines.append(f"• {current_icon} ~{escaped_step_name}~ *{count_text}*")
                else:
                    report_lines.append(f"• {current_icon} {escaped_step_name} *{count_text}*")
            
            elif result_icon == "❌":
                report_lines.append(f"• {result_icon} ~{escaped_step_name}~")
            elif result_icon == "⚪️":
                 skipped_text = app_instance._escape_markdown("(пропущено)")
                 report_lines.append(f"• {result_icon} {escaped_step_name} *{skipped_text}*")
            else:
                report_lines.append(f"• {result_icon} {escaped_step_name}")
    
    app_instance.tg_api.send_message_in_thread("\n".join(report_lines))

def test_telegram_connection(app_instance):
    """Test Telegram API connection and display results."""
    from api.telegram_api import TelegramAPI
    
    api_key = app_instance.tg_api_key_var.get()
    temp_config = {"telegram": {"api_key": api_key}}
    temp_api = TelegramAPI(temp_config)
    success, message = temp_api.test_connection()
    if success:
        messagebox.showinfo(app_instance._t('test_connection_title_tg'), message)
    else:
        messagebox.showerror(app_instance._t('test_connection_title_tg'), message)
