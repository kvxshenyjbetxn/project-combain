# constants/log_filters.py

"""
Конфігурація фільтрів для логування.
Тут зібрані всі технічні повідомлення, які не повинні відображатися в GUI користувача
та не відправлятись в мобільний додаток, але залишаються у файлових логах.
"""

# Точні повідомлення, які повністю фільтруються з GUI
TECHNICAL_MESSAGES = [
    "Програму запущено. Логування в інтерфейс активовано.",
    "Firebase -> Очищення посилань на зображення з бази даних...",
    "Firebase -> Посилання на зображення видалено.",
    "Firebase -> Очищення файлів зображень зі Storage...",
    "Firebase -> Файли зображень зі Storage видалено.",
    "Auto-cleared old gallery images from Firebase on application startup",
    "Auto-cleared old gallery images from Firebase for new generation session",
    "Firebase -> Очищено статус готовності до монтажу",
    "Cleared montage ready status on application startup",
    "Firebase -> Відправлено статус готовності до монтажу",
]

# Префікси повідомлень, які фільтруються з GUI
TECHNICAL_MESSAGE_PREFIXES = [
    "Firebase -> Додано посилання на зображення в базу даних:",
    "Firebase -> Оновлено посилання на зображення в базі даних:",
    "Firebase -> Видалено зображення з бази даних:",
    "Firebase -> Видалено зображення зі Storage:",
    "Firebase -> Зображення видалено зі Storage:",
    "Firebase -> Лог успішно надіслано:",
]

def is_technical_message(message):
    """
    Перевіряє чи є повідомлення технічним (яке треба приховати з GUI).
    
    Args:
        message (str): Повідомлення для перевірки
        
    Returns:
        bool: True якщо повідомлення технічне і має бути приховано з GUI
    """
    # Точний збіг з технічними повідомленнями
    if message in TECHNICAL_MESSAGES:
        return True
    
    # Перевірка префіксів
    for prefix in TECHNICAL_MESSAGE_PREFIXES:
        if message.startswith(prefix):
            return True
    
    return False

def add_technical_message(message):
    """
    Додає нове технічне повідомлення до фільтра.
    
    Args:
        message (str): Повідомлення для додавання до фільтра
    """
    if message not in TECHNICAL_MESSAGES:
        TECHNICAL_MESSAGES.append(message)

def add_technical_prefix(prefix):
    """
    Додає новий префікс для фільтрації технічних повідомлень.
    
    Args:
        prefix (str): Префікс для додавання до фільтра
    """
    if prefix not in TECHNICAL_MESSAGE_PREFIXES:
        TECHNICAL_MESSAGE_PREFIXES.append(prefix)
