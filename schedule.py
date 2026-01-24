from __future__ import annotations
import sqlite3
from DB import DB_PATH

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

from datetime import datetime, date, timedelta



def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_attendance_tables() -> None:
    """
    Create attendance/schedule tables if they do not exist.
    Call once at app startup (after DB.init_db()).
    """
    conn = _get_conn()
    c = conn.cursor()

    # 1) Schedule range per group (optional schedule)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS group_schedules (
            group_id    INTEGER PRIMARY KEY,
            start_date  TEXT NOT NULL,   -- YYYY-MM-DD
            end_date    TEXT NOT NULL,   -- YYYY-MM-DD
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # 2) Weekday rules (0=Mon .. 6=Sun) with per-day times
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS group_schedule_days (
            group_id    INTEGER NOT NULL,
            weekday     INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
            start_time  TEXT NOT NULL,   -- HH:MM
            end_time    TEXT NOT NULL,   -- HH:MM
            UNIQUE(group_id, weekday),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # 3) Excluded dates (just dates, no reason)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS group_schedule_exclusions (
            group_id    INTEGER NOT NULL,
            date        TEXT NOT NULL,   -- YYYY-MM-DD
            UNIQUE(group_id, date),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # 4) Generated sessions (lesson instances)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    INTEGER NOT NULL,
            date        TEXT NOT NULL,   -- YYYY-MM-DD
            start_time  TEXT NOT NULL,   -- HH:MM
            end_time    TEXT NOT NULL,   -- HH:MM
            UNIQUE(group_id, date, start_time, end_time),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
        """
    )

    # Helpful index for queries like "sessions for group between dates"
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_group_date
        ON sessions(group_id, date)
        """
    )

    # 5) Attendance (presence only): row exists => present
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (
            session_id  INTEGER NOT NULL,
            student_id  INTEGER NOT NULL,
            UNIQUE(session_id, student_id),
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        )
        """
    )

    # Helpful index for analytics later (per student)
    c.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_attendance_student
        ON attendance(student_id)
        """
    )

    conn.commit()
    conn.close()

# ----------------------------
# Helpers
# ----------------------------

WEEKDAYS = [
    ("Mon", 0),
    ("Tue", 1),
    ("Wed", 2),
    ("Thu", 3),
    ("Fri", 4),
    ("Sat", 5),
    ("Sun", 6),
]

def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()

def _parse_time_hhmm(s: str) -> tuple[int, int]:
    s = s.strip()
    dt = datetime.strptime(s, "%H:%M")
    return dt.hour, dt.minute

def _format_error(title: str, msg: str) -> None:
    messagebox.showerror(title, msg)

def _count_sessions(
    start_d: date,
    end_d: date,
    selected_weekdays: set[int],
    exclusions: set[date],
) -> int:
    if end_d < start_d:
        return 0
    if not selected_weekdays:
        return 0

    count = 0
    cur = start_d
    while cur <= end_d:
        if cur.weekday() in selected_weekdays and cur not in exclusions:
            count += 1
        cur += timedelta(days=1)
    return count

def _bind_mousewheel(widget):
    def _on_mousewheel(event):
        # Windows / Linux
        if event.num == 4:      # Linux scroll up
            widget._parent_canvas.yview_scroll(-1, "units")
        elif event.num == 5:    # Linux scroll down
            widget._parent_canvas.yview_scroll(1, "units")
        else:                   # Windows / Mac
            widget._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # Windows / Mac
    widget.bind_all("<MouseWheel>", _on_mousewheel)
    # Linux
    widget.bind_all("<Button-4>", _on_mousewheel)
    widget.bind_all("<Button-5>", _on_mousewheel)

# ----------------------------
# Public: plugin attach
# ----------------------------

def attach_group_schedule_extension(
    parent_frame,
    initial_data: dict | None = None,
):
    """
    Build the schedule UI inside parent_frame.

    Optional + collapsible behavior:
      - Collapsed => treated as "no schedule"
      - validate() returns True (doesn't block saving)
      - apply() returns None
    """
    initial_data = initial_data or {}

    root = ctk.CTkFrame(parent_frame, fg_color="transparent")
    root.pack(fill="x", padx=0, pady=(8, 0))

    # ----------------------------
    # Collapsible header
    # ----------------------------
    header = ctk.CTkFrame(root, fg_color="transparent")
    header.pack(fill="x")

    ctk.CTkLabel(
        header,
        text="Schedule (optional)",
        font=("Arial", 16, "bold"),
    ).pack(side="left")

    enabled_var = ctk.BooleanVar(value=False)  # collapsed by default

    toggle_btn = ctk.CTkButton(
        header,
        text="Show",
        width=80,
        fg_color="#3B82F6",
    )
    toggle_btn.pack(side="right")

    # ----------------------------
    # Card (content) - starts hidden
    # ----------------------------
    card = ctk.CTkScrollableFrame(
        root,
        fg_color="white",
        height=400  # controls when scrolling appears
    )

    _bind_mousewheel(card)

    # --- Date range
    range_frame = ctk.CTkFrame(card, fg_color="transparent")
    range_frame.pack(fill="x", padx=12, pady=(12, 6))
    range_frame.grid_columnconfigure(1, weight=1)
    range_frame.grid_columnconfigure(3, weight=1)

    ctk.CTkLabel(range_frame, text="Start Date (YYYY-MM-DD):").grid(row=0, column=0, sticky="w", padx=(0, 8))
    start_entry = ctk.CTkEntry(range_frame, width=140)
    start_entry.grid(row=0, column=1, sticky="ew")

    ctk.CTkLabel(range_frame, text="End Date (YYYY-MM-DD):").grid(row=0, column=2, sticky="w", padx=(12, 8))
    end_entry = ctk.CTkEntry(range_frame, width=140)
    end_entry.grid(row=0, column=3, sticky="ew")

    # Defaults
    today = date.today()
    start_entry.insert(0, initial_data.get("start_date", today.strftime("%Y-%m-%d")))
    end_entry.insert(0, initial_data.get("end_date", (today + timedelta(days=90)).strftime("%Y-%m-%d")))

    # --- Weekday selection + times
    ctk.CTkLabel(
        card,
        text="Weekly days & times",
        font=("Arial", 13, "bold"),
    ).pack(anchor="w", padx=12, pady=(6, 2))

    grid = ctk.CTkFrame(card, fg_color="transparent")
    grid.pack(fill="x", padx=12, pady=(0, 6))

    ctk.CTkLabel(grid, text="Day", width=60, anchor="w").grid(row=0, column=0, padx=(0, 8), pady=(0, 6))
    ctk.CTkLabel(grid, text="Enable", width=70, anchor="w").grid(row=0, column=1, padx=(0, 8), pady=(0, 6))
    ctk.CTkLabel(grid, text="Start (HH:MM)", width=120, anchor="w").grid(row=0, column=2, padx=(0, 8), pady=(0, 6))
    ctk.CTkLabel(grid, text="End (HH:MM)", width=120, anchor="w").grid(row=0, column=3, padx=(0, 8), pady=(0, 6))

    day_rows = []
    default_times = initial_data.get("days", {})  # {weekday: {"start":..,"end":..,"enabled":..}}

    for i, (label, wday) in enumerate(WEEKDAYS, start=1):
        enabled = bool(default_times.get(wday, {}).get("enabled", False))
        start_t = default_times.get(wday, {}).get("start", "17:00")
        end_t = default_times.get(wday, {}).get("end", "18:30")

        ctk.CTkLabel(grid, text=label, width=60, anchor="w").grid(row=i, column=0, sticky="w", pady=2)

        en_var = ctk.BooleanVar(value=enabled)
        cb = ctk.CTkCheckBox(grid, text="", variable=en_var)
        cb.grid(row=i, column=1, sticky="w", pady=2)

        start_time = ctk.CTkEntry(grid, width=120)
        start_time.insert(0, start_t)
        start_time.grid(row=i, column=2, sticky="w", pady=2)

        end_time = ctk.CTkEntry(grid, width=120)
        end_time.insert(0, end_t)
        end_time.grid(row=i, column=3, sticky="w", pady=2)

        day_rows.append({
            "weekday": wday,
            "enabled_var": en_var,
            "start_entry": start_time,
            "end_entry": end_time,
        })

    # --- Exclusions
    ex_frame = ctk.CTkFrame(card, fg_color="transparent")
    ex_frame.pack(fill="x", padx=12, pady=(6, 10))
    ex_frame.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(ex_frame, text="Excluded dates (YYYY-MM-DD), one per line:").grid(row=0, column=0, sticky="w")
    ex_text = tk.Text(ex_frame, height=4, wrap="none")
    ex_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    init_ex = initial_data.get("exclusions", [])
    if init_ex:
        ex_text.insert("1.0", "\n".join(init_ex))

    # --- Preview row
    preview_frame = ctk.CTkFrame(card, fg_color="transparent")
    preview_frame.pack(fill="x", padx=12, pady=(0, 12))

    preview_label = ctk.CTkLabel(preview_frame, text="Preview: —", font=("Arial", 12))
    preview_label.pack(side="left")

    def _collect_payload(for_preview: bool = False) -> dict | None:
        # If schedule section is collapsed/disabled, treat as "no schedule"
        if not enabled_var.get():
            return None

        try:
            sd = _parse_date(start_entry.get())
        except Exception:
            if not for_preview:
                _format_error("Invalid start date", "Start date must be YYYY-MM-DD.")
            return None

        try:
            ed = _parse_date(end_entry.get())
        except Exception:
            if not for_preview:
                _format_error("Invalid end date", "End date must be YYYY-MM-DD.")
            return None

        if ed < sd and not for_preview:
            _format_error("Invalid range", "End date must be after start date.")
            return None

        exclusions_raw = (ex_text.get("1.0", "end").strip() or "")
        exclusions: list[str] = []
        ex_set: set[date] = set()

        if exclusions_raw:
            for line in exclusions_raw.splitlines():
                t = line.strip()
                if not t:
                    continue
                try:
                    d = _parse_date(t)
                except Exception:
                    if not for_preview:
                        _format_error("Invalid excluded date", f"Excluded date is invalid: {t}\nUse YYYY-MM-DD.")
                    return None
                if d not in ex_set:
                    ex_set.add(d)
                    exclusions.append(d.strftime("%Y-%m-%d"))

        rules = {}
        selected_weekdays: set[int] = set()

        for row in day_rows:
            wday = row["weekday"]
            enabled = bool(row["enabled_var"].get())
            if enabled:
                selected_weekdays.add(wday)

            st = row["start_entry"].get().strip()
            et = row["end_entry"].get().strip()

            if enabled and not for_preview:
                try:
                    sh, sm = _parse_time_hhmm(st)
                    eh, em = _parse_time_hhmm(et)
                except Exception:
                    _format_error("Invalid time", f"Time format must be HH:MM.\nProblem on weekday {wday}.")
                    return None
                if (eh, em) <= (sh, sm):
                    _format_error("Invalid time range", f"End time must be after start time (weekday {wday}).")
                    return None

            rules[wday] = {"enabled": enabled, "start": st, "end": et}

        if not selected_weekdays and not for_preview:
            _format_error("No weekdays", "Select at least one weekday.")
            return None

        return {
            "start_date": sd.strftime("%Y-%m-%d"),
            "end_date": ed.strftime("%Y-%m-%d"),
            "days": rules,
            "exclusions": exclusions,
            "_sd": sd,
            "_ed": ed,
            "_selected_weekdays": selected_weekdays,
            "_ex_set": ex_set,
        }

    def _update_preview():
        payload = _collect_payload(for_preview=True)
        if not payload:
            preview_label.configure(text="Preview: (schedule is hidden / not set)")
            return
        total = _count_sessions(payload["_sd"], payload["_ed"], payload["_selected_weekdays"], payload["_ex_set"])
        preview_label.configure(text=f"Preview: total sessions = {total}")

    ctk.CTkButton(
        preview_frame,
        text="Preview Count",
        command=_update_preview,
        fg_color="#3B82F6",
    ).pack(side="right")

    def _toggle():
        if enabled_var.get():
            # currently shown -> hide
            enabled_var.set(False)
            try:
                card.pack_forget()
            except Exception:
                pass
            toggle_btn.configure(text="Show")
            preview_label.configure(text="Preview: (schedule is hidden / not set)")
        else:
            # currently hidden -> show
            enabled_var.set(True)
            card.pack(fill="x", pady=(8, 0))
            toggle_btn.configure(text="Hide")
            _update_preview()

    toggle_btn.configure(command=_toggle)

    # ----------------------------
    # Hooks (validate/apply)
    # ----------------------------
    def validate_fn() -> bool:
        # If schedule is not enabled, don't block saving
        if not enabled_var.get():
            return True
        return _collect_payload(for_preview=False) is not None

    def apply_fn():
        """
        If schedule is hidden => return None (meaning: no schedule).
        If shown => return dict payload (for now; later DB save).
        """
        payload = _collect_payload(for_preview=False)
        if not payload:
            return None
        payload.pop("_sd", None)
        payload.pop("_ed", None)
        payload.pop("_selected_weekdays", None)
        payload.pop("_ex_set", None)
        return payload

    return validate_fn, apply_fn
