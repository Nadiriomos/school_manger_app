# receipt_printer.py
from __future__ import annotations

import calendar
import errno
import queue
import threading
import time
from typing import Optional
from datetime import datetime

from DB import get_student, get_student_groups

try:
    from escpos.printer import Usb, Network, Win32Raw
except Exception:
    Usb = Network = Win32Raw = None


# -----------------------------
# CONFIG (edit these)
# -----------------------------

# modes:
#   "usb"      -> Linux USB direct (recommended for your dev)
#   "network"  -> IP printer (optional)
#   "win32raw" -> Windows installed printer name (for customer Windows 7)
PRINTER_MODE = "usb"

# USB IDs (from your logs: 1fc9:2016)
USB_VENDOR_ID = 0x1FC9
USB_PRODUCT_ID = 0x2016

# Network (only if you ever use it)
PRINTER_IP = "192.168.1.50"
PRINTER_PORT = 9100

# Windows (only if PRINTER_MODE="win32raw")
WINDOWS_PRINTER_NAME = "XP-Q80H"

# Receipt text labels (easy to change, Arabic allowed)
SCHOOL_NAME = "El Najah School"
PLACE_LINE = ""  # optional second line
PAID_LABEL = "PAID"  # you can change to Arabic: "مدفوع"

# If you later want different month names (e.g. French/Arabic),
# you can override this list (index 1..12 used).
MONTH_NAMES = list(calendar.month_name)  # ["", "January", ..., "December"]


# -----------------------------
# Helpers you asked for
# -----------------------------

def set_school_name(name: str) -> None:
    """Call this from your main app to switch to Arabic or anything else."""
    global SCHOOL_NAME
    SCHOOL_NAME = name


def set_place_line(line: str) -> None:
    global PLACE_LINE
    PLACE_LINE = line


def set_paid_label(text: str) -> None:
    global PAID_LABEL
    PAID_LABEL = text


def fmt_student_id(student_id: int) -> str:
    """1 -> 0001"""
    return f"{int(student_id):04d}"


def month_label(year: int, month: int) -> str:
    """2026, 2 -> 'February 2026'"""
    m = int(month)
    y = int(year)
    if not (1 <= m <= 12):
        return f"{y}-{m:02d}"
    return f"{MONTH_NAMES[m]} {y}"


def payment_time_label() -> str:
    # Example: 14:07
    return datetime.now().strftime("%H:%M")

# -----------------------------
# Printer backend
# -----------------------------

def _open_printer():
    if PRINTER_MODE == "usb":
        if Usb is None:
            raise RuntimeError("python-escpos not installed or Usb backend missing.")
        return Usb(USB_VENDOR_ID, USB_PRODUCT_ID)

    if PRINTER_MODE == "network":
        if Network is None:
            raise RuntimeError("python-escpos not installed or Network backend missing.")
        return Network(PRINTER_IP, port=PRINTER_PORT, timeout=5)

    if PRINTER_MODE == "win32raw":
        if Win32Raw is None:
            raise RuntimeError("Win32Raw not available (install pywin32 on Windows).")
        return Win32Raw(WINDOWS_PRINTER_NAME)

    raise RuntimeError(f"Unknown PRINTER_MODE: {PRINTER_MODE}")


# -----------------------------
# Print queue (single worker)
# -----------------------------

_print_q: "queue.Queue[dict]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()

# One printer handle reused by the worker (important for USB stability)
_printer_handle = None
_printer_lock = threading.Lock()


def _print_receipt(p, job: dict) -> None:
    student_id = int(job["student_id"])
    year = int(job["year"])
    month = int(job["month"])
    payment_date = str(job["payment_date"])

    stu = get_student(student_id)
    groups = get_student_groups(student_id)
    group_str = ", ".join(groups) if groups else "—"

    sid = fmt_student_id(student_id)
    mtxt = month_label(year, month)

    # --- RECEIPT (simple text ESC/POS) ---
    # NOTE: Arabic may not shape correctly in text mode on many printers.
    # If Arabic looks broken, the fix is: render as image and print raster.

    p.set(align="center", bold=True, width=2, height=2)
    p.text(f"{SCHOOL_NAME}\n")

    p.set(align="center", bold=False, width=1, height=1)
    if PLACE_LINE:
        p.text(f"{PLACE_LINE}\n")
    p.text("--------------------------------\n")

    # Content (ID UNDER THE NAME as you requested)
    p.set(align="left", bold=True, width=2, height=2)
    p.text(f"Student: {stu.name}\n")
    p.text(f"ID:      {sid}\n")          # <- under the name
    p.text(f"Group:   {group_str}\n")
    p.text(f"Month:   {mtxt}\n")         # <- month words
    p.text(f"Date:    {payment_date}\n")
    p.text(f"Time:    {payment_time_label()}\n")

    p.text("--------------------------------\n")
    p.set(align="center", bold=True)
    p.text(f"{PAID_LABEL}\n\n")

    # Cut paper (some printers need feed before cut; cut() usually handles it)
    p.cut()


def _worker_loop() -> None:
    global _printer_handle

    while True:
        job = _print_q.get()
        try:
            # Open printer once (and reopen on failure)
            if _printer_handle is None:
                _printer_handle = _open_with_retry()

            # Ensure single access to the device handle
            with _printer_lock:
                _print_with_retry(_printer_handle, job)

        except Exception as e:
            print("RECEIPT PRINT ERROR:", e)

            # If device handle got into a bad state, drop it and reopen next time
            try:
                if _printer_handle is not None:
                    _printer_handle.close()
            except Exception:
                pass
            _printer_handle = None

        finally:
            _print_q.task_done()


def _open_with_retry(max_tries: int = 8):
    # Busy often happens if CUPS or another process briefly holds the interface.
    # We retry a few times with backoff.
    last_err = None
    for i in range(max_tries):
        try:
            return _open_printer()
        except OSError as e:
            last_err = e
            if getattr(e, "errno", None) in (errno.EBUSY, errno.EACCES):
                time.sleep(0.25 * (i + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(0.25 * (i + 1))
    raise RuntimeError(f"Could not open printer after retries: {last_err}")


def _print_with_retry(p, job: dict, max_tries: int = 6) -> None:
    last_err = None
    for i in range(max_tries):
        try:
            _print_receipt(p, job)
            return
        except OSError as e:
            last_err = e
            if getattr(e, "errno", None) == errno.EBUSY:
                time.sleep(0.2 * (i + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            raise
    raise RuntimeError(f"Print failed after retries: {last_err}")


def start_worker_once() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, daemon=True)
        t.start()
        _worker_started = True


# -----------------------------
# Hook entry point (DB calls this)
# -----------------------------

def on_payment_became_paid(student_id: int, year: int, month: int, payment_date: str) -> None:
    """
    DB hook: called only when NOT 'paid' -> 'paid' transition happens.
    """
    start_worker_once()
    _print_q.put(
        {
            "student_id": student_id,
            "year": year,
            "month": month,
            "payment_date": payment_date,
        }
    )


# -----------------------------
# Optional quick test helper
# -----------------------------

def print_test(student_id: int, year: int, month: int, payment_date: Optional[str] = None) -> None:
    """Manual test print from code without changing DB."""
    if payment_date is None:
        # Keep it simple: YYYY-MM-DD
        payment_date = time.strftime("%Y-%m-%d")
    on_payment_became_paid(student_id, year, month, payment_date)
