import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, Menu, messagebox
import os
import sys
from datetime import datetime

# Data / DB layer
from DB import (
    init_db,
    DBError,
    NotFoundError,
    AlreadyExistsError,
    create_student,
    update_student,
    delete_student,
    restore_student_snapshot,
    get_student,
    get_student_groups,
    set_student_groups,
    get_all_groups,
    get_students_with_payment_for_month,
    get_payment,
    upsert_payment,
)

import menu_tools
import payments_log


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for dev and for PyInstaller.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


# ---------------------------------------------------------------------------
# Global style / constants
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

BACKGROUND = "#F4F7FA"
PRIMARY    = "#3B82F6"  # blue-500
SECONDARY  = "#60A5FA"  # blue-400
TEXT       = "#1F2937"  # gray-800
HOVER      = "#DAD9E9"

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# Global state for undo
_last_deleted_snapshot = None
_last_deleted_id = None


# ---------------------------------------------------------------------------
# Main window setup
# ---------------------------------------------------------------------------

init_db()  # ensure DB schema exists

ElNajahSchool = ctk.CTk()
ElNajahSchool.title("El Najah School Manager")

# Try to set icon if you have one (optional)
try:
    icon_path = resource_path("school.ico")
    if os.path.exists(icon_path):
        ElNajahSchool.iconbitmap(icon_path)
except Exception:
    pass

# Geometry
screen_width = ElNajahSchool.winfo_screenwidth()
screen_height = ElNajahSchool.winfo_screenheight()
ElNajahSchool.geometry(f"{screen_width}x{screen_height}+0+0")

ElNajahSchool.configure(fg_color=BACKGROUND)

# ---------------------------------------------------------------------------
# Top filters: year, month, group, search
# ---------------------------------------------------------------------------

top_frame = ctk.CTkFrame(ElNajahSchool, fg_color="transparent")
top_frame.pack(side="top", fill="x", padx=16, pady=(10, 4))

# Year selector
_now = datetime.now()
years = [str(y) for y in range(_now.year - 2, _now.year + 3)]
year_var = ctk.StringVar(value=str(_now.year))

year_label = ctk.CTkLabel(top_frame, text="Year:", font=("Arial", 14), text_color=TEXT)
year_label.grid(row=0, column=0, padx=(4, 4), pady=4, sticky="w")
year_menu = ctk.CTkOptionMenu(top_frame, variable=year_var, values=years, width=90)
year_menu.grid(row=0, column=1, padx=(0, 10), pady=4, sticky="w")

# Month selector
month_var = ctk.StringVar(value=MONTHS[_now.month - 1])
month_label = ctk.CTkLabel(top_frame, text="Month:", font=("Arial", 14), text_color=TEXT)
month_label.grid(row=0, column=2, padx=(4, 4), pady=4, sticky="w")
month_menu = ctk.CTkOptionMenu(top_frame, variable=month_var, values=MONTHS, width=130)
month_menu.grid(row=0, column=3, padx=(0, 10), pady=4, sticky="w")

# Group filter
group_filter_var = ctk.StringVar(value="All")
group_label = ctk.CTkLabel(top_frame, text="Group:", font=("Arial", 14), text_color=TEXT)
group_label.grid(row=0, column=4, padx=(4, 4), pady=4, sticky="w")
group_menu = ctk.CTkOptionMenu(top_frame, variable=group_filter_var, values=["All"], width=140)
group_menu.grid(row=0, column=5, padx=(0, 10), pady=4, sticky="w")

# Search controls
search_var = ctk.StringVar()
search_type_var = ctk.StringVar(value="name")

search_label = ctk.CTkLabel(top_frame, text="Search:", font=("Arial", 14), text_color=TEXT)
search_label.grid(row=0, column=6, padx=(4, 4), pady=4, sticky="e")

search_entry = ctk.CTkEntry(top_frame, textvariable=search_var)
search_entry.grid(row=0, column=7, padx=(0, 4), pady=4, sticky="ew")

search_button = ctk.CTkButton(
    top_frame,
    text="Search",
    command=lambda: on_search_pressed(),  # use same logic as Enter key
    fg_color=PRIMARY,
    hover_color=HOVER,
    text_color="white",
    width=80,
)
search_button.grid(row=0, column=9, padx=(0, 10), pady=4, sticky="w")

search_radio_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
search_radio_frame.grid(row=0, column=8, padx=(0, 10), pady=4, sticky="w")

search_id_radio = ctk.CTkRadioButton(
    search_radio_frame, text="ID", variable=search_type_var, value="id"
)
search_name_radio = ctk.CTkRadioButton(
    search_radio_frame, text="Name", variable=search_type_var, value="name"
)
search_name_radio.grid(row=0, column=0, padx=2)
search_id_radio.grid(row=0, column=1, padx=2)

top_frame.grid_columnconfigure(7, weight=1)  # let search entry stretch


# ---------------------------------------------------------------------------
# Treeview of students
# ---------------------------------------------------------------------------

middle_frame = ctk.CTkFrame(ElNajahSchool, fg_color="white")
middle_frame.pack(side="top", fill="both", expand=True, padx=16, pady=(0, 8))

columns = ("id", "name", "groups", "join_date", "payment")
tree = ttk.Treeview(
    middle_frame,
    columns=columns,
    show="headings",
    height=20,
)

tree.heading("id", text="ID")
tree.heading("name", text="Name")
tree.heading("groups", text="Groups")
tree.heading("join_date", text="Join Date")
tree.heading("payment", text="Payment (selected month)")

tree.column("id", width=60, anchor="center")
tree.column("name", width=200, anchor="w")
tree.column("groups", width=220, anchor="w")
tree.column("join_date", width=100, anchor="center")
tree.column("payment", width=180, anchor="w")

tree_scroll_y = ttk.Scrollbar(middle_frame, orient="vertical", command=tree.yview)
tree_scroll_x = ttk.Scrollbar(middle_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

tree.grid(row=0, column=0, sticky="nsew")
tree_scroll_y.grid(row=0, column=1, sticky="ns")
tree_scroll_x.grid(row=1, column=0, sticky="ew")

middle_frame.grid_rowconfigure(0, weight=1)
middle_frame.grid_columnconfigure(0, weight=1)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def refresh_group_filter():
    """
    Reload the list of groups for the filter dropdown.
    """
    groups = get_all_groups()
    values = ["All"] + groups
    current = group_filter_var.get()
    if current not in values:
        group_filter_var.set("All")
    group_menu.configure(values=values)


def _current_year_month():
    try:
        year = int(year_var.get())
    except ValueError:
        year = _now.year
        year_var.set(str(year))

    try:
        month_index = MONTHS.index(month_var.get())
    except ValueError:
        month_index = _now.month - 1
        month_var.set(MONTHS[month_index])

    return year, month_index + 1  # month as 1..12


def refresh_treeview_all():
    """
    Re-populate the main tree using filters + search.
    """
    for item in tree.get_children():
        tree.delete(item)

    year, month = _current_year_month()
    search_text = search_var.get().strip()
    search_type = search_type_var.get()

    try:
        rows = get_students_with_payment_for_month(
            year=year,
            month=month,
            search_text=search_text,
            search_type=search_type,
        )
    except Exception as e:
        messagebox.showerror("DB Error", f"Could not load students:\n{e}")
        return

    filter_group = group_filter_var.get()
    for row in rows:
        # Filter by group if not "All"
        groups = [g.strip() for g in (row.get("groups") or "").split(",") if g.strip()]
        if filter_group != "All" and filter_group not in groups:
            continue

        tree.insert(
            "",
            "end",
            values=(
                row["id"],
                row["name"],
                row.get("groups", ""),
                row.get("join_date", ""),
                row.get("monthly_payment", ""),
            ),
        )


def on_search_pressed(event=None):
    refresh_treeview_all()


def _get_selected_student_id():
    sel = tree.selection()
    if not sel:
        return None
    item_id = sel[0]
    values = tree.item(item_id, "values")
    if not values:
        return None
    try:
        return int(values[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Add / edit / delete student
# ---------------------------------------------------------------------------

def open_add_student():
    """
    Popup window to create a new student.
    """
    top = ctk.CTkToplevel(ElNajahSchool)
    top.title("New Student")
    top.geometry("470x570")

    try:
        top.grab_set()
    except tk.TclError:
        top.focus_force()

    top.focus_force()

    ctk.CTkLabel(top, text="Add New Student", font=("Arial", 24, "bold")).pack(pady=(16, 10))

    form = ctk.CTkFrame(top, fg_color="transparent")
    form.pack(fill="both", expand=True, padx=16, pady=10)

    form.grid_columnconfigure(0, weight=1)

    # ID (optional manual)
    ctk.CTkLabel(form, text="Student ID (optional):", anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 2))
    id_entry = ctk.CTkEntry(form)
    id_entry.grid(row=1, column=0, sticky="ew", pady=(0, 8))

    # Name
    ctk.CTkLabel(form, text="Full Name:", anchor="w").grid(row=2, column=0, sticky="w", pady=(0, 2))
    name_entry = ctk.CTkEntry(form)
    name_entry.grid(row=3, column=0, sticky="ew", pady=(0, 8))

    # Payment status for current filter month
    pay_frame = ctk.CTkFrame(form, fg_color="transparent")
    pay_frame.grid(row=4, column=0, sticky="n", pady=(4, 8))
    ctk.CTkLabel(pay_frame, text="Payment for selected month:", anchor="n").grid(row=0, column=0, columnspan=2, sticky="n")

    pay_var = ctk.StringVar(value="paid")
    ctk.CTkRadioButton(pay_frame, text="Paid", variable=pay_var, value="paid").grid(row=1, column=0, padx=(0, 6))
    ctk.CTkRadioButton(pay_frame, text="Unpaid", variable=pay_var, value="unpaid").grid(row=1, column=1, padx=(0, 6))

    # Group selection
    group_frame = ctk.CTkFrame(form, fg_color="transparent")
    group_frame.grid(row=5, column=0, sticky="nsew", pady=(4, 8))
    group_frame.grid_rowconfigure(1, weight=1)

    ctk.CTkLabel(group_frame, text="Assign Groups:", anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 4))

    scroll = ctk.CTkScrollableFrame(group_frame, width=420, height=180, fg_color="white")
    scroll.grid(row=1, column=0, sticky="nsew")

    group_vars: dict[str, ctk.BooleanVar] = {}

    def reload_groups_in_add():
        for w in scroll.winfo_children():
            w.destroy()
        for name in get_all_groups():
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(scroll, text=name, variable=var)
            cb.pack(anchor="w", padx=6, pady=2)
            group_vars[name] = var

    reload_groups_in_add()

    # Buttons
    btn_frame = ctk.CTkFrame(top, fg_color="transparent")
    btn_frame.pack(pady=(0, 16), anchor="center") 

    def handle_save():
        name = name_entry.get().strip()
        if not name:
            messagebox.showerror("Invalid Name", "Student name is required.")
            return

        id_text = id_entry.get().strip()
        manual_id = None
        if id_text:
            if not id_text.isdigit():
                messagebox.showerror("Invalid ID", "Student ID must be a number.")
                return
            manual_id = int(id_text)

        selected_groups = [g for g, var in group_vars.items() if var.get()]
        year, month = _current_year_month()
        pay_status = pay_var.get() or "unpaid"

        try:
            sid = create_student(name=name, student_id=manual_id)
            set_student_groups(sid, selected_groups)
            upsert_payment(sid, year=year, month=month, paid=pay_status)
        except AlreadyExistsError as e:
            messagebox.showerror("Duplicate ID", str(e))
            return
        except DBError as e:
            messagebox.showerror("Database Error", str(e))
            return

        messagebox.showinfo("Student Added", f"Student '{name}' added with ID {sid}.")
        top.destroy()
        refresh_group_filter()
        refresh_treeview_all()

    save_btn = ctk.CTkButton(btn_frame, text="Save", command=handle_save,
                            fg_color=PRIMARY, hover_color=HOVER)
    save_btn.pack(side="left", padx=4)

    cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", command=top.destroy)
    cancel_btn.pack(side="left", padx=4)


def open_add_group():
    """
    Popup to create a new group.
    """
    top = ctk.CTkToplevel(ElNajahSchool)
    top.title("Add Group")
    top.geometry("360x160")
    try:
        top.grab_set()
    except tk.TclError:
        top.focus_force()

    top.focus_force()

    ctk.CTkLabel(top, text="New Group Name:", font=("Arial", 16)).pack(pady=(16, 8))
    entry = ctk.CTkEntry(top)
    entry.pack(padx=16, pady=(0, 12), fill="x")

    btn_frame = ctk.CTkFrame(top, fg_color="transparent")
    btn_frame.pack(pady=4)

    def handle_add_group():
        from DB import create_group, delete_group_by_name  # local import to avoid circulars

        name = entry.get().strip()
        if not name:
            messagebox.showerror("Error", "Group name cannot be empty.")
            return

        try:
            create_group(name)
        except AlreadyExistsError as e:
            messagebox.showerror("Error", str(e))
            return

        messagebox.showinfo("Added", f"Group '{name}' created.")
        top.destroy()
        refresh_group_filter()
        refresh_treeview_all()

    ctk.CTkButton(btn_frame, text="Add", command=handle_add_group, fg_color=PRIMARY, hover_color=HOVER).pack(side="left", padx=4)
    ctk.CTkButton(btn_frame, text="Cancel", command=top.destroy).pack(side="left", padx=4)


def open_delete_group():
    """
    Popup to delete an existing group by name.
    """
    from DB import delete_group_by_name

    top = ctk.CTkToplevel(ElNajahSchool)
    top.title("Delete Group")
    top.geometry("360x180")
    try:
        top.grab_set()
    except tk.TclError:
        top.focus_force()

    top.focus_force()

    ctk.CTkLabel(top, text="Delete Group", font=("Arial", 16, "bold")).pack(pady=(12, 4))
    ctk.CTkLabel(top, text="Enter group name to delete:", font=("Arial", 12)).pack()

    entry = ctk.CTkEntry(top)
    entry.pack(padx=16, pady=8, fill="x")

    def handle_delete():
        name = entry.get().strip()
        if not name:
            messagebox.showerror("Error", "Group name is required.")
            return

        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete group '{name}'?\nThis will unlink it from all students."
        ):
            return

        ok = delete_group_by_name(name)
        if not ok:
            messagebox.showinfo("Not Found", f"Group '{name}' does not exist.")
        else:
            messagebox.showinfo("Deleted", f"Group '{name}' deleted.")
            refresh_group_filter()
            refresh_treeview_all()
        top.destroy()

    btn_frame = ctk.CTkFrame(top, fg_color="transparent")
    btn_frame.pack(pady=8)
    ctk.CTkButton(btn_frame, text="Delete", command=handle_delete, fg_color="#DC2626").pack(side="left", padx=4)
    ctk.CTkButton(btn_frame, text="Cancel", command=top.destroy).pack(side="left", padx=4)


def open_edit_student_modal():
    """
    Edit the selected student's name, groups, and payment status for the current month.
    """
    sid = _get_selected_student_id()
    if sid is None:
        messagebox.showerror("No selection", "Please select a student first.")
        return

    try:
        student = get_student(sid)
        current_groups = set(get_student_groups(sid))
    except NotFoundError:
        messagebox.showerror("Not found", f"Student {sid} not found.")
        return
    except DBError as e:
        messagebox.showerror("DB Error", str(e))
        return

    year, month = _current_year_month()
    existing_payment = get_payment(sid, year, month)
    current_paid = existing_payment.paid if existing_payment else "unpaid"

    top = ctk.CTkToplevel(ElNajahSchool)
    top.title(f"Edit Student {sid}")
    top.geometry("520x520")
    try:
        top.grab_set()
    except tk.TclError:
        top.focus_force()

    top.focus_force()

    ctk.CTkLabel(top, text=f"Edit Student {sid}", font=("Arial", 20, "bold")).pack(pady=(12, 4))
    ctk.CTkLabel(top, text=f"Joined: {student.join_date}", font=("Arial", 12)).pack()

    form = ctk.CTkFrame(top, fg_color="transparent")
    form.pack(fill="both", expand=True, padx=16, pady=8)
    form.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(form, text="Name:", anchor="w").grid(row=0, column=0, sticky="w")
    name_entry = ctk.CTkEntry(form)
    name_entry.insert(0, student.name)
    name_entry.grid(row=1, column=0, sticky="ew", pady=(0, 8))

    # Payment status
    pay_frame = ctk.CTkFrame(form, fg_color="transparent")
    pay_frame.grid(row=2, column=0, sticky="w", pady=(4, 8))
    ctk.CTkLabel(pay_frame, text="Payment for selected month:", anchor="w").grid(row=0, column=0, columnspan=2, sticky="w")

    pay_var = ctk.StringVar(value=current_paid)
    ctk.CTkRadioButton(pay_frame, text="Paid", variable=pay_var, value="paid").grid(row=1, column=0, padx=(0, 6))
    ctk.CTkRadioButton(pay_frame, text="Unpaid", variable=pay_var, value="unpaid").grid(row=1, column=1, padx=(0, 6))

    # Groups
    group_frame = ctk.CTkFrame(form, fg_color="transparent")
    group_frame.grid(row=3, column=0, sticky="nsew", pady=(4, 8))
    group_frame.grid_rowconfigure(1, weight=1)

    ctk.CTkLabel(group_frame, text="Groups:", anchor="w").grid(row=0, column=0, sticky="w")

    scroll = ctk.CTkScrollableFrame(group_frame, width=420, height=200, fg_color="white")
    scroll.grid(row=1, column=0, sticky="nsew")

    group_vars: dict[str, ctk.BooleanVar] = {}
    for gname in get_all_groups():
        var = ctk.BooleanVar(value=(gname in current_groups))
        cb = ctk.CTkCheckBox(scroll, text=gname, variable=var)
        cb.pack(anchor="w", padx=6, pady=2)
        group_vars[gname] = var

    btn_frame = ctk.CTkFrame(top, fg_color="transparent")
    btn_frame.pack(pady=(0, 12))

    def handle_save():
        name = name_entry.get().strip()
        if not name:
            messagebox.showerror("Invalid Name", "Student name cannot be empty.")
            return

        try:
            update_student(sid, name=name)
            chosen_groups = [g for g, v in group_vars.items() if v.get()]
            set_student_groups(sid, chosen_groups)
            upsert_payment(sid, year=year, month=month, paid=pay_var.get())
        except DBError as e:
            messagebox.showerror("DB Error", str(e))
            return

        messagebox.showinfo("Updated", "Student updated successfully.")
        top.destroy()
        refresh_treeview_all()

    ctk.CTkButton(btn_frame, text="Save", command=handle_save, fg_color=PRIMARY, hover_color=HOVER).pack(side="left", padx=4)
    ctk.CTkButton(btn_frame, text="Cancel", command=top.destroy).pack(side="left", padx=4)


def perform_delete():
    """
    Delete selected student (with undo support).
    """
    global _last_deleted_snapshot, _last_deleted_id

    sid = _get_selected_student_id()
    if sid is None:
        messagebox.showerror("No selection", "Please select a student to delete.")
        return

    if not messagebox.askyesno("Confirm Delete", f"Delete student {sid}? This can be undone until next delete."):
        return

    try:
        snapshot = delete_student(sid, snapshot_for_undo=True)
    except NotFoundError:
        messagebox.showerror("Not found", f"Student {sid} not found.")
        return
    except DBError as e:
        messagebox.showerror("DB Error", str(e))
        return

    _last_deleted_snapshot = snapshot
    _last_deleted_id = sid
    messagebox.showinfo("Deleted", f"Student {sid} deleted.\nYou can undo this from the 'Undo Delete' button.")
    refresh_treeview_all()


def undo_delete():
    """
    Undo the last delete if possible.
    """
    global _last_deleted_snapshot, _last_deleted_id

    if not _last_deleted_snapshot:
        messagebox.showinfo("Nothing to undo", "There is no recent delete to undo.")
        return

    try:
        restore_student_snapshot(_last_deleted_snapshot)
    except AlreadyExistsError as e:
        messagebox.showerror("Cannot restore", str(e))
        return
    except DBError as e:
        messagebox.showerror("DB Error", str(e))
        return

    sid = _last_deleted_id
    _last_deleted_snapshot = None
    _last_deleted_id = None
    messagebox.showinfo("Restored", f"Student {sid} has been restored.")
    refresh_treeview_all()


# ---------------------------------------------------------------------------
# Bottom buttons
# ---------------------------------------------------------------------------

bottom_frame = ctk.CTkFrame(ElNajahSchool, fg_color="transparent")
bottom_frame.pack(side="bottom", fill="x", padx=16, pady=(4, 10))

ctk.CTkButton(
    bottom_frame,
    text="Add Student",
    command=open_add_student,
    fg_color=PRIMARY,
    hover_color=HOVER,
    text_color="white",
    font=("Arial", 16),
).pack(side="left", padx=4)

ctk.CTkButton(
    bottom_frame,
    text="Add Group",
    command=open_add_group,
    fg_color=SECONDARY,
    hover_color=HOVER,
    text_color="white",
    font=("Arial", 16),
).pack(side="left", padx=4)

ctk.CTkButton(
    bottom_frame,
    text="Delete Group",
    command=open_delete_group,
    fg_color=SECONDARY,
    hover_color=HOVER,
    text_color="white",
    font=("Arial", 16),
).pack(side="left", padx=4)

ctk.CTkButton(
    bottom_frame,
    text="Edit Student",
    command=open_edit_student_modal,
    fg_color=PRIMARY,
    hover_color=HOVER,
    text_color="white",
    font=("Arial", 16),
).pack(side="left", padx=4)

ctk.CTkButton(
    bottom_frame,
    text="Delete Student",
    command=perform_delete,
    fg_color="#DC2626",
    hover_color="#B91C1C",
    text_color="white",
    font=("Arial", 16),
).pack(side="left", padx=4)

ctk.CTkButton(
    bottom_frame,
    text="Undo Delete",
    command=undo_delete,
    fg_color="#F59E0B",
    hover_color="#D97706",
    text_color="white",
    font=("Arial", 16),
).pack(side="left", padx=4)


def open_history():
    # paymants_log currently expects a global ElNajahSchool. We also pass DB helpers through globals.
    try:
        payments_log.open_full_window()
    except AttributeError:
        # in the future you may switch to paymants_log.open_history_window(ElNajahSchool)
        try:
            payments_log.open_history_window(ElNajahSchool)
        except Exception as e:
            messagebox.showerror("History Error", str(e))


ctk.CTkButton(
    bottom_frame,
    text="Payments History Logs",
    command=open_history,
    fg_color=PRIMARY,
    hover_color=HOVER,
    text_color="white",
    font=("Arial", 16),
).pack(side="left", padx=4)

ctk.CTkButton(
    bottom_frame,
    text="Exit",
    command=ElNajahSchool.destroy,
    fg_color="#6B7280",
    hover_color="#4B5563",
    text_color="white",
    font=("Arial", 16),
).pack(side="right", padx=4)


# ---------------------------------------------------------------------------
# Menu bar (Tools / Backup / Export / Help)
# ---------------------------------------------------------------------------

menubar = Menu(ElNajahSchool)
ElNajahSchool.config(menu=menubar)

# Tools menu
tools_menu = Menu(menubar, tearoff=0)
tools_menu.add_command(label="Delete Groupless Students", command=menu_tools.delete_groupless_students)
tools_menu.add_command(label="Merge Duplicate Students", command=menu_tools.merge_duplicate_students)
tools_menu.add_command(label="Bulk Remove Group if Only Group", command=menu_tools.bulk_remove_group_if_only_group)
menubar.add_cascade(label="Tools", menu=tools_menu)

# Backup menu
backup_menu = Menu(menubar, tearoff=0)
backup_menu.add_command(label="Backup Database", command=menu_tools.backup_database)
backup_menu.add_command(label="Restore Database", command=menu_tools.restore_backup)
backup_menu.add_command(label="Purge Old Backups", command=menu_tools.purge_old_backups)
menubar.add_cascade(label="Backup", menu=backup_menu)

# Export menu
export_menu = Menu(menubar, tearoff=0)
export_menu.add_command(label="Export Group to PDF", command=menu_tools.open_group_selector_and_export)
export_menu.add_command(label="Export All Students to Excel", command=menu_tools.export_all_students_excel)
export_menu.add_command(label="Export Unpaid Students to PDF", command=menu_tools.export_unpaid_students_pdf)
export_menu.add_command(label="Export Student Count to PDF", command=menu_tools.export_student_count_pdf)
export_menu.add_command(label="Export Student Payment History to PDF", command=menu_tools.export_student_payment_history_pdf)
menubar.add_cascade(label="Export", menu=export_menu)

# Help menu
help_menu = Menu(menubar, tearoff=0)
help_menu.add_command(label="Contact Support", command=menu_tools.contact_support)
help_menu.add_command(label="Send Feedback", command=menu_tools.send_feedback)
menubar.add_cascade(label="Help", menu=help_menu)


# ---------------------------------------------------------------------------
# Wire globals into helper modules so old code keeps working
# ---------------------------------------------------------------------------

# Many functions inside menu_tools/paymants_log expect these to exist as globals
menu_tools.ElNajahSchool = ElNajahSchool
menu_tools.refresh_treeview_all = refresh_treeview_all
menu_tools.get_all_groups = get_all_groups

payments_log.ElNajahSchool = ElNajahSchool
payments_log.get_all_groups = get_all_groups

# Bindings
search_entry.bind("<Return>", on_search_pressed)
year_menu.configure(command=lambda _value: refresh_treeview_all())
month_menu.configure(command=lambda _value: refresh_treeview_all())
group_menu.configure(command=lambda _value: refresh_treeview_all())

# Initial load
refresh_group_filter()
refresh_treeview_all()

if __name__ == "__main__":
    ElNajahSchool.mainloop()