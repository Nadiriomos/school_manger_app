"""
paymants_log.py

Payments History window and edit modal for El Najah School.

This module is responsible ONLY for:
    - Showing the full history window (opened by the "Payments History Logs" button)
    - Letting the user edit payments for a student across an academic year
    - Exporting the current history view to a PDF

All database access is done via DB.py.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox

from datetime import datetime, date
import os
import json

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from DB import (
    DBError,
    NotFoundError,
    get_student,
    get_student_groups,
    get_all_groups,
    get_all_students,
    get_group_students,
    get_payments_for_student_academic_year,
    upsert_payments_bulk,
)

# ---------------------------------------------------------------------------
# Globals injected from main (El Najah School)
# ---------------------------------------------------------------------------

# Main root window will be injected by the main file:
#     paymants_log.ElNajahSchool = ElNajahSchool
ElNajahSchool = None

# Month labels for academic year (Aug..Jul)
MONTH_COLS = [
    "Aug", "Sep", "Oct", "Nov", "Dec",
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"
]

# Preferences file to remember last selected academic year/group
PREFS_PATH = os.path.join(os.path.dirname(__file__), "payments_history_prefs.json")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def guess_current_academic_start_year() -> int:
    """
    Academic year is Aug..Jul.
    If month >= 8, academic year starts this year.
    Otherwise, it started last year.
    """
    now = datetime.now()
    if now.month >= 8:
        return now.year
    return now.year - 1


def make_academic_label(start_year: int) -> str:
    """Convert 2024 -> '2024-2025'."""
    return f"{start_year}-{start_year + 1}"


def parse_academic_label(label: str) -> int:
    """Extract start year from '2024-2025' as int."""
    try:
        start = label.split("-")[0].strip()
        return int(start)
    except Exception:
        return guess_current_academic_start_year()


def get_academic_year_labels() -> list[str]:
    """
    Return a list of academic year labels around the current one.
    e.g. ['2022-2023', '2023-2024', '2024-2025', '2025-2026', '2026-2027']
    """
    base = guess_current_academic_start_year()
    years = [base - 2, base - 1, base, base + 1, base + 2]
    return [make_academic_label(y) for y in years]


def months_for_academic_year(start_year: int) -> list[tuple[int, int, str]]:
    """
    For an academic year starting in 'start_year', return a list of:
        (year, month, label)
    in academic order: Aug..Dec (start_year), Jan..Jul (start_year+1).

    Label corresponds to entries in MONTH_COLS.
    """
    months: list[tuple[int, int, str]] = []
    for idx, label in enumerate(MONTH_COLS):
        if idx < 5:  # Aug..Dec
            y = start_year
            m = 8 + idx
        else:        # Jan..Jul
            y = start_year + 1
            m = idx - 4
        months.append((y, m, label))
    return months


# ---------------------------------------------------------------------------
# Preferences (last used academic year & group)
# ---------------------------------------------------------------------------

def load_prefs() -> dict:
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_prefs(academic_label: str, group_name: str) -> None:
    data = {
        "academic_label": academic_label,
        "group_name": group_name,
    }
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        # preferences are nice-to-have; ignore errors
        pass


# ---------------------------------------------------------------------------
# Data loader for history view
# ---------------------------------------------------------------------------

def load_history_rows(academic_start_year: int, group_name: str | None) -> list[dict]:
    """
    Load rows for the history table.

    Returns list of dicts:
        {
            "student": Student dataclass,
            "groups": "G1, G2, ...",
            "cells": [text_for_Aug, ..., text_for_Jul]
        }
    """
    if group_name and group_name != "All":
        students = get_group_students(group_name)
    else:
        students = get_all_students(order_by="name")

    months_spec = months_for_academic_year(academic_start_year)
    rows: list[dict] = []

    for stu in students:
        try:
            groups_list = get_student_groups(stu.id)
            groups_str = ", ".join(groups_list)
        except DBError:
            groups_str = ""

        payments = get_payments_for_student_academic_year(stu.id, academic_start_year)
        pay_map = {(p.year, p.month): p for p in payments}

        cells: list[str] = []
        for (py, pm, _label) in months_spec:
            p = pay_map.get((py, pm))
            if p:
                if p.paid == "paid":
                    cell_text = f"Paid"
                else:
                    cell_text = "Unpaid"
            else:
                cell_text = ""  # no record
            cells.append(cell_text)

        rows.append({
            "student": stu,
            "groups": groups_str,
            "cells": cells,
        })

    return rows


# ---------------------------------------------------------------------------
# Edit modal
# ---------------------------------------------------------------------------

def open_edit_payment_modal(
    parent: ctk.CTkToplevel,
    student_id: int,
    academic_start_year: int,
    refresh_callback=None,
) -> None:
    """
    Open a modal window to edit payments for a student across one academic year.
    """
    try:
        stu = get_student(student_id)
        groups_list = get_student_groups(student_id)
    except NotFoundError:
        messagebox.showerror("Not found", f"Student {student_id} not found.")
        return
    except DBError as e:
        messagebox.showerror("DB Error", str(e))
        return

    groups_str = ", ".join(groups_list)
    year_label = make_academic_label(academic_start_year)
    months_spec = months_for_academic_year(academic_start_year)
    payments = get_payments_for_student_academic_year(student_id, academic_start_year)
    pay_map = {(p.year, p.month): p for p in payments}

    win = ctk.CTkToplevel(parent)
    win.title(f"Edit Payments — {stu.id}: {stu.name}")
    win.geometry("720x620")

    try:
        win.grab_set()
    except tk.TclError:
        win.focus_force()

    win.focus_force()

    header_frame = ctk.CTkFrame(win, fg_color="transparent")
    header_frame.pack(fill="x", padx=12, pady=(10, 4))

    ctk.CTkLabel(
        header_frame,
        text=f"Edit Payments — {stu.id}: {stu.name}",
        font=("Arial", 20, "bold"),
    ).pack(anchor="w")
    ctk.CTkLabel(
        header_frame,
        text=f"Groups: {groups_str or 'None'}",
        font=("Arial", 12),
    ).pack(anchor="w")
    ctk.CTkLabel(
        header_frame,
        text=f"Academic Year: {year_label}",
        font=("Arial", 12),
    ).pack(anchor="w")

    body_frame = ctk.CTkFrame(win, fg_color="transparent")
    body_frame.pack(fill="both", expand=True, padx=12, pady=8)

    body_frame.grid_rowconfigure(0, weight=1)
    body_frame.grid_columnconfigure(0, weight=1)

    scroll = ctk.CTkScrollableFrame(body_frame, fg_color="white")
    scroll.grid(row=0, column=0, sticky="nsew")

    # Table header
    header_row = ctk.CTkFrame(scroll, fg_color="#E5E7EB")
    header_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    header_row.grid_columnconfigure(0, weight=0)
    header_row.grid_columnconfigure(1, weight=0)
    header_row.grid_columnconfigure(2, weight=1)

    ctk.CTkLabel(header_row, text="Month", width=100, anchor="w").grid(row=0, column=0, padx=4, pady=4)
    ctk.CTkLabel(header_row, text="Status", width=140, anchor="w").grid(row=0, column=1, padx=4, pady=4)
    ctk.CTkLabel(header_row, text="Payment Date (YYYY-MM-DD)", anchor="w").grid(row=0, column=2, padx=4, pady=4)

    # One row per month
    month_state = []
    today_str = _today_str()

    for idx, (py, pm, label) in enumerate(months_spec, start=1):
        p = pay_map.get((py, pm))
        default_paid = p.paid if p else "unpaid"
        default_date = p.payment_date if p else today_str

        row_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        row_frame.grid(row=idx, column=0, sticky="ew", pady=2)
        row_frame.grid_columnconfigure(2, weight=1)

        # Month label (e.g. "Aug 2024-08")
        display = f"{label}  {py}-{pm:02d}"
        ctk.CTkLabel(row_frame, text=display, width=120, anchor="w").grid(row=0, column=0, padx=4, pady=2)

        paid_var = tk.StringVar(value=default_paid if default_paid in ("paid", "unpaid") else "unpaid")

        status_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
        status_frame.grid(row=0, column=1, padx=4, pady=2, sticky="w")

        ctk.CTkRadioButton(status_frame, text="Paid", variable=paid_var, value="paid").grid(row=0, column=0, padx=2)
        ctk.CTkRadioButton(status_frame, text="Unpaid", variable=paid_var, value="unpaid").grid(row=0, column=1, padx=2)

        date_entry = ctk.CTkEntry(row_frame, width=160)
        date_entry.insert(0, default_date)
        date_entry.grid(row=0, column=2, padx=4, pady=2, sticky="ew")

        month_state.append({
            "year": py,
            "month": pm,
            "paid_var": paid_var,
            "date_entry": date_entry,
        })

    # Buttons
    btn_frame = ctk.CTkFrame(win, fg_color="transparent")
    btn_frame.pack(fill="x", padx=12, pady=(4, 10))

    def handle_save():
        items = []
        for st in month_state:
            paid = st["paid_var"].get()
            if paid not in ("paid", "unpaid"):
                paid = "unpaid"
            ds = st["date_entry"].get().strip() or today_str
            # simple validation
            try:
                datetime.strptime(ds, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Invalid date", f"Invalid date format: {ds}\nUse YYYY-MM-DD.")
                return

            items.append({
                "year": st["year"],
                "month": st["month"],
                "paid": paid,
                "payment_date": ds,
            })

        try:
            upsert_payments_bulk(student_id, items)
        except DBError as e:
            messagebox.showerror("DB Error", str(e))
            return

        messagebox.showinfo("Saved", "Payments updated successfully.")
        win.destroy()
        if refresh_callback:
            try:
                refresh_callback()
            except Exception:
                pass

    ctk.CTkButton(btn_frame, text="Save", command=handle_save, fg_color="#3B82F6").pack(side="left", padx=4)
    ctk.CTkButton(btn_frame, text="Cancel", command=win.destroy).pack(side="left", padx=4)


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def export_history_pdf(academic_label: str, group_name: str | None) -> None:
    """
    Export the current academic year + group view to a PDF.
    """
    start_year = parse_academic_label(academic_label)
    rows = load_history_rows(start_year, group_name if group_name != "All" else None)

    if not rows:
        messagebox.showinfo("No data", "There are no rows to export for this selection.")
        return

    os.makedirs("exports", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_group = (group_name or "All").replace(" ", "_")
    filename = os.path.join("exports", f"payments_history_{academic_label.replace(' ', '').replace('-', '_')}_{safe_group}_{timestamp}.pdf")

    c = canvas.Canvas(filename, pagesize=landscape(A4))
    width, height = landscape(A4)

    margin_x = 40
    margin_y = 40
    line_h = 12

    # Header
    y = height - margin_y
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_x, y, f"Payments History — Academic Year {academic_label} — Group: {group_name or 'All'}")
    y -= line_h * 2

    # Columns: ID, Name, Groups, Aug..Jul
    headings = ["ID", "Name", "Groups"] + MONTH_COLS

    # x positions
    x_id = margin_x
    x_name = x_id + 35
    x_groups = x_name + 150
    x_month_start = x_groups + 180
    col_w_month = 35

    x_positions = [x_id, x_name, x_groups] + [
        x_month_start + i * col_w_month for i in range(len(MONTH_COLS))
    ]

    # Draw headings
    c.setFont("Helvetica-Bold", 9)
    for col, x in zip(headings, x_positions):
        c.drawString(x, y, col)
    y -= line_h

    # Rows
    c.setFont("Helvetica", 8)
    for row in rows:
        if y < margin_y:
            c.showPage()
            y = height - margin_y
            c.setFont("Helvetica", 8)

        stu = row["student"]
        groups_str = row["groups"]
        cells = row["cells"]

        c.drawString(x_positions[0], y, str(stu.id))
        c.drawString(x_positions[1], y, stu.name[:24])
        c.drawString(x_positions[2], y, groups_str[:26])

        for idx, val in enumerate(cells):
            if val.startswith("Paid"):
                txt = "P"
            elif val == "Unpaid":
                txt = "U"
            else:
                txt = ""
            c.drawString(x_positions[3 + idx], y, txt)

        y -= line_h

    c.save()
    messagebox.showinfo("Exported", f"PDF exported as:\n{filename}")


# ---------------------------------------------------------------------------
# Main history window
# ---------------------------------------------------------------------------

def open_history_window(root: ctk.CTk | None = None) -> None:
    """
    Open the Payments History window.

    root: parent window (CTk). If None, uses the global ElNajahSchool.
    """
    global ElNajahSchool

    if root is None:
        root = ElNajahSchool
    if root is None:
        raise RuntimeError("Root window is not set for payments history window.")

    prefs = load_prefs()
    year_labels = get_academic_year_labels()

    # Determine default academic year
    default_label = make_academic_label(guess_current_academic_start_year())
    if prefs.get("academic_label") in year_labels:
        default_label = prefs["academic_label"]

    academic_year_var = ctk.StringVar(value=default_label)

    # Groups
    all_groups = get_all_groups()
    group_values = ["All"] + all_groups
    default_group = prefs.get("group_name", "All")
    if default_group not in group_values:
        default_group = "All"
    group_var = ctk.StringVar(value=default_group)

    win = ctk.CTkToplevel(root)
    win.title("Payments History Logs")
    try:
        win.state("zoomed")
    except Exception:
        win.geometry("1100x700")

    # Make grab_set safe on window managers that complain
    try:
        win.grab_set()
    except tk.TclError:
        # Fallback: just focus the window, no modal grab
        win.focus_force()

    win.focus_force()

    # Top controls
    top_frame = ctk.CTkFrame(win, fg_color="transparent")
    top_frame.pack(side="top", fill="x", padx=12, pady=(10, 4))

    ctk.CTkLabel(top_frame, text="Academic Year:", font=("Arial", 14)).grid(row=0, column=0, padx=4, pady=4, sticky="w")
    year_menu = ctk.CTkOptionMenu(top_frame, variable=academic_year_var, values=year_labels, width=140)
    year_menu.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="w")

    ctk.CTkLabel(top_frame, text="Group:", font=("Arial", 14)).grid(row=0, column=2, padx=4, pady=4, sticky="w")
    group_menu = ctk.CTkOptionMenu(top_frame, variable=group_var, values=group_values, width=140)
    group_menu.grid(row=0, column=3, padx=(0, 8), pady=4, sticky="w")

    # Buttons
    btn_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
    btn_frame.grid(row=0, column=4, padx=8, pady=4, sticky="w")

    # History tree
    main_frame = ctk.CTkFrame(win, fg_color="white")
    main_frame.pack(fill="both", expand=True, padx=12, pady=8)

    columns = ("id", "name", "groups") + tuple(MONTH_COLS)
    tree = ttk.Treeview(main_frame, columns=columns, show="headings")

    tree.heading("id", text="ID")
    tree.heading("name", text="Name")
    tree.heading("groups", text="Groups")
    for m in MONTH_COLS:
        tree.heading(m, text=m)

    tree.column("id", width=60, anchor="center")
    tree.column("name", width=180, anchor="w")
    tree.column("groups", width=220, anchor="w")
    for m in MONTH_COLS:
        tree.column(m, width=60, anchor="center")

    scroll_y = ttk.Scrollbar(main_frame, orient="vertical", command=tree.yview)
    scroll_x = ttk.Scrollbar(main_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

    tree.grid(row=0, column=0, sticky="nsew")
    scroll_y.grid(row=0, column=1, sticky="ns")
    scroll_x.grid(row=1, column=0, sticky="ew")

    main_frame.grid_rowconfigure(0, weight=1)
    main_frame.grid_columnconfigure(0, weight=1)

    # Bottom buttons
    bottom_frame = ctk.CTkFrame(win, fg_color="transparent")
    bottom_frame.pack(side="bottom", fill="x", padx=12, pady=(4, 10))

    def refresh_tree():
        # Clear
        for item in tree.get_children():
            tree.delete(item)

        start_year = parse_academic_label(academic_year_var.get())
        g_name = group_var.get()
        try:
            rows = load_history_rows(start_year, g_name if g_name != "All" else None)
        except DBError as e:
            messagebox.showerror("DB Error", str(e))
            return

        for row in rows:
            stu = row["student"]
            vals = [stu.id, stu.name, row["groups"]] + row["cells"]
            tree.insert("", "end", values=vals)

    def on_edit_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showerror("No selection", "Please select a student row to edit.")
            return
        vals = tree.item(sel[0], "values")
        if not vals:
            return
        try:
            sid = int(vals[0])
        except Exception:
            return

        start_year = parse_academic_label(academic_year_var.get())
        open_edit_payment_modal(win, sid, start_year, refresh_callback=refresh_tree)

    def on_double_click(event=None):
        on_edit_selected()

    def on_export():
        export_history_pdf(academic_year_var.get(), group_var.get())

    def on_close():
        save_prefs(academic_year_var.get(), group_var.get())
        win.destroy()

    # Buttons on top frame
    ctk.CTkButton(btn_frame, text="Refresh", command=refresh_tree).pack(side="left", padx=2)
    ctk.CTkButton(btn_frame, text="Edit Selected", command=on_edit_selected).pack(side="left", padx=2)
    ctk.CTkButton(btn_frame, text="Export PDF", command=on_export).pack(side="left", padx=2)
    ctk.CTkButton(btn_frame, text="Close", command=on_close).pack(side="left", padx=2)

    # Bindings
    tree.bind("<Double-1>", on_double_click)

    year_menu.configure(command=lambda _value: refresh_tree())
    group_menu.configure(command=lambda _value: refresh_tree())

    # Initial load
    refresh_tree()


# Backwards-compatible name used by your main file's history button
def open_full_window():
    """
    Backwards-compatible wrapper; calls open_history_window using the global root.
    """
    open_history_window(ElNajahSchool)
