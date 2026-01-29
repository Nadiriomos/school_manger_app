from __future__ import annotations

import os
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Any

import customtkinter as ctk
from tkinter import messagebox

# Optional deps: camera + image encode/resize
try:
    import cv2  # type: ignore
except Exception:
    cv2 = None

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None


@dataclass
class PendingPhoto:
    jpg_bytes: bytes
    thumb_pil: "Image.Image"  # for preview only


class AddStudentPhotoPlugin:
    """
    Add Student photo extension (MVP)
    - Captures a face photo from webcam into memory
    - Blocks saving if a photo exists but ID is missing/invalid
    - Saves JPG as photos/<year>/<student_id>.jpg after host saves student
    """

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        get_student_id: Callable[[], Any],
        *,
        year_fn: Callable[[], int] | None = None,
        base_dir: str | None = None,
        camera_index: int = 0,
        preview_size: tuple[int, int] = (140, 140),
        capture_quality: int = 90,
    ):
        self.parent = parent
        self.get_student_id = get_student_id
        self.year_fn = year_fn or (lambda: datetime.now().year)
        self.base_dir = base_dir or os.path.abspath(".")
        self.camera_index = camera_index
        self.preview_size = preview_size
        self.capture_quality = max(60, min(int(capture_quality), 98))

        self.pending: Optional[PendingPhoto] = None
        self._preview_img = None  # keep reference (avoid GC)

        # UI
        self._build_ui(parent)

    # ---------------- UI ----------------

    def _build_ui(self, parent: ctk.CTkBaseClass):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", pady=(8, 0))

        # Header (collapsible)
        header = ctk.CTkFrame(container, fg_color="transparent")
        header.pack(fill="x")

        self._collapsed = ctk.BooleanVar(value=False)
        self._toggle_btn = ctk.CTkButton(
            header,
            text="Hide Photo",
            width=110,
            command=self._toggle,
        )
        self._toggle_btn.pack(side="right", padx=(6, 0))

        ctk.CTkLabel(header, text="Photo", font=("Arial", 14, "bold")).pack(side="left")

        # Body
        self.body = ctk.CTkFrame(container, fg_color="transparent")
        self.body.pack(fill="x", pady=(6, 0))

        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x")

        # Preview box
        self.preview_box = ctk.CTkFrame(row, width=self.preview_size[0], height=self.preview_size[1], corner_radius=12)
        self.preview_box.pack_propagate(False)
        self.preview_box.pack(side="left", padx=(0, 12))

        self.preview_lbl = ctk.CTkLabel(self.preview_box, text="No photo", font=("Arial", 12))
        self.preview_lbl.pack(expand=True)

        # Buttons
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="left", fill="x", expand=True)

        self.take_btn = ctk.CTkButton(btns, text="Take Photo", command=self.open_camera_popup)
        self.take_btn.pack(anchor="w", pady=(0, 8))

        self.retake_btn = ctk.CTkButton(btns, text="Retake", command=self.open_camera_popup, state="disabled")
        self.retake_btn.pack(anchor="w")

        self.status_lbl = ctk.CTkLabel(self.body, text="", font=("Arial", 12))
        self.status_lbl.pack(anchor="w", pady=(8, 0))

    def _toggle(self):
        collapsed = not self._collapsed.get()
        self._collapsed.set(collapsed)
        if collapsed:
            self.body.pack_forget()
            self._toggle_btn.configure(text="Show Photo")
        else:
            self.body.pack(fill="x", pady=(6, 0))
            self._toggle_btn.configure(text="Hide Photo")

    # ---------------- Camera popup ----------------

    def open_camera_popup(self):
        if cv2 is None or Image is None:
            messagebox.showerror(
                "Camera not available",
                "Missing dependency. Install:\n\npip install opencv-python pillow",
            )
            return

        self._cam_win = ctk.CTkToplevel(self.parent.winfo_toplevel())
        self._cam_win.title("Take Photo")
        self._cam_win.geometry("720x520")
        try:
            self._cam_win.grab_set()
        except Exception:
            pass

        # Video label (full background)
        self._video_lbl = ctk.CTkLabel(self._cam_win, text="")
        self._video_lbl.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Bottom-center capture button
        self._capture_btn = ctk.CTkButton(self._cam_win, text="Capture", width=140, command=self._capture_frame)
        self._capture_btn.place(relx=0.5, rely=0.95, anchor="s")

        self._cam_win.protocol("WM_DELETE_WINDOW", self._close_camera)

        # Open camera
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            self._close_camera()
            messagebox.showerror("Camera error", "Could not open the camera.")
            return

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 580)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 420)

        self._last_frame_bgr = None
        self._video_img_ref = None
        self._running = True
        self._tick_video()

    def _tick_video(self):
        if not getattr(self, "_running", False):
            return

        ok, frame = self._cap.read()
        if ok:
            self._last_frame_bgr = frame
            # Convert for display
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)

            # Fit into window
            w = max(1, self._cam_win.winfo_width())
            h = max(1, self._cam_win.winfo_height())
            pil = pil.resize((w, h))

            ctki = ctk.CTkImage(light_image=pil, dark_image=pil, size=(w, h))
            self._video_img_ref = ctki  # keep reference
            self._video_lbl.configure(image=ctki)

        # ~30fps
        self._cam_win.after(33, self._tick_video)

    def _capture_frame(self):
        if self._last_frame_bgr is None:
            return

        # Convert to PIL
        rgb = cv2.cvtColor(self._last_frame_bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        # Encode as JPG bytes (store in memory)
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=self.capture_quality)
        jpg_bytes = buf.getvalue()

        # Create thumb for preview
        thumb = pil.copy()
        thumb.thumbnail(self.preview_size)

        self.pending = PendingPhoto(jpg_bytes=jpg_bytes, thumb_pil=thumb)

        self._apply_preview()
        self._close_camera()

    def _close_camera(self):
        self._running = False
        try:
            if getattr(self, "_cap", None) is not None:
                self._cap.release()
        except Exception:
            pass
        try:
            if getattr(self, "_cam_win", None) is not None:
                self._cam_win.destroy()
        except Exception:
            pass

    # ---------------- Preview ----------------

    def _apply_preview(self):
        if self.pending is None:
            self.preview_lbl.configure(text="No photo", image=None)
            self._preview_img = None
            self.retake_btn.configure(state="disabled")
            self.status_lbl.configure(text="")
            return

        pil = self.pending.thumb_pil
        ctki = ctk.CTkImage(light_image=pil, dark_image=pil, size=self.preview_size)
        self._preview_img = ctki  # keep reference
        self.preview_lbl.configure(text="", image=ctki)
        self.retake_btn.configure(state="normal")
        self.status_lbl.configure(text="Photo ready (will save when you click Save).")

    # ---------------- Host hooks ----------------

    def validate_before_save(self) -> bool:
        """
        Host calls this BEFORE saving the student.
        If a photo exists but ID is missing/invalid, block save and keep photo in memory.
        """
        if self.pending is None:
            return True

        sid = self._read_student_id()
        if sid is None:
            messagebox.showwarning(
                "Missing ID",
                "You took a photo, but Student ID is missing/invalid.\n"
                "Enter the ID first, then click Save again.\n\n"
                "The photo is kept in memory (not lost)."
            )
            return False

        return True

    def save_after_student_saved(self) -> bool:
        """
        Host calls this AFTER the student is saved successfully.
        Writes photos/<year>/<student_id>.jpg
        Returns True if saved or no pending photo.
        """
        if self.pending is None:
            return True

        sid = self._read_student_id()
        if sid is None:
            # Should not happen if validate_before_save was used, but keep safe
            messagebox.showwarning("Missing ID", "Cannot save photo because Student ID is missing/invalid.")
            return False

        year = int(self.year_fn())
        folder = os.path.join(self.base_dir, "photos", str(year))
        os.makedirs(folder, exist_ok=True)

        path = os.path.join(folder, f"{sid}.jpg")
        if os.path.exists(path):
            ok = messagebox.askyesno("Overwrite photo?", f"A photo already exists for ID {sid}.\n\nOverwrite it?")
            if not ok:
                return False

        try:
            with open(path, "wb") as f:
                f.write(self.pending.jpg_bytes)
        except Exception as e:
            messagebox.showerror("Save error", f"Could not save photo:\n{e}")
            return False

        # Optional: clear pending after saving
        self.pending = None
        self._apply_preview()
        return True

    def _read_student_id(self) -> Optional[int]:
        """
        Reads student ID from host getter. Accepts int or numeric string.
        Returns None if missing/invalid.
        """
        try:
            raw = self.get_student_id()
        except Exception:
            return None

        if raw is None:
            return None

        if isinstance(raw, int):
            return raw if raw > 0 else None

        s = str(raw).strip()
        if not s.isdigit():
            return None

        sid = int(s)
        return sid if sid > 0 else None


def attach_add_student_photo_extension(
    parent: ctk.CTkBaseClass,
    get_student_id: Callable[[], Any],
    *,
    base_dir: str | None = None,
) -> AddStudentPhotoPlugin:
    """
    Convenience function for your host-plugin style.

    Usage:
        photo_plugin = attach_add_student_photo_extension(ext_frame, lambda: id_var.get())
        # in save handler:
        if not photo_plugin.validate_before_save(): return
        ... save student ...
        if not photo_plugin.save_after_student_saved(): return
    """
    return AddStudentPhotoPlugin(parent, get_student_id, base_dir=base_dir)
