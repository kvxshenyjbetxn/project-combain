# utils/firebase_utils.py

from tkinter import messagebox


def clear_user_logs(app_instance):
    """Очищує логи поточного користувача."""
    if not hasattr(app_instance, 'firebase_api') or not app_instance.firebase_api or not app_instance.firebase_api.is_initialized:
        messagebox.showerror(app_instance._t('error_title'), "Firebase не підключено!")
        return
        
    user_id = app_instance.firebase_api.get_current_user_id()
    if not user_id or user_id == "default":
        messagebox.showerror(app_instance._t('error_title'), "User ID не ініціалізовано!")
        return
        
    if messagebox.askyesno(app_instance._t('confirm_title'), 
                         f"Очистити всі логи для користувача '{user_id}'?\n\nЦе дія незворотна!"):
        success = app_instance.firebase_api.clear_user_logs()
        if success:
            refresh_user_stats(app_instance)
            messagebox.showinfo(app_instance._t('info_title'), "Ваші логи успішно очищено!")
        else:
            messagebox.showerror(app_instance._t('error_title'), "Помилка очищення логів!")


def clear_user_images(app_instance):
    """Очищує зображення поточного користувача."""
    if not hasattr(app_instance, 'firebase_api') or not app_instance.firebase_api or not app_instance.firebase_api.is_initialized:
        messagebox.showerror(app_instance._t('error_title'), "Firebase не підключено!")
        return
        
    user_id = app_instance.firebase_api.get_current_user_id()
    if not user_id or user_id == "default":
        messagebox.showerror(app_instance._t('error_title'), "User ID не ініціалізовано!")
        return
        
    if messagebox.askyesno(app_instance._t('confirm_title'), 
                         f"Очистити всі зображення для користувача '{user_id}'?\n\nЦе дія незворотна!"):
        success = app_instance.firebase_api.clear_user_images()
        if success:
            refresh_user_stats(app_instance)
            messagebox.showinfo(app_instance._t('info_title'), "Ваші зображення успішно очищено!")
        else:
            messagebox.showerror(app_instance._t('error_title'), "Помилка очищення зображень!")


def refresh_user_stats(app_instance):
    """Оновлює статистику поточного користувача та відображення User ID."""
    if not hasattr(app_instance, 'firebase_api') or not app_instance.firebase_api or not app_instance.firebase_api.is_initialized:
        if hasattr(app_instance, 'user_stats_label'):
            app_instance.user_stats_label.config(text="Firebase не підключено")
        if hasattr(app_instance, 'current_user_id_label'):
            app_instance.current_user_id_label.config(text="Firebase не підключено")
        return
        
    user_id = app_instance.firebase_api.get_current_user_id()
    if not user_id:
        if hasattr(app_instance, 'user_stats_label'):
            app_instance.user_stats_label.config(text="User ID не ініціалізовано")
        if hasattr(app_instance, 'current_user_id_label'):
            app_instance.current_user_id_label.config(text="Не ініціалізовано")
        return
        
    # Оновлюємо відображення User ID
    if hasattr(app_instance, 'current_user_id_label'):
        app_instance.current_user_id_label.config(text=user_id)
        
    # Оновлюємо статистику
    stats = app_instance.firebase_api.get_user_stats()
    if stats and hasattr(app_instance, 'user_stats_label'):
        stats_text = f"Користувач: {user_id} | Логи: {stats['logs']} | Зображення: {stats['images']}"
        app_instance.user_stats_label.config(text=stats_text)
    elif hasattr(app_instance, 'user_stats_label'):
        app_instance.user_stats_label.config(text=f"Користувач: {user_id} | Помилка завантаження статистики")


def refresh_firebase_stats(app_instance):
    """Оновлює статистику Firebase."""
    if not hasattr(app_instance, 'firebase_api') or not app_instance.firebase_api or not app_instance.firebase_api.is_initialized:
        if hasattr(app_instance, 'firebase_logs_stat_var'):
            app_instance.firebase_logs_stat_var.set("Firebase not connected")
        if hasattr(app_instance, 'firebase_images_stat_var'):
            app_instance.firebase_images_stat_var.set("Firebase not connected")
        return
        
    try:
        stats = app_instance.firebase_api.get_user_stats()
        if stats:
            if hasattr(app_instance, 'firebase_logs_stat_var'):
                app_instance.firebase_logs_stat_var.set(str(stats['logs']))
            if hasattr(app_instance, 'firebase_images_stat_var'):
                app_instance.firebase_images_stat_var.set(str(stats['images']))
            if hasattr(app_instance, 'firebase_user_id_var'):
                app_instance.firebase_user_id_var.set(app_instance.firebase_api.get_current_user_id() or "Not available")
        else:
            if hasattr(app_instance, 'firebase_logs_stat_var'):
                app_instance.firebase_logs_stat_var.set("Error loading")
            if hasattr(app_instance, 'firebase_images_stat_var'):
                app_instance.firebase_images_stat_var.set("Error loading")
    except Exception as e:
        print(f"Error refreshing Firebase stats: {e}")
        if hasattr(app_instance, 'firebase_logs_stat_var'):
            app_instance.firebase_logs_stat_var.set("Error")
        if hasattr(app_instance, 'firebase_images_stat_var'):
            app_instance.firebase_images_stat_var.set("Error")


def clear_firebase_logs(app_instance):
    """Очищає логи Firebase."""
    if not hasattr(app_instance, 'firebase_api') or not app_instance.firebase_api or not app_instance.firebase_api.is_initialized:
        messagebox.showerror("Error", "Firebase not connected!")
        return
        
    if messagebox.askyesno("Confirm", "Clear all your logs from Firebase?\n\nThis action cannot be undone!"):
        success = app_instance.firebase_api.clear_user_logs()
        if success:
            refresh_firebase_stats(app_instance)
            messagebox.showinfo("Success", "Your logs have been cleared!")
        else:
            messagebox.showerror("Error", "Failed to clear logs!")


def clear_firebase_images(app_instance):
    """Очищає зображення Firebase."""
    if not hasattr(app_instance, 'firebase_api') or not app_instance.firebase_api or not app_instance.firebase_api.is_initialized:
        messagebox.showerror("Error", "Firebase not connected!")
        return
        
    if messagebox.askyesno("Confirm", "Clear all your images from Firebase?\n\nThis action cannot be undone!"):
        success = app_instance.firebase_api.clear_user_images()
        if success:
            refresh_firebase_stats(app_instance)
            messagebox.showinfo("Success", "Your images have been cleared!")
        else:
            messagebox.showerror("Error", "Failed to clear images!")
