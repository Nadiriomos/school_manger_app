from __future__ import annotations

import re
import time
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import customtkinter as ctk

from DB import DB_PATH, get_student, get_payment, NotFoundError


# ----------------------------
# Small DTOs
# ----------------------------

@dataclass
class ScanResult:
    kind: str  # "green" | "orange" | "red"
    title: str
    subtitle: str
    student_name: str = ""
    student_id: int = 0
    groups: str = ""
    session_text: str = ""
    payment_text: str = ""

PHOTO_YEAR_PROVIDER = lambda: datetime.now().year
# ----------------------------
# DB helpers (local, fast)
# ----------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _get_student_groups_with_ids(student_id: int) -> list[tuple[int, str]]:
    """
    Returns [(group_id, group_name), ...]
    """
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT g.id, g.name
            FROM student_group sg
            JOIN groups g ON g.id = sg.group_id
            WHERE sg.student_id = ?
            ORDER BY g.name
            """,
            (student_id,),
        )
        return [(int(r[0]), str(r[1])) for r in cur.fetchall()]
    finally:
        conn.close()


def _get_todays_sessions_for_groups(group_ids: list[int], today: str) -> list[dict]:
    """
    Returns rows like:
      {"id":..,"group_id":..,"date":..,"start_time":..,"end_time":..}
    """
    if not group_ids:
        return []

    placeholders = ",".join("?" for _ in group_ids)
    params = [today, *group_ids]

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT id, group_id, date, start_time, end_time
            FROM sessions
            WHERE date = ?
              AND group_id IN ({placeholders})
            ORDER BY start_time ASC
            """,
            params,
        )
        out = []
        for r in cur.fetchall():
            out.append(
                {
                    "id": int(r[0]),
                    "group_id": int(r[1]),
                    "date": str(r[2]),
                    "start_time": str(r[3]),
                    "end_time": str(r[4]),
                }
            )
        return out
    finally:
        conn.close()


def _attendance_exists(session_id: int, student_id: int) -> bool:
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM attendance WHERE session_id = ? AND student_id = ? LIMIT 1",
            (session_id, student_id),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def _mark_present(session_ids: list[int], student_id: int) -> int:
    """
    Insert attendance rows (duplicates ignored by UNIQUE constraint).
    Returns how many inserts were *attempted* (not necessarily newly inserted).
    """
    if not session_ids:
        return 0

    conn = _get_conn()
    cur = conn.cursor()
    try:
        for sid in session_ids:
            cur.execute(
                "INSERT OR IGNORE INTO attendance(session_id, student_id) VALUES (?, ?)",
                (sid, student_id),
            )
        conn.commit()
        return len(session_ids)
    finally:
        conn.close()


def _dt_from(date_str: str, hhmm: str) -> datetime:
    dt = datetime.strptime(f"{date_str} {hhmm}", "%Y-%m-%d %H:%M")
    return dt

# ----------------------------
# UI: Toast + Overlay Card
# ----------------------------

class _Toast:
    def __init__(self, root: ctk.CTk, kind: str, title: str, subtitle: str, ms: int = 1600):
        self.root = root
        self.ms = ms

        colors = {
            "green": ("#16A34A", "white"),
            "orange": ("#F59E0B", "black"),
            "red": ("#EF4444", "white"),
        }
        bg, fg = colors.get(kind, ("#111827", "white"))

        top = ctk.CTkToplevel(root)
        top.overrideredirect(True)
        try:
            top.attributes("-topmost", True)
        except Exception:
            pass

        frame = ctk.CTkFrame(top, fg_color=bg, corner_radius=14)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(frame, text=title, text_color=fg, font=("Arial", 16, "bold")).pack(
            padx=16, pady=(12, 2), anchor="w"
        )
        ctk.CTkLabel(frame, text=subtitle, text_color=fg, font=("Arial", 13)).pack(
            padx=16, pady=(0, 12), anchor="w"
        )

        # place near top-right of main window
        root.update_idletasks()
        w, h = 360, 86

        x = root.winfo_rootx() + (root.winfo_width() - w) // 2
        y = root.winfo_rooty() + (root.winfo_height() - h) // 2

        top.geometry(f"{w}x{h}+{x}+{y}")

        self.top = top
        top.after(ms, self.destroy)

    def destroy(self):
        try:
            self.top.destroy()
        except Exception:
            pass


class _OverlayCard:
    def __init__(self, root: ctk.CTk):
        self.root = root

        self.card = ctk.CTkFrame(root, fg_color="white", corner_radius=16)
        # overlay bottom-right
        self.card.place(relx=1.0, rely=1.0, anchor="se", x=-14, y=-90)

        self.badge = ctk.CTkFrame(self.card, fg_color="#111827", corner_radius=12)
        self.badge.pack(fill="x", padx=12, pady=(12, 8))

        self.badge_lbl = ctk.CTkLabel(
            self.badge, text="QR Reader: waiting…", text_color="white", font=("Arial", 13, "bold")
        )
        self.badge_lbl.pack(padx=10, pady=8, anchor="w")

        # --- NEW: horizontal row (photo + text) ---
        row = ctk.CTkFrame(self.card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 12))

        # (optional photo will be packed into `row` later)

        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)

        self.name_lbl = ctk.CTkLabel(left, text="—", font=("Arial", 18, "bold"), text_color="#111827")
        self.name_lbl.pack(pady=(0, 2), anchor="w")

        self.groups_lbl = ctk.CTkLabel(left, text="", font=("Arial", 13), text_color="#374151")
        self.groups_lbl.pack(pady=(0, 2), anchor="w")

        self.session_lbl = ctk.CTkLabel(left, text="", font=("Arial", 13), text_color="#374151")
        self.session_lbl.pack(pady=(0, 2), anchor="w")

        self.pay_lbl = ctk.CTkLabel(left, text="", font=("Arial", 13), text_color="#374151")
        self.pay_lbl.pack(pady=(0, 0), anchor="w")

        # keep refs for later
        self._row = row
        self._left = left
        self._face_lbl = None

        self.set_status("neutral", "QR Reader: waiting…")

    def set_status(self, kind: str, text: str):
        colors = {
            "neutral": ("#111827", "white"),
            "green": ("#16A34A", "white"),
            "orange": ("#F59E0B", "black"),
            "red": ("#EF4444", "white"),
        }
        bg, fg = colors.get(kind, ("#111827", "white"))
        self.badge.configure(fg_color=bg)
        self.badge_lbl.configure(text_color=fg, text=text)

    def update(self, res: ScanResult):
        self.set_status(res.kind, res.title)

        # --- show face photo if exists (for green/orange/red) ---
        if getattr(self, "_face_lbl", None) is not None:
            try:
                self._face_lbl.destroy()
            except Exception:
                pass
            self._face_lbl = None

        if res.student_id:
            self._face_lbl = attach_student_face_if_exists(
                self._row,
                res.student_id,
                before_widget=self._left,   # photo stays left of text
            )

        if self._face_lbl is not None:
            # pack "before=" is unreliable in CTk, so force correct order:
            self._left.pack_forget()
            self._left.pack(side="left", fill="x", expand=True)
      
        if res.student_id:
            self.name_lbl.configure(text=f"{res.student_name}  ·  ID {res.student_id}")
        else:
            self.name_lbl.configure(text="—")

        self.groups_lbl.configure(text=f"Groups: {res.groups}" if res.groups else "Groups: —")
        self.session_lbl.configure(text=res.session_text or "Session: —")
        self.pay_lbl.configure(text=res.payment_text or "Payment: —")


# ----------------------------
# Main Scanner
# ----------------------------

class QRSessionScanner:
    """
    Install once on the main window.
    QR scanners usually type quickly + press Enter.
    We detect "scanner-like speed" to avoid interfering with normal typing.
    """

    def __init__(
        self,
        root: ctk.CTk,
        buffer_minutes: int = 30,
        toast_ms: int = 1600,
        scanner_gap_seconds: float = 0.20,
        min_len: int = 3,
    ):
        self.root = root
        self.buffer_minutes = buffer_minutes
        self.toast_ms = toast_ms
        self.scanner_gap = scanner_gap_seconds
        self.min_len = min_len

        self._buf = ""
        self._last_t = 0.0

        self.card = _OverlayCard(root)

        # bind globally (background listener)
        root.bind_all("<KeyPress>", self._on_keypress, add="+")

    # ---------- sound ----------
    def _beep(self, kind: str):
        # Windows: nice beeps. Else: Tk bell fallback.
        try:
            import winsound  # type: ignore

            if kind == "green":
                winsound.Beep(1200, 90)
                winsound.Beep(1500, 90)
            elif kind == "orange":
                winsound.Beep(700, 140)
            elif kind == "red":
                winsound.Beep(5000, 250)
                winsound.Beep(250, 250)
            else:
                winsound.MessageBeep()
            return
        except Exception:
            pass

        try:
            self.root.bell()
        except Exception:
            pass

    # ---------- toast ----------
    def _toast(self, kind: str, title: str, subtitle: str):
        _Toast(self.root, kind, title, subtitle, ms=self.toast_ms)

    # ---------- key handling ----------
    def _on_keypress(self, event):
        t = time.perf_counter()
        gap = t - self._last_t
        self._last_t = t

        # if typing slowed down, reset (human typing)
        if gap > self.scanner_gap:
            self._buf = ""

        ks = getattr(event, "keysym", "")
        ch = getattr(event, "char", "")

        # finish scan
        if ks == "Return":
            code = (self._buf or "").strip()
            self._buf = ""

            if len(code) < self.min_len:
                return

            # extract student_id (first number run)
            m = re.search(r"\d+", code)
            if not m:
                # per your rule: corrupted/empty => do nothing (no UI)
                return

            student_id = int(m.group())
            self.process_student_id(student_id)
            return

        # ignore control keys
        if ks in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Tab", "Escape"):
            return
        if ks == "BackSpace":
            # scanner almost never uses backspace; keep it simple
            return

        # append printable characters
        if ch and ch.isprintable() and not ch.isspace():
            self._buf += ch

    # ---------- logic ----------
    def process_student_id(self, student_id: int):
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # student lookup
        try:
            stu = get_student(student_id)
        except NotFoundError:
            res = ScanResult(
                kind="red",
                title="Student not found",
                subtitle="This ID is missing/deleted.",
                student_id=student_id,
            )
            self.card.update(res)
            self._beep("red")
            self._toast("red", res.title, res.subtitle)
            return
        except Exception:
            # if DB is busy or something weird: show orange
            res = ScanResult(
                kind="orange",
                title="Could not read student",
                subtitle="DB error while reading student.",
                student_id=student_id,
            )
            self.card.update(res)
            self._beep("orange")
            self._toast("orange", res.title, res.subtitle)
            return

        # groups
        try:
            groups = _get_student_groups_with_ids(student_id)
        except Exception:
            groups = []

        group_ids = [gid for gid, _ in groups]
        group_names = [name for _, name in groups]
        groups_str = ", ".join(group_names)

        if not group_ids:
            res = ScanResult(
                kind="orange",
                title="No group",
                subtitle="Student has no group assigned.",
                student_name=stu.name,
                student_id=stu.id,
                groups=groups_str,
            )
            self.card.update(res)
            self._beep("orange")
            self._toast("orange", res.title, res.subtitle)
            return

        # today's sessions for those groups
        try:
            sessions = _get_todays_sessions_for_groups(group_ids, today)
        except sqlite3.OperationalError:
            res = ScanResult(
                kind="orange",
                title="Sessions not ready",
                subtitle="Sessions table missing or not initialized.",
                student_name=stu.name,
                student_id=stu.id,
                groups=groups_str,
            )
            self.card.update(res)
            self._beep("orange")
            self._toast("orange", res.title, res.subtitle)
            return
        except Exception:
            res = ScanResult(
                kind="orange",
                title="Could not read sessions",
                subtitle="DB error while reading sessions.",
                student_name=stu.name,
                student_id=stu.id,
                groups=groups_str,
            )
            self.card.update(res)
            self._beep("orange")
            self._toast("orange", res.title, res.subtitle)
            return

        # filter by time window (start - buffer -> end)
        buf = timedelta(minutes=self.buffer_minutes)
        candidates: list[dict] = []
        for s in sessions:
            try:
                start_dt = _dt_from(s["date"], s["start_time"])
                end_dt = _dt_from(s["date"], s["end_time"])
                if end_dt <= start_dt:
                    end_dt = end_dt + timedelta(days=1)  # safety for weird data
            except Exception:
                continue

            if (start_dt - buf) <= now <= end_dt:
                candidates.append(s)

        if not candidates:
            res = ScanResult(
                kind="orange",
                title="Wrong time",
                subtitle="No session window right now.",
                student_name=stu.name,
                student_id=stu.id,
                groups=groups_str,
                session_text=f"Session: none now (buffer {self.buffer_minutes} min)",
            )
            self.card.update(res)
            self._beep("orange")
            self._toast("orange", res.title, res.subtitle)
            return

        # Payment check is per session month (all candidates are today => same month)
        sy = int(candidates[0]["date"][:4])
        sm = int(candidates[0]["date"][5:7])

        pay = None
        try:
            pay = get_payment(student_id, sy, sm)
        except Exception:
            pay = None

        paid_ok = (pay is not None and getattr(pay, "paid", "") == "paid")
        pay_txt = f"Payment: {'PAID' if paid_ok else 'UNPAID'} for {sy}-{sm:02d}"

        if not paid_ok:
            res = ScanResult(
                kind="red",
                title="Unpaid",
                subtitle=f"Not paid for {sy}-{sm:02d}. حضور غير مسموح.",
                student_name=stu.name,
                student_id=stu.id,
                groups=groups_str,
                session_text=f"Session: {today} (in window)",
                payment_text=pay_txt,
            )
            self.card.update(res)
            self._beep("red")
            self._toast("red", res.title, res.subtitle)
            return

        # If already present for ALL candidate sessions => green "already"
        already_all = True
        for s in candidates:
            if not _attendance_exists(int(s["id"]), student_id):
                already_all = False
                break

        # Mark present for all candidate sessions (you said: "mark all")
        if not already_all:
            try:
                _mark_present([int(s["id"]) for s in candidates], student_id)
            except Exception:
                res = ScanResult(
                    kind="orange",
                    title="Could not mark present",
                    subtitle="DB error while writing attendance.",
                    student_name=stu.name,
                    student_id=stu.id,
                    groups=groups_str,
                    payment_text=pay_txt,
                )
                self.card.update(res)
                self._beep("orange")
                self._toast("orange", res.title, res.subtitle)
                return

        # Build session display (show the first + count)
        first = candidates[0]
        gname_map = {gid: name for gid, name in groups}
        gname = gname_map.get(int(first["group_id"]), f"Group {first['group_id']}")
        count = len(candidates)
        sess_txt = (
            f"Session: {gname} · {first['date']} {first['start_time']}–{first['end_time']}"
            + (f"  (+{count-1} more)" if count > 1 else "")
        )

        if already_all:
            res = ScanResult(
                kind="green",
                title="Already checked-in",
                subtitle="Duplicate scan ignored.",
                student_name=stu.name,
                student_id=stu.id,
                groups=groups_str,
                session_text=sess_txt,
                payment_text=pay_txt,
            )
        else:
            res = ScanResult(
                kind="green",
                title=" حاضر ✅",
                subtitle="Marked present.",
                student_name=stu.name,
                student_id=stu.id,
                groups=groups_str,
                session_text=sess_txt,
                payment_text=pay_txt,
            )

        self.card.update(res)
        self._beep("green")
        self._toast("green", res.title, res.subtitle)


# ----------------------------
# Public install function
# ----------------------------

def install_qr_scanner(root: ctk.CTk, buffer_minutes: int = 30) -> QRSessionScanner:
    """
    Call this once after you create your main CTk window.
    Example:
        import qr_session_reader
        qr_session_reader.install_qr_scanner(app)

    Returns the scanner instance (keep it if you want).
    """
    return QRSessionScanner(root=root, buffer_minutes=buffer_minutes)
