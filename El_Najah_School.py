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
    get_student_counts_by_group,
    get_payment,
    upsert_payment,
)

import menu_tools
import payments_log
import schedule


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
schedule.init_attendance_tables()

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
    refresh_all()


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
        refresh_all()

    save_btn = ctk.CTkButton(btn_frame, text="Save", command=handle_save,
                            fg_color=PRIMARY, hover_color=HOVER)
    save_btn.pack(side="left", padx=4)

    cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", command=top.destroy)
    cancel_btn.pack(side="left", padx=4)


def open_add_group(parent=None):
    top = ctk.CTkToplevel(parent or ElNajahSchool)
    top.title("Add Group")
    top.geometry("565x620")  

    try:
        top.grab_set()
    except tk.TclError:
        top.focus_force()
    top.focus_force()

    # --- Main container (use pack consistently)
    container = ctk.CTkFrame(top, fg_color="transparent")
    container.pack(fill="both", expand=True, padx=16, pady=16)

    ctk.CTkLabel(container, text="New Group Name:", font=("Arial", 16)).pack(anchor="w", pady=(0, 8))
    entry = ctk.CTkEntry(container)
    entry.pack(fill="x", pady=(0, 12))

    ext_zone = ctk.CTkFrame(container, fg_color="transparent")
    ext_zone.pack(fill="x", pady=(8, 12))

    # Mount schedule plugin UI inside ext_zone
    # (Make sure you have: import schedule at the top of the file)
    schedule_validate, schedule_apply = schedule.attach_group_schedule_extension(ext_zone)

    # Buttons
    btn_frame = ctk.CTkFrame(container, fg_color="transparent")
    btn_frame.pack(fill="x", pady=(8, 0))

    def handle_add_group():
        from DB import create_group
        name = entry.get().strip()
        if not name:
            messagebox.showerror("Error", "Group name cannot be empty.")
            return

        # Plugin validate
        if schedule_validate and not schedule_validate():
            return

        try:
            group_id = create_group(name)   # <-- IMPORTANT: capture returned group id
        except AlreadyExistsError as e:
            messagebox.showerror("Error", str(e))
            return

        # Plugin apply -> payload or None
        schedule_payload = schedule_apply() if schedule_apply else None

        # Save schedule + generate sessions
        try:
            schedule.save_group_schedule_and_regenerate(group_id, schedule_payload)
        except Exception as e:
            from DB import delete_group  
            try:
                delete_group(group_id)
            except Exception:
                pass
            messagebox.showerror("Schedule Error", f"Schedule save failed:\n{e}\n(Group creation was rolled back.)")
            return


        messagebox.showinfo("Added", f"Group '{name}' created.")
        top.destroy()
        refresh_all()

    ctk.CTkButton(btn_frame, text="Add", command=handle_add_group, fg_color=PRIMARY, hover_color=HOVER).pack(side="left", padx=4)
    ctk.CTkButton(btn_frame, text="Cancel", command=top.destroy).pack(side="left", padx=4)

    return top

def open_delete_group(parent=None, preset_group_name: str | None = None, skip_popup: bool = False):
    # If caller already has the group name, skip the entry popup entirely.
    if skip_popup and preset_group_name:
        return delete_group_flow(preset_group_name, parent=parent)

    top = ctk.CTkToplevel(parent or ElNajahSchool)
    top.title("Delete Group")
    top.geometry("360x180")
    try:
        top.grab_set()
    except tk.TclError:
        top.focus_force()
    top.focus_force()

    ctk.CTkLabel(top, text="Group Name to Delete:", font=("Arial", 16)).pack(pady=(16, 8))
    entry = ctk.CTkEntry(top)
    entry.pack(padx=16, pady=(0, 12), fill="x")

    if preset_group_name:
        entry.insert(0, preset_group_name)

    btn = ctk.CTkFrame(top, fg_color="transparent")
    btn.pack(pady=6)

    def handle():
        ok = delete_group_flow(entry.get(), parent=top)
        if ok:
            top.destroy()
            if refresh_all:
                refresh_all()

    ctk.CTkButton(btn, text="Delete", command=handle, fg_color="#EF4444").pack(side="left", padx=4)
    ctk.CTkButton(btn, text="Cancel", command=top.destroy).pack(side="left", padx=4)
    return top

def delete_group_flow(group_name: str, parent=None):
    group_name = (group_name or "").strip()
    if not group_name:
        messagebox.showerror("Error", "No group selected.", parent=parent)
        return False

    if not messagebox.askyesno(
        "Confirm Delete",
        f"Delete group '{group_name}'?\n\nThis will remove the group and its links.",
        parent=parent
    ):
        return False

    try:
        from DB import delete_group_by_name
        deleted = delete_group_by_name(group_name)
    except Exception as e:
        messagebox.showerror("DB Error", str(e), parent=parent)
        return False

    if not deleted:
        messagebox.showinfo("Not Found", f"Group '{group_name}' was not found.", parent=parent)
        return False

    messagebox.showinfo("Deleted", f"Group '{group_name}' deleted.", parent=parent)
    return True

def open_manage_groups():
    win = ctk.CTkToplevel(ElNajahSchool)
    win.title("Manage Groups")
    win.geometry("760x480")

    try:
        win.grab_set()
    except tk.TclError:
        win.focus_force()
    win.focus_force()

    root = ctk.CTkFrame(win, fg_color="transparent")
    root.pack(fill="both", expand=True, padx=12, pady=12)

    # Left panel (buttons)
    left = ctk.CTkFrame(root, width=180, fg_color="white")
    left.pack(side="left", fill="y", padx=(0, 10))
    left.pack_propagate(False)

    ctk.CTkLabel(left, text="Groups", font=("Arial", 16, "bold")).pack(pady=(14, 10))

    # Right panel (tree)
    right = ctk.CTkFrame(root, fg_color="white")
    right.pack(side="left", fill="both", expand=True)

    groups_tree = ttk.Treeview(right, columns=("id", "group", "count"), show="headings")

    groups_tree.heading("id", text="ID")
    groups_tree.heading("group", text="Group")
    groups_tree.heading("count", text="Students")

    groups_tree.column("id", width=0, stretch=False)  # hidden
    groups_tree.column("group", width=320, anchor="w")
    groups_tree.column("count", width=90, anchor="center")

    yscroll = ttk.Scrollbar(right, orient="vertical", command=groups_tree.yview)
    groups_tree.configure(yscrollcommand=yscroll.set)

    groups_tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
    yscroll.pack(side="left", fill="y", pady=10, padx=(0, 10))

    def refresh_groups_tree():
        groups_tree.delete(*groups_tree.get_children())

        # Build {"GroupName": count}
        counts_map = {
            r["group"]: r["count"]
            for r in get_student_counts_by_group()
            if r.get("group") != "TOTAL"
        }

        for gid, gname in _get_groups_with_ids():
            groups_tree.insert("", "end", values=(gid, gname, counts_map.get(gname, 0)))

    def _get_groups_with_ids():
        import sqlite3
        from DB import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM groups ORDER BY name COLLATE NOCASE")
        rows = cur.fetchall()
        conn.close()
        return rows

    def selected_group():
        sel = groups_tree.selection()
        if not sel:
            return None, None
        vals = groups_tree.item(sel[0], "values")
        if not vals:
            return None, None
        try:
            return int(vals[0]), vals[1]
        except Exception:
            return None, None

    def on_add():
        child = open_add_group(parent=win)
        try:
            win.wait_window(child)
        except Exception:
            pass
        refresh_groups_tree()
        refresh_all()

    def on_delete():
        name = selected_group_name()
        if not name:
            messagebox.showerror("No selection", "Select a group to delete.")
            return

        deleted = open_delete_group(
            parent=win,
            preset_group_name=name,
            skip_popup=True
        )

        if deleted:
            refresh_groups_tree()
            refresh_all()


    ctk.CTkButton(left, text="Add Group", command=on_add, fg_color=PRIMARY, hover_color=HOVER).pack(
        fill="x", padx=10, pady=(0, 8)
    )
    ctk.CTkButton(left, text="Delete Group", command=on_delete, fg_color="#DC2626", hover_color="#B91C1C").pack(
        fill="x", padx=10, pady=(0, 8)
    )
    ctk.CTkButton(left, text="Close", command=win.destroy).pack(fill="x", padx=10, pady=(18, 0))

    refresh_groups_tree()

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
        refresh_all()

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
    refresh_all()


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
    refresh_all()


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
    text="Manage Groups",
    command=open_manage_groups,
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
    try:
        payments_log.open_full_window()
    except AttributeError:
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

def refresh_all():
    refresh_group_filter()
    refresh_treeview_all()

menu_tools.ElNajahSchool = ElNajahSchool
menu_tools.refresh_treeview_all = refresh_treeview_all
menu_tools.get_all_groups = get_all_groups
menu_tools.refresh_all = refresh_all

payments_log.ElNajahSchool = ElNajahSchool
payments_log.get_all_groups = get_all_groups
payments_log.refresh_all = refresh_all

# Bindings
search_entry.bind("<Return>", on_search_pressed)
year_menu.configure(command=lambda _value: refresh_all())
month_menu.configure(command=lambda _value: refresh_all())
group_menu.configure(command=lambda _value: refresh_all())

# Initial load
refresh_all()

if __name__ == "__main__":
    ElNajahSchool.mainloop()