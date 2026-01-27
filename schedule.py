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

def _bind_mousewheel_local(scrollable: ctk.CTkScrollableFrame):
    def _on_mousewheel(event):
        if event.num == 4:
            scrollable._parent_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            scrollable._parent_canvas.yview_scroll(1, "units")
        else:
            scrollable._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind(_e=None):
        scrollable.bind_all("<MouseWheel>", _on_mousewheel)
        scrollable.bind_all("<Button-4>", _on_mousewheel)
        scrollable.bind_all("<Button-5>", _on_mousewheel)

    def _unbind(_e=None):
        scrollable.unbind_all("<MouseWheel>")
        scrollable.unbind_all("<Button-4>")
        scrollable.unbind_all("<Button-5>")

    scrollable.bind("<Enter>", _bind)
    scrollable.bind("<Leave>", _unbind)


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
        text="Schedule",
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

    _bind_mousewheel_local(card)

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

def save_group_schedule_and_regenerate(group_id: int, payload: dict | None) -> None:
    """
    Writes:
      - group_schedules
      - group_schedule_days
      - group_schedule_exclusions
    Then regenerates:
      - sessions

    If payload is None => delete schedule + days + exclusions + sessions for that group.
    """
    conn = _get_conn()
    cur = conn.cursor()

    try:
        # If schedule is not set => wipe existing schedule data
        if not payload:
            cur.execute("DELETE FROM group_schedule_days WHERE group_id = ?", (group_id,))
            cur.execute("DELETE FROM group_schedule_exclusions WHERE group_id = ?", (group_id,))
            cur.execute("DELETE FROM group_schedules WHERE group_id = ?", (group_id,))
            cur.execute("DELETE FROM sessions WHERE group_id = ?", (group_id,))
            conn.commit()
            return

        start_date = payload["start_date"]  # YYYY-MM-DD
        end_date = payload["end_date"]      # YYYY-MM-DD
        days_map = payload["days"]          # {weekday: {"enabled":bool,"start":"HH:MM","end":"HH:MM"}}
        exclusions = payload.get("exclusions", [])  # ["YYYY-MM-DD", ...]

        # --- Upsert group_schedules
        cur.execute(
            """
            INSERT INTO group_schedules (group_id, start_date, end_date)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                start_date = excluded.start_date,
                end_date   = excluded.end_date
            """,
            (group_id, start_date, end_date),
        )

        # --- Replace weekday rules
        cur.execute("DELETE FROM group_schedule_days WHERE group_id = ?", (group_id,))
        day_rows = []
        for wday, info in days_map.items():
            # keys might be strings depending on how dict was created
            wday_int = int(wday)
            if info.get("enabled"):
                day_rows.append((group_id, wday_int, info["start"].strip(), info["end"].strip()))

        if day_rows:
            cur.executemany(
                """
                INSERT INTO group_schedule_days (group_id, weekday, start_time, end_time)
                VALUES (?, ?, ?, ?)
                """,
                day_rows,
            )

        # --- Replace exclusions (just dates)
        cur.execute("DELETE FROM group_schedule_exclusions WHERE group_id = ?", (group_id,))
        ex_rows = [(group_id, d.strip()) for d in exclusions if d.strip()]
        if ex_rows:
            cur.executemany(
                """
                INSERT INTO group_schedule_exclusions (group_id, date)
                VALUES (?, ?)
                """,
                ex_rows,
            )

        # --- Regenerate sessions (hard regenerate, as agreed)
        cur.execute("DELETE FROM sessions WHERE group_id = ?", (group_id,))

        # Build lookup weekday -> (start,end)
        weekday_time = {int(w): (info["start"].strip(), info["end"].strip())
                        for w, info in days_map.items() if info.get("enabled")}

        selected_weekdays = set(weekday_time.keys())
        excluded_set = set(exclusions)

        if selected_weekdays:
            from datetime import datetime, timedelta
            sd = datetime.strptime(start_date, "%Y-%m-%d").date()
            ed = datetime.strptime(end_date, "%Y-%m-%d").date()

            session_rows = []
            d = sd
            while d <= ed:
                ds = d.strftime("%Y-%m-%d")
                if d.weekday() in selected_weekdays and ds not in excluded_set:
                    st, et = weekday_time[d.weekday()]
                    session_rows.append((group_id, ds, st, et))
                d += timedelta(days=1)

            if session_rows:
                cur.executemany(
                    """
                    INSERT INTO sessions (group_id, date, start_time, end_time)
                    VALUES (?, ?, ?, ?)
                    """,
                    session_rows,
                )
            
        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# UI: View Sessions window (cards + filters + add/edit/delete + review)
# ---------------------------------------------------------------------------

_DEFAULT_PRIMARY = "#3B82F6"
_DEFAULT_HOVER = "#2563EB"
_DEFAULT_DANGER = "#DC2626"
_DEFAULT_DANGER_HOVER = "#B91C1C"
_DEFAULT_BG_PAST = "#E5E7EB"
_DEFAULT_BG_UPCOMING = "#DCFCE7"
_DEFAULT_BG_RUNNING = "#60A5FA"

def _safe_grab(win: tk.Misc) -> None:
    """Best-effort modal grab without 'window not viewable' crashes."""
    try:
        win.update_idletasks()
        try:
            win.deiconify()
        except Exception:
            pass
        try:
            win.lift()
        except Exception:
            pass

        def _try():
            try:
                win.grab_set()
            except tk.TclError:
                try:
                    win.focus_force()
                except Exception:
                    pass

        win.after(0, _try)
    except Exception:
        # Never crash the app just because modal grab failed
        pass


def _is_descendant(widget: tk.Misc | None, ancestor: tk.Misc) -> bool:
    """Return True if widget is inside ancestor (or equals it)."""
    w = widget
    while w is not None:
        if w == ancestor:
            return True
        try:
            w = w.master
        except Exception:
            break
    return False


def _bind_wheel_to_scroll(top: tk.Misc, scroll: ctk.CTkScrollableFrame) -> None:
    """Bind mouse wheel for one toplevel only (no bind_all), Linux + Windows."""
    canvas = getattr(scroll, "_parent_canvas", None)
    if canvas is None:
        return

    def _on_wheel(event):
        # Only scroll when the pointer is over the scroll area
        w = top.winfo_containing(event.x_root, event.y_root)
        if not _is_descendant(w, scroll):
            return

        if getattr(event, "num", None) == 4:
            canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            canvas.yview_scroll(1, "units")
        else:
            delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
            if delta:
                canvas.yview_scroll(delta, "units")

    # Use add='+' so we don't clobber other bindings
    try:
        top.bind("<MouseWheel>", _on_wheel, add="+")
        top.bind("<Button-4>", _on_wheel, add="+")
        top.bind("<Button-5>", _on_wheel, add="+")
    except Exception:
        pass


def _get_group_name_by_id(group_id: int) -> str:
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM groups WHERE id = ?", (group_id,))
        row = cur.fetchone()
        return str(row[0]) if row and row[0] else f"Group {group_id}"
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Sessions + Attendance review helpers (View Sessions UI)
# ---------------------------------------------------------------------------

def get_group_sessions(group_id: int) -> list[dict]:
    """Return sessions for group ordered by date, start_time."""
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, date, start_time, end_time
            FROM sessions
            WHERE group_id = ?
            ORDER BY date ASC, start_time ASC
            """,
            (group_id,),
        )
        return [
            {"id": int(r[0]), "date": r[1], "start_time": r[2], "end_time": r[3]}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def get_attendance_counts_for_sessions(session_ids: list[int]) -> dict[int, int]:
    """Batch present counts: {session_id: present_count}"""
    if not session_ids:
        return {}

    conn = _get_conn()
    cur = conn.cursor()
    try:
        placeholders = ",".join("?" for _ in session_ids)
        cur.execute(
            f"""
            SELECT session_id, COUNT(*)
            FROM attendance
            WHERE session_id IN ({placeholders})
            GROUP BY session_id
            """,
            session_ids,
        )
        return {int(sid): int(cnt) for (sid, cnt) in cur.fetchall()}
    finally:
        conn.close()


def _get_group_students_by_id(group_id: int) -> list[dict]:
    """Current group students: [{'id':..,'name':..}, ...]"""
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT s.id, s.name
            FROM student_group sg
            JOIN students s ON s.id = sg.student_id
            WHERE sg.group_id = ?
            ORDER BY s.name COLLATE NOCASE
            """,
            (group_id,),
        )
        return [{"id": int(r[0]), "name": str(r[1])} for r in cur.fetchall()]
    finally:
        conn.close()


def get_session_review_lists(session_id: int, group_id: int) -> dict:
    """
    Review-only lists:
      present = students with a row in attendance(session_id, student_id)
      absent  = group students not present
    """
    students = _get_group_students_by_id(group_id)

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT student_id FROM attendance WHERE session_id = ?", (session_id,))
        present_ids = {int(r[0]) for r in cur.fetchall()}
    finally:
        conn.close()

    present = [s for s in students if s["id"] in present_ids]
    absent = [s for s in students if s["id"] not in present_ids]

    return {
        "taken": len(present_ids) > 0,
        "total": len(students),
        "present": present,
        "absent": absent,
    }


def _validate_session_inputs(date_s: str, start_s: str, end_s: str) -> tuple[str, str, str]:
    d = _parse_date(date_s).strftime("%Y-%m-%d")

    sh, sm = _parse_time_hhmm(start_s)
    eh, em = _parse_time_hhmm(end_s)

    start_s2 = f"{sh:02d}:{sm:02d}"
    end_s2 = f"{eh:02d}:{em:02d}"

    if (eh * 60 + em) <= (sh * 60 + sm):
        raise ValueError("End time must be after start time.")

    return d, start_s2, end_s2


def add_session(group_id: int, date_s: str, start_s: str, end_s: str) -> int:
    d, st, et = _validate_session_inputs(date_s, start_s, end_s)

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO sessions (group_id, date, start_time, end_time)
            VALUES (?, ?, ?, ?)
            """,
            (group_id, d, st, et),
        )
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise ValueError("A session with the same date/time already exists for this group.") from e
    finally:
        conn.close()


def update_session(session_id: int, date_s: str, start_s: str, end_s: str) -> None:
    d, st, et = _validate_session_inputs(date_s, start_s, end_s)

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE sessions
            SET date = ?, start_time = ?, end_time = ?
            WHERE id = ?
            """,
            (d, st, et, session_id),
        )
        if cur.rowcount == 0:
            raise ValueError("Session not found.")
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise ValueError("That edit would create a duplicate session (same date/time).") from e
    finally:
        conn.close()


def delete_session(session_id: int) -> None:
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()

def open_view_sessions(
    group_id: int,
    parent=None,
    *,
    primary: str = _DEFAULT_PRIMARY,
    hover: str = _DEFAULT_HOVER,
    danger: str = _DEFAULT_DANGER,
    danger_hover: str = _DEFAULT_DANGER_HOVER,
) -> None:
    """
    Popup window to view + manage sessions (cards UI).
    - Filters: All / Past / Upcoming, and month scope (Prev/Current/Next/All)
    - Cards grouped by month
    - Add / Edit / Delete session
    - Review (present/absent lists) for past sessions only
    """
    group_name = _get_group_name_by_id(group_id)

    top = ctk.CTkToplevel(parent)
    top.title(f"Sessions — {group_name}")
    top.geometry("900x680")

    _safe_grab(top)
    try:
        top.focus_force()
    except Exception:
        pass

    # ---------------- Top bar ----------------
    header = ctk.CTkFrame(top, fg_color="transparent")
    header.pack(fill="x", padx=16, pady=(14, 6))

    ctk.CTkLabel(header, text=f"Sessions — {group_name}", font=("Arial", 18, "bold")).pack(side="left")

    # Filters row
    filter_frame = ctk.CTkFrame(top, fg_color="transparent")
    filter_frame.pack(fill="x", padx=16, pady=(0, 8))

    mode_var = ctk.StringVar(value="All")          
    month_var = ctk.StringVar(value="All")    

    ctk.CTkLabel(filter_frame, text="Filter:", font=("Arial", 12)).pack(side="left", padx=(0, 6))
    mode_menu = ctk.CTkOptionMenu(filter_frame, variable=mode_var, values=["All", "Past", "Upcoming"], width=140)
    mode_menu.pack(side="left", padx=(0, 10))

    ctk.CTkLabel(filter_frame, text="Month:", font=("Arial", 12)).pack(side="left", padx=(0, 6))
    month_menu = ctk.CTkOptionMenu(filter_frame, variable=month_var, values=["All", "Prev", "Current", "Next"], width=140)
    month_menu.pack(side="left", padx=(0, 10))

    stats_lbl = ctk.CTkLabel(filter_frame, text="", font=("Arial", 12))
    stats_lbl.pack(side="left", padx=8)

    # Actions on the right
    ctk.CTkButton(
        filter_frame,
        text="＋ Add Session",
        fg_color=primary,
        hover_color=hover,
        command=lambda: _open_add_session_modal(),
    ).pack(side="right")

    # ---------------- Loading overlay ----------------
    loading = {"frame": None, "bar": None}

    def start_loading(text: str = "Loading sessions..."):
        if loading["frame"] is not None:
            return
        lf = ctk.CTkFrame(top, fg_color="white", corner_radius=12)
        lf.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(lf, text=text, font=("Arial", 14, "bold")).pack(padx=18, pady=(14, 8))
        bar = ctk.CTkProgressBar(lf, mode="indeterminate", width=260)
        bar.pack(padx=18, pady=(0, 14))
        bar.start()
        loading["frame"] = lf
        loading["bar"] = bar
        try:
            top.update_idletasks()
        except Exception:
            pass

    def stop_loading():
        if loading["bar"] is not None:
            try:
                loading["bar"].stop()
            except Exception:
                pass
        if loading["frame"] is not None:
            try:
                loading["frame"].destroy()
            except Exception:
                pass
        loading["frame"] = None
        loading["bar"] = None

    # ---------------- Scroll area ----------------
    scroll = ctk.CTkScrollableFrame(top, fg_color="white")
    scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    _bind_wheel_to_scroll(top, scroll)

    # -------- helpers --------
    def _session_status(sess: dict) -> str:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        nt = now.strftime("%H:%M")

        d = sess["date"]
        st = sess["start_time"]
        et = sess["end_time"]

        if d < today:
            return "past"
        if d > today:
            return "upcoming"
        # today
        if st <= nt < et:
            return "running"
        if et <= nt:
            return "past"
        return "upcoming"

    def _month_scope_ok(sess: dict) -> bool:
        scope = month_var.get()
        if scope == "All":
            return True

        now = datetime.now()
        y, m = now.year, now.month

        sy = int(sess["date"][:4])
        sm = int(sess["date"][5:7])

        if scope == "Current":
            return (sy, sm) == (y, m)
        if scope == "Prev":
            py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
            return (sy, sm) == (py, pm)
        if scope == "Next":
            ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
            return (sy, sm) == (ny, nm)
        return True

    def _open_review(sess: dict):
        # Only past sessions are reviewable per your rule
        if _session_status(sess) != "past":
            messagebox.showinfo("Not Available", "You can review presence/absence only for past sessions.")
            return

        data = get_session_review_lists(int(sess["id"]), group_id)

        win = ctk.CTkToplevel(top)
        win.title(f"Review — {sess['date']} {sess['start_time']}–{sess['end_time']}")
        win.geometry("920x560")
        _safe_grab(win)
        win.focus_force()

        topbar = ctk.CTkFrame(win, fg_color="transparent")
        topbar.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            topbar,
            text=(
                f"{sess['date']}  {sess['start_time']}–{sess['end_time']}   |   "
                f"Total: {data['total']}  Present: {len(data['present'])}  Absent: {len(data['absent'])}"
            ),
            font=("Arial", 14, "bold"),
        ).pack(side="left")

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(body, text="Present", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkLabel(body, text="Absent", font=("Arial", 14, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0))

        left = ctk.CTkScrollableFrame(body, fg_color="white")
        right = ctk.CTkScrollableFrame(body, fg_color="white")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 0))

        _bind_wheel_to_scroll(win, left)
        _bind_wheel_to_scroll(win, right)

        for s in data["present"]:
            ctk.CTkLabel(left, text=f"{s['id']} · {s['name']}", anchor="w").pack(fill="x", padx=10, pady=3)

        for s in data["absent"]:
            ctk.CTkLabel(right, text=f"{s['id']} · {s['name']}", anchor="w").pack(fill="x", padx=10, pady=3)

    def _open_edit_session_modal(sess: dict):
        win = ctk.CTkToplevel(top)
        win.title("Edit Session")
        win.geometry("420x270")
        _safe_grab(win)
        win.focus_force()

        frm = ctk.CTkFrame(win, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(frm, text="Date (YYYY-MM-DD):").pack(anchor="w")
        d_ent = ctk.CTkEntry(frm); d_ent.pack(fill="x", pady=(0, 10)); d_ent.insert(0, sess["date"])

        ctk.CTkLabel(frm, text="Start (HH:MM):").pack(anchor="w")
        s_ent = ctk.CTkEntry(frm); s_ent.pack(fill="x", pady=(0, 10)); s_ent.insert(0, sess["start_time"])

        ctk.CTkLabel(frm, text="End (HH:MM):").pack(anchor="w")
        e_ent = ctk.CTkEntry(frm); e_ent.pack(fill="x", pady=(0, 14)); e_ent.insert(0, sess["end_time"])

        def save():
            try:
                update_session(int(sess["id"]), d_ent.get(), s_ent.get(), e_ent.get())
            except Exception as e:
                messagebox.showerror("Edit Error", str(e))
                return
            win.destroy()
            refresh()

        btns = ctk.CTkFrame(frm, fg_color="transparent"); btns.pack(fill="x")
        ctk.CTkButton(btns, text="Save", fg_color=primary, hover_color=hover, command=save).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Cancel", command=win.destroy).pack(side="left")

    def _open_add_session_modal():
        win = ctk.CTkToplevel(top)
        win.title("Add Session")
        win.geometry("420x270")
        _safe_grab(win)
        win.focus_force()

        frm = ctk.CTkFrame(win, fg_color="transparent")
        frm.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(frm, text="Date (YYYY-MM-DD):").pack(anchor="w")
        d_ent = ctk.CTkEntry(frm); d_ent.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(frm, text="Start (HH:MM):").pack(anchor="w")
        s_ent = ctk.CTkEntry(frm); s_ent.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(frm, text="End (HH:MM):").pack(anchor="w")
        e_ent = ctk.CTkEntry(frm); e_ent.pack(fill="x", pady=(0, 14))

        def add_one():
            try:
                add_session(group_id, d_ent.get(), s_ent.get(), e_ent.get())
            except Exception as e:
                messagebox.showerror("Add Error", str(e))
                return
            win.destroy()
            refresh()

        btns = ctk.CTkFrame(frm, fg_color="transparent"); btns.pack(fill="x")
        ctk.CTkButton(btns, text="Add", fg_color=primary, hover_color=hover, command=add_one).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btns, text="Cancel", command=win.destroy).pack(side="left")

    def _delete_one_session(sess: dict):
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete session on {sess['date']} {sess['start_time']}–{sess['end_time']}?",
        ):
            return
        try:
            delete_session(int(sess["id"]))
        except Exception as e:
            messagebox.showerror("Delete Error", str(e))
            return
        refresh()

    # Render (lazy, grouped by month)
    last_month = {"val": None}

    def _month_header(ym: str):
        sep = ctk.CTkFrame(scroll, fg_color="transparent")
        sep.pack(fill="x", padx=2, pady=(10, 4))

        ctk.CTkLabel(sep, text=ym, font=("Arial", 14, "bold")).pack(side="left")
        line = ctk.CTkFrame(sep, fg_color="#D1D5DB", height=2)
        line.pack(side="left", fill="x", expand=True, padx=10, pady=10)

    def render_one(sess: dict, present_counts: dict[int, int], total_students: int):
        ym = sess["date"][:7]  # YYYY-MM
        if last_month["val"] != ym:
            last_month["val"] = ym
            _month_header(ym)

        status = _session_status(sess)
        bg = "white"
        if status == "past":
            bg = _DEFAULT_BG_PAST
        elif status == "running":
            bg = _DEFAULT_BG_RUNNING
        else:
            bg = _DEFAULT_BG_UPCOMING

        card = ctk.CTkFrame(scroll, fg_color=bg, corner_radius=12)
        card.pack(fill="x", padx=2, pady=6)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=12, pady=10)

        date_text = sess["date"]
        # Weekday label (Mon/Tue/...)
        try:
            wd = datetime.strptime(sess["date"], "%Y-%m-%d").strftime("%a")
        except Exception:
            wd = ""

        lbl1 = ctk.CTkLabel(left, text=f"{date_text} ({wd})", font=("Arial", 14, "bold"), anchor="w")
        lbl1.pack(anchor="w")

        lbl2 = ctk.CTkLabel(left, text=f"{sess['start_time']} – {sess['end_time']}   ·   {status}", font=("Arial", 12), anchor="w")
        lbl2.pack(anchor="w", pady=(2, 0))

        # Attendance summary (only show for past sessions)
        if status == "past" and total_students > 0:
            present = int(present_counts.get(int(sess["id"]), 0))
            # If there's no attendance rows, treat it as "not taken"
            if int(sess["id"]) in present_counts:
                absent = max(0, total_students - present)
                lbl3 = ctk.CTkLabel(left, text=f"Present: {present}   Absent: {absent}   Total: {total_students}", font=("Arial", 12))
            else:
                lbl3 = ctk.CTkLabel(left, text=f"Attendance: not taken   Total: {total_students}", font=("Arial", 12))
            lbl3.pack(anchor="w", pady=(6, 0))

        # Clickable review area (labels only; avoids colliding with edit/delete buttons)
        def _review(_e=None):
            _open_review(sess)

        if status == "past":
            lbl1.bind("<Double-1>", _review)
            lbl2.bind("<Double-1>", _review)

        right = ctk.CTkFrame(card, fg_color="transparent")
        right.pack(side="right", padx=10, pady=10)

        if status == "past":
            ctk.CTkButton(
                right,
                text="👁",
                width=25,
                fg_color=primary,
                hover_color=hover,
                command=lambda s=sess: _open_review(s),
            ).pack(side="left", padx=3)

        ctk.CTkButton(
            right,
            text="✎",
            width=38,
            fg_color="#6B7280",
            hover_color="#4B5563",
            command=lambda s=sess: _open_edit_session_modal(s),
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            right,
            text="✖",
            width=38,
            fg_color=danger,
            hover_color=danger_hover,
            command=lambda s=sess: _delete_one_session(s),
        ).pack(side="left", padx=3)

    def refresh():
        start_loading()

        # Clear existing UI immediately so user sees something happening
        for w in scroll.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        last_month["val"] = None

        top.after(10, _refresh_work)

    def _refresh_work():
        if not top.winfo_exists():
            return
        try:
            sessions = get_group_sessions(group_id)
            sid_list = [int(s["id"]) for s in sessions]
            present_counts = get_attendance_counts_for_sessions(sid_list)
            total_students = len(_get_group_students_by_id(group_id))

            # Apply filters
            filt = mode_var.get()
            sessions2: list[dict] = []
            for s in sessions:
                st = _session_status(s)
                if filt == "Past" and st != "past":
                    continue
                if filt == "Upcoming" and st not in ("upcoming", "running"):
                    continue
                if not _month_scope_ok(s):
                    continue
                sessions2.append(s)

            # Stats update (based on ALL sessions, not filtered)
            past_n = sum(1 for s in sessions if _session_status(s) == "past")
            up_n = sum(1 for s in sessions if _session_status(s) in ("upcoming", "running"))
            stats_lbl.configure(text=f"Total: {len(sessions)} | Past: {past_n} | Upcoming: {up_n}")

            if not sessions2:
                stop_loading()
                empty = ctk.CTkLabel(scroll, text="No sessions to show for this filter.", font=("Arial", 14))
                empty.pack(pady=30)
                return

            # Render in batches to keep UI responsive
            state = {"i": 0}
            batch_size = 14

            def render_batch():
                i = state["i"]
                end = min(i + batch_size, len(sessions2))
                for k in range(i, end):
                    render_one(sessions2[k], present_counts, total_students)

                state["i"] = end
                if end < len(sessions2):
                    top.after(1, render_batch)
                else:
                    stop_loading()

            render_batch()

        except Exception as e:
            stop_loading()
            try:
                if top.winfo_exists():
                    messagebox.showerror("Load Error", str(e), parent=top)
            except tk.TclError:
                pass

    def _on_filter(_value=None):
        refresh()

    mode_menu.configure(command=_on_filter)
    month_menu.configure(command=_on_filter)

    refresh()
