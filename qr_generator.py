"""
qr_code_generator_step2_numbers.py — Step 2 (place base card + print numbers)

What changed from Step 1:
- We DO print a number for each card.
- We DO allow partial last page:
  If the range is not divisible by 10, the remaining slots on the last sheet are left EMPTY (no card).

Still NOT doing QR overlay yet — that's Step 3.

How to set coordinates for the number:
- NUMBER_XY_MM is (x_mm, y_mm) measured from the *bottom-left corner of the card*.
- Start with the default and tweak, print one sheet, adjust again.
- Turn DEBUG_GUIDES = True to draw a red border + green crosshair at the number point.

Run:
    python qr_code_generator_step2_numbers.py
"""

from __future__ import annotations

import os
from tkinter import Tk, messagebox, simpledialog

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
CARD_MM = (86.0, 54.0)          # 8.6×5.4 cm (LANDSCAPE)
COLS, ROWS = 2, 5               # 10 slots per page

# Gap between cards (you said you want to increase this)
GAP_MM = 7.0                    # try 3 or 4

# Shift ONLY the base cards (mm). Negative x => left.
CARD_OFFSET_MM = (-90.0, 0.0)     # e.g. (-3.0, 0.0)

# Number config (Step 2)
DISPLAY_DIGITS = 4
FONT_NAME = "Helvetica-Bold"
FONT_SIZE_PT = 14

# >>> This is what you will tune <<<
NUMBER_XY_MM = (78.0, 27.0)

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
QR_BOX_MM = (36.5, 8.6, 36.95)   # start guess: you will adjust

# QR colors
QR_INVERT = True  # True = white QR on blue background
QR_BG_COLOR = colors.HexColor("#264878") 
QR_FG_COLOR = colors.white

# QR quality
QR_ERROR_LEVEL = "M"      # L/M/Q/H (M good default)
QR_BORDER_MODULES = 4     # quiet zone (keep 4)


def ask_range_popup() -> tuple[int, int] | None:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    start = simpledialog.askinteger("QR Cards", "From what number? (start)", parent=root)
    if start is None:
        root.destroy()
        return None

    end = simpledialog.askinteger("QR Cards", "To what number? (end)", parent=root)
    if end is None:
        root.destroy()
        return None

    if end < start:
        messagebox.showwarning("QR Cards", "End is smaller than start. I will swap them.")
        start, end = end, start

    root.destroy()
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

def _compute_centered_margins_mm(page_mm=PAGE_MM, card_mm=CARD_MM, cols=COLS, rows=ROWS, gap_mm=GAP_MM):
    page_w, page_h = page_mm
    card_w, card_h = card_mm
    grid_w = cols * card_w + (cols - 1) * gap_mm
    grid_h = rows * card_h + (rows - 1) * gap_mm
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
    x_mm = margin_x_mm + col * (card_w_mm + GAP_MM)
    y_mm = page_h_mm - margin_y_mm - card_h_mm - r * (card_h_mm + GAP_MM)
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


if __name__ == "__main__":
    main()