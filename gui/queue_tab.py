# gui/queue_tab.py
import tkinter as tk
import ttkbootstrap as ttk
from .gui_utils import create_scrollable_tab

def create_queue_tab(notebook, app):
    """
    Створює спільну вкладку "Черга завдань" та всі її елементи.
    """
    # Тепер ця функція лише заповнює вже існуючий app.queue_frame
    app.queue_canvas, app.queue_scrollable_frame = create_scrollable_tab(app, app.queue_frame)

    buttons_frame = ttk.Frame(app.queue_scrollable_frame)
    buttons_frame.pack(fill='x', padx=10, pady=5)

    ttk.Button(buttons_frame, text=app._t('process_queue_button'), command=app.process_queue, bootstyle="success").pack(side='left', padx=5)

    app.pause_resume_button = ttk.Button(buttons_frame, text=app._t('pause_button'), command=app.toggle_pause_resume, bootstyle="warning", state="disabled")
    app.pause_resume_button.pack(side='left', padx=5)

    ttk.Button(buttons_frame, text=app._t('clear_queue_button'), command=app.clear_queue, bootstyle="danger").pack(side='left', padx=5)

    progress_container = ttk.Frame(app.queue_scrollable_frame)
    progress_container.pack(fill='x', padx=10, pady=5)

    app.progress_label_var = tk.StringVar(value="0%")
    ttk.Label(progress_container, textvariable=app.progress_label_var, font=("Helvetica", 10, "bold"), width=5).pack(side='left')

    app.progress_var = tk.DoubleVar()
    app.progress_bar = ttk.Progressbar(progress_container, variable=app.progress_var, maximum=100, bootstyle="success-striped")
    app.progress_bar.pack(fill='x', expand=True, side='left', padx=(5, 0))

    # Frame for image generation control buttons
    image_control_frame = ttk.Frame(app.queue_scrollable_frame)
    image_control_frame.pack(fill='x', padx=10, pady=5)

    skip_image_button = ttk.Button(
        image_control_frame,
        text=app._t('skip_image_button'),
        command=app._on_skip_image_click,
        bootstyle="warning",
        state="disabled"
    )
    skip_image_button.pack(side='left', padx=5)
    app.skip_image_buttons.append(skip_image_button)

    switch_service_button = ttk.Button(
        image_control_frame,
        text=app._t('switch_service_button'),
        command=app._on_switch_service_click,
        bootstyle="info",
        state="disabled"
    )
    switch_service_button.pack(side='left', padx=5)
    app.switch_service_buttons.append(switch_service_button)

    regenerate_alt_button = ttk.Button(
        image_control_frame,
        text=app._t('regenerate_alt_button'),
        command=app._on_regenerate_alt_click,
        bootstyle="success",
        state="disabled"
    )
    regenerate_alt_button.pack(side='left', padx=5)
    app.regenerate_alt_buttons.append(regenerate_alt_button)

    queue_main_frame = ttk.Labelframe(app.queue_scrollable_frame, text=app._t('task_queue_label'))
    queue_main_frame.pack(fill='both', expand=True, padx=10, pady=10)

    queue_list_frame = ttk.Frame(queue_main_frame)
    queue_list_frame.pack(fill='both', expand=True, padx=10, pady=5)

    columns = ("type", "status", "time")
    app.queue_tree = ttk.Treeview(queue_list_frame, columns=columns, show='tree headings', bootstyle="dark")

    saved_height = app.config.get("ui_settings", {}).get("queue_height", 15)
    app.queue_tree.configure(height=saved_height)

    style = ttk.Style()
    style.configure("Treeview.Heading", relief="groove", borderwidth=1, padding=(5,5))

    saved_widths = app.config.get("ui_settings", {}).get("queue_column_widths", {})

    app.queue_tree.heading("#0", text=app._t('task_details_column'))
    app.queue_tree.column("#0", width=saved_widths.get('task_details', 400), anchor='w')

    app.queue_tree.heading('type', text=app._t('task_type_column'))
    app.queue_tree.column('type', width=saved_widths.get('type', 100), anchor='w')

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