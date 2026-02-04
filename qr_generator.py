from __future__ import annotations

import os
from tkinter import Tk, messagebox, simpledialog
from tkinter import Tk, messagebox, simpledialog, Toplevel, Button, Label
import re
from datetime import datetime

from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

# ---------------------------------------------------------------------
# Layout config (20×30 cm, 10-up)
# ---------------------------------------------------------------------
PAGE_MM = (200.0, 300.0)        # 20×30 cm
CARD_MM = (90.0, 58.0)          # 8.6×5.4 cm (LANDSCAPE)
COLS, ROWS = 2, 5               # 10 slots per page

# Gap between cards (you said you want to increase this)
GAP_X_MM = 7.0   # keep gap between columns
GAP_Y_MM = 0.0   # remove gap between rows

# Shift ONLY the base cards (mm). Negative x => left.
CARD_OFFSET_MM = (-90.0, 0.0)     # e.g. (-3.0, 0.0)

# Number config (Step 2)
DISPLAY_DIGITS = 4
FONT_NAME = "Helvetica-Bold"
FONT_SIZE_PT = 14

# >>> This is what you will tune <<<
NUMBER_XY_MM = (86.0, 27.0)

# Shift the entire grid (mm). Use this to nudge everything left/right/up/down.
# Example: (-3.0, 0.0) moves the whole layout 3mm to the LEFT.
CARD_OFFSET_MM = (-86.0, 0.0)

# Rotate the printed number (degrees). Example: 90 or -90.
NUMBER_ROTATE_DEG = 90

# Debug overlay to help you find exact coordinates
DEBUG_GUIDES = False

# Image fit: "contain" (no distortion) or "stretch"
FIT_MODE = "contain"

ANCHOR_NUMBERS_TO_CARDS = False

# --- QR overlay toggles ---
PRINT_QR = True

# QR placement INSIDE THE SLOT GRID (NOT tied to card offset)
# (x_mm, y_mm, size_mm) measured from the *slot's* bottom-left corner
QR_BOX_MM = (43, 11, 36.95)   # start guess: you will adjust

# QR colors
QR_INVERT = True  # True = white QR on blue background
QR_BG_COLOR = colors.HexColor("#264878") 
QR_FG_COLOR = colors.white

# QR quality
QR_ERROR_LEVEL = "M"      # L/M/Q/H (M good default)
QR_BORDER_MODULES = 4     # quiet zone (keep 4)


def ask_range_popup(parent=None) -> tuple[int, int] | None:
    temp_root = None

    # If called from app menu, parent will be your CTk root (good).
    # If called standalone, we create a temporary root.
    if parent is None:
        temp_root = Tk()
        temp_root.withdraw()
        try:
            temp_root.attributes("-topmost", True)
        except Exception:
            pass
        parent = temp_root

    start = simpledialog.askinteger("QR Cards", "From what number? (start)", parent=parent)
    if start is None:
        if temp_root: temp_root.destroy()
        return None

    end = simpledialog.askinteger("QR Cards", "To what number? (end)", parent=parent)
    if end is None:
        if temp_root: temp_root.destroy()
        return None

    if end < start:
        messagebox.showwarning("QR Cards", "End is smaller than start. I will swap them.", parent=parent)
        start, end = end, start

    if temp_root:
        temp_root.destroy()
    return start, end

def draw_qr_on_pdf(c, data: str, x_pt: float, y_pt: float, size_pt: float):
    """
    Draw QR at (x_pt, y_pt) with square size size_pt (points).
    Supports inverted style (white QR on blue background).
    """
    # background (for inverted style)
    if QR_INVERT:
        c.setFillColor(QR_BG_COLOR)
        c.rect(x_pt, y_pt, size_pt, size_pt, stroke=0, fill=1)
        module_color = QR_FG_COLOR
    else:
        module_color = colors.black

    w = qr.QrCodeWidget(data, barLevel=QR_ERROR_LEVEL)
    w.barBorder = QR_BORDER_MODULES
    w.barFillColor = module_color
    w.barStrokeColor = module_color
    w.barStrokeWidth = 0

    # Scale by scaling the Drawing (NOT the widget)
    x0, y0, x1, y1 = w.getBounds()
    w_size = (x1 - x0)  # square
    scale = size_pt / w_size

    d = Drawing(size_pt, size_pt)
    d.add(w)
    d.scale(scale, scale)

    renderPDF.draw(d, c, x_pt, y_pt)

def _compute_centered_margins_mm(page_mm=PAGE_MM, card_mm=CARD_MM, cols=COLS, rows=ROWS, GAP_X_M=GAP_X_MM, GAP_Y_MM=GAP_Y_MM):
    page_w, page_h = page_mm
    card_w, card_h = card_mm
    grid_w = cols * card_w + (cols - 1) * GAP_X_MM
    grid_h = rows * card_h + (rows - 1) * GAP_Y_MM
    if grid_w > page_w or grid_h > page_h:
        raise ValueError(
            f"Grid doesn't fit: grid={grid_w:.1f}x{grid_h:.1f}mm "
            f"page={page_w:.1f}x{page_h:.1f}mm"
        )
    return (page_w - grid_w) / 2.0, (page_h - grid_h) / 2.0


def _slot_xy_mm(r: int, col: int, margin_x_mm: float, margin_y_mm: float) -> tuple[float, float]:
    """Return bottom-left of slot in mm (no offsets)."""
    page_w_mm, page_h_mm = PAGE_MM
    card_w_mm, card_h_mm = CARD_MM
    x_mm = margin_x_mm + col * (card_w_mm + GAP_X_MM)
    y_mm = page_h_mm - margin_y_mm - card_h_mm - r * (card_h_mm + GAP_Y_MM)
    return x_mm, y_mm


def _draw_card_image(c: canvas.Canvas, img: ImageReader, x: float, y: float, w: float, h: float, preserve: bool):
    """
    Draw image into a card box. Auto-rotates 90° if that matches the card aspect better.
    (Helps when base_card.jpg is portrait but our slot is landscape.)
    """
    iw, ih = img.getSize()
    card_ar = w / h
    ar0 = iw / ih
    ar_rot = ih / iw
    rotate = abs(ar_rot - card_ar) < abs(ar0 - card_ar)

    if not rotate:
        c.drawImage(img, x, y, width=w, height=h, preserveAspectRatio=preserve, anchor="c", mask="auto")
        return

    c.saveState()
    c.translate(x + w, y)
    c.rotate(90)
    c.drawImage(img, 0, -w, width=h, height=w, preserveAspectRatio=preserve, anchor="c", mask="auto")
    c.restoreState()


def _draw_rotated_centered_text(c: canvas.Canvas, x: float, y: float, text: str, deg: float):
    if deg:
        c.saveState()
        c.translate(x, y)
        c.rotate(deg)
        c.drawCentredString(0, 0, text)
        c.restoreState()
    else:
        c.drawCentredString(x, y, text)


def generate_pdf(base_card_image_path: str, output_pdf_path: str, start: int, end: int) -> str:
    if not os.path.exists(base_card_image_path):
        raise FileNotFoundError(base_card_image_path)

    ids = [str(n) for n in range(start, end + 1)]
    if not ids:
        raise ValueError("Empty range.")

    per_page = COLS * ROWS
    pages = (len(ids) + per_page - 1) // per_page  # partial last page allowed

    margin_x_mm, margin_y_mm = _compute_centered_margins_mm()

    page_w_mm, page_h_mm = PAGE_MM
    card_w_mm, card_h_mm = CARD_MM

    c = canvas.Canvas(output_pdf_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    img = ImageReader(base_card_image_path)
    preserve = (FIT_MODE.lower() != "stretch")

    idx = 0
    for _p in range(pages):
        for r in range(ROWS):
            for col in range(COLS):
                if idx >= len(ids):
                    # Leave this slot empty (no card, no number)
                    continue

                slot_x_mm, slot_y_mm = _slot_xy_mm(r, col, margin_x_mm, margin_y_mm)

                # --- CARD position (slot + CARD_OFFSET) ---
                dx_mm, dy_mm = CARD_OFFSET_MM
                card_x_mm = slot_x_mm + dx_mm
                card_y_mm = slot_y_mm + dy_mm

                x = card_x_mm * mm
                y = card_y_mm * mm
                w = card_w_mm * mm
                h = card_h_mm * mm

                _draw_card_image(c, img, x, y, w, h, preserve=preserve)

                # --- NUMBER position ---
                sid = ids[idx]
                disp = sid[-DISPLAY_DIGITS:].zfill(DISPLAY_DIGITS)

                nx_in_mm, ny_in_mm = NUMBER_XY_MM

                if ANCHOR_NUMBERS_TO_CARDS:
                    # numbers follow the shifted cards (final mode)
                    nx_mm = card_x_mm + nx_in_mm
                    ny_mm = card_y_mm + ny_in_mm
                else:
                    # numbers stay on the page grid (calibration mode)
                    nx_mm = slot_x_mm + nx_in_mm
                    ny_mm = slot_y_mm + ny_in_mm

                if PRINT_QR:
                    qx_mm, qy_mm, qs_mm = QR_BOX_MM

                    # IMPORTANT: anchored to SLOT (NOT card offset)
                    qx = (slot_x_mm + qx_mm) * mm
                    qy = (slot_y_mm + qy_mm) * mm
                    qs = qs_mm * mm

                    draw_qr_on_pdf(c, sid, qx, qy, qs)

                nx = nx_mm * mm
                ny = ny_mm * mm

                c.setFont(FONT_NAME, FONT_SIZE_PT)
                c.setFillColor(colors.black)
                _draw_rotated_centered_text(c, nx, ny, disp, NUMBER_ROTATE_DEG)

                if DEBUG_GUIDES:
                    # slot border (blue) shows the "true grid" without offsets
                    c.setStrokeColor(colors.blue)
                    c.setLineWidth(0.4)
                    c.rect(slot_x_mm * mm, slot_y_mm * mm, w, h, stroke=1, fill=0)

                    # card border (red) shows where the image is drawn
                    c.setStrokeColor(colors.red)
                    c.setLineWidth(0.6)
                    c.rect(x, y, w, h, stroke=1, fill=0)

                    # number crosshair (green)
                    c.setStrokeColor(colors.green)
                    c.setLineWidth(0.6)
                    c.line(nx - 6, ny, nx + 6, ny)
                    c.line(nx, ny - 6, nx, ny + 6)

                    c.setFillColor(colors.red)
                    c.setFont("Helvetica", 7)
                    c.drawString((slot_x_mm * mm) + 2, (slot_y_mm * mm) + 2, f"slot({slot_x_mm:.1f},{slot_y_mm:.1f})")
                    c.drawString((slot_x_mm * mm) + 2, (slot_y_mm * mm) + 11, f"card_off({dx_mm:.1f},{dy_mm:.1f})")
                    c.drawString((slot_x_mm * mm) + 2, (slot_y_mm * mm) + 20, f"num@({nx_mm:.1f},{ny_mm:.1f})")

                idx += 1

        c.showPage()

    c.save()
    return output_pdf_path


def main():
    rng = ask_range_popup()
    if rng is None:
        return
    start, end = rng

    here = os.path.dirname(__file__)
    base = os.path.join(here, "base_card.jpg")
    out = os.path.join(here, f"cards_20x30_10up_NUMBERS_{start}_to_{end}.pdf")

    try:
        generate_pdf(base, out, start, end)
    except Exception as e:
        root = Tk(); root.withdraw()
        messagebox.showerror("QR Cards", f"Error:\n{e}")
        root.destroy()
        return

    total = end - start + 1
    per_page = COLS * ROWS
    pages = (total + per_page - 1) // per_page
    blanks = (per_page - (total % per_page)) % per_page

    root = Tk(); root.withdraw()
    msg = (
        f"Saved:\n{out}\n\n"
        f"Total cards: {total}\n"
        f"Pages: {pages}\n"
        f"Empty slots on last page: {blanks}\n\n"
        f"Tune gaps: GAP_MM\n"
        f"Move ONLY cards: CARD_OFFSET_MM\n"
        f"Move numbers: NUMBER_XY_MM\n"
        f"Rotate numbers: NUMBER_ROTATE_DEG\n"
        f"Anchor numbers to cards: ANCHOR_NUMBERS_TO_CARDS\n"
        f"Debug overlay: DEBUG_GUIDES"
    )
    messagebox.showinfo("QR Cards", msg)
    root.destroy()

def open_qr_generator(parent=None):
    rng = ask_range_popup(parent)
    if rng is None:
        return
    start, end = rng

    here = os.path.dirname(__file__)
    base = os.path.join(here, "base_card.jpg")
    out = os.path.join(here, f"cards_{start}_to_{end}.pdf")

    try:
        generate_pdf(base, out, start, end)
    except Exception as e:
        messagebox.showerror("QR Cards", f"Error:\n{e}", parent=parent)
        return

    messagebox.showinfo("QR Cards", f"Saved:\n{out}", parent=parent)


def generate_pdf_for_ids(base_card_image_path: str, output_pdf_path: str, ids_list: list[int]) -> str:
    # reuse your existing generator logic by converting to strings
    ids = [str(int(n)) for n in sorted(set(ids_list))]
    if not ids:
        raise ValueError("No IDs to generate.")

    # ---- copy of generate_pdf BUT replacing the range-created ids with this `ids` ----
    if not os.path.exists(base_card_image_path):
        raise FileNotFoundError(base_card_image_path)

    per_page = COLS * ROWS
    pages = (len(ids) + per_page - 1) // per_page

    margin_x_mm, margin_y_mm = _compute_centered_margins_mm()
    page_w_mm, page_h_mm = PAGE_MM
    card_w_mm, card_h_mm = CARD_MM

    c = canvas.Canvas(output_pdf_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    img = ImageReader(base_card_image_path)
    preserve = (FIT_MODE.lower() != "stretch")

    idx = 0
    for _p in range(pages):
        for r in range(ROWS):
            for col in range(COLS):
                if idx >= len(ids):
                    continue

                slot_x_mm, slot_y_mm = _slot_xy_mm(r, col, margin_x_mm, margin_y_mm)

                dx_mm, dy_mm = CARD_OFFSET_MM
                card_x_mm = slot_x_mm + dx_mm
                card_y_mm = slot_y_mm + dy_mm

                x = card_x_mm * mm
                y = card_y_mm * mm
                w = card_w_mm * mm
                h = card_h_mm * mm

                _draw_card_image(c, img, x, y, w, h, preserve=preserve)

                sid = ids[idx]
                disp = sid[-DISPLAY_DIGITS:].zfill(DISPLAY_DIGITS)

                nx_in_mm, ny_in_mm = NUMBER_XY_MM
                if ANCHOR_NUMBERS_TO_CARDS:
                    nx_mm = card_x_mm + nx_in_mm
                    ny_mm = card_y_mm + ny_in_mm
                else:
                    nx_mm = slot_x_mm + nx_in_mm
                    ny_mm = slot_y_mm + ny_in_mm

                if PRINT_QR:
                    qx_mm, qy_mm, qs_mm = QR_BOX_MM
                    qx = (slot_x_mm + qx_mm) * mm
                    qy = (slot_y_mm + qy_mm) * mm
                    qs = qs_mm * mm
                    draw_qr_on_pdf(c, sid, qx, qy, qs)

                c.setFont(FONT_NAME, FONT_SIZE_PT)
                c.setFillColor(colors.black)
                _draw_rotated_centered_text(c, nx_mm * mm, ny_mm * mm, disp, NUMBER_ROTATE_DEG)

                idx += 1

        c.showPage()

    c.save()
    return output_pdf_path


def open_qr_counter(parent=None):
    # 1) ask expected range
    rng = ask_range_popup(parent)
    if rng is None:
        return
    start, end = rng
    expected = set(range(start, end + 1))

    # 2) build popup
    top = Toplevel(parent)
    top.title("Check How Many You Have")
    top.geometry("520x260")
    try:
        top.attributes("-topmost", True)
    except Exception:
        pass

    scanned: set[int] = set()
    total_scans = 0
    dup_scans = 0
    buf = ""
    last_t = 0.0

    info = Label(top, text=f"Expected range: {start} → {end}\nScan cards now (scanner + Enter).", justify="left")
    info.pack(anchor="w", padx=12, pady=(12, 6))

    stat = Label(top, text="Scanned: 0 | Missing: ? | Duplicates: 0 | Last: —", justify="left")
    stat.pack(anchor="w", padx=12, pady=(0, 10))

    result = Label(top, text="", justify="left")
    result.pack(anchor="w", padx=12, pady=(0, 10))

    def refresh(last="—"):
        missing = len(expected) - len(scanned)
        stat.configure(text=f"Scanned: {len(scanned)} | Missing: {missing} | Duplicates: {dup_scans} | Last: {last}")

    def do_count():
        missing_list = sorted(expected - scanned)
        if not missing_list:
            result.configure(text="✅ No missing cards.")
            return
        # show a compact preview (don’t spam UI)
        preview = ", ".join(f"{n:04d}" for n in missing_list[:40])
        more = "" if len(missing_list) <= 40 else f" ... (+{len(missing_list)-40} more)"
        result.configure(text=f"Missing ({len(missing_list)}): {preview}{more}")

    def do_generate_lost():
        missing_list = sorted(expected - scanned)
        if not missing_list:
            messagebox.showinfo("Lost Cards", "No missing cards to generate.", parent=top)
            return

        here = os.path.dirname(__file__)
        base = os.path.join(here, "base_card.jpg")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(here, f"lost_cards_{start}_to_{end}_{stamp}.pdf")

        try:
            generate_pdf_for_ids(base, out, missing_list)
        except Exception as e:
            messagebox.showerror("Lost Cards", f"Error:\n{e}", parent=top)
            return

        messagebox.showinfo("Lost Cards", f"Saved:\n{out}", parent=top)

    def do_reset():
        nonlocal total_scans, dup_scans, buf
        scanned.clear()
        total_scans = 0
        dup_scans = 0
        buf = ""
        result.configure(text="")
        refresh()


    # 3) key capture (prevents qr_code.py global scanner)
    import time as _time
    _scanner_gap = 0.20

    def on_key(e):
        nonlocal buf, last_t, total_scans, dup_scans
        t = _time.perf_counter()
        if t - last_t > _scanner_gap:
            buf = ""
        last_t = t

        ks = getattr(e, "keysym", "")
        ch = getattr(e, "char", "")

        if ks == "Return":
            code = buf.strip()
            buf = ""
            m = re.search(r"\d+", code)
            if not m:
                refresh(last="—")
                return "break"

            n = int(m.group())          # IMPORTANT: strips leading zeros automatically
            disp = f"{n:04d}"           # display as 4 digits

            total_scans += 1
            if n in scanned:
                dup_scans += 1
                top.bell()  # 🔔 small system beep
                result.configure(text=f"⚠️ Duplicate scan: {disp}")
                # optional: clear warning after a moment
                top.after(800, lambda: result.configure(text=""))
            else:
                scanned.add(n)

            refresh(last=disp)
            return "break"


        # ignore controls
        if ks in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Tab", "Escape"):
            if ks == "Escape":
                top.destroy()
            return "break"

        if ch and ch.isprintable() and not ch.isspace():
            buf += ch

        return "break"  # IMPORTANT: stops propagation to root.bind_all

    top.bind("<KeyPress>", on_key)

    # buttons
    row = Label(top, text="")
    row.pack()

    Button(top, text="Count", command=do_count).pack(side="left", padx=10, pady=10)
    Button(top, text="Generate lost cards", command=do_generate_lost).pack(side="left", padx=10, pady=10)
    Button(top, text="Reset", command=do_reset).pack(side="left", padx=10, pady=10)
    Button(top, text="Close", command=top.destroy).pack(side="right", padx=10, pady=10)

    # modal behavior
    top.grab_set()
    top.focus_force()
    refresh()


if __name__ == "__main__":
    main()