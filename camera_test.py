"""
VDMS CAMERA TEST - proof-of-concept

Purpose: prove that a physical USB camera attached to a Windows PC can be
opened, previewed, and captured programmatically, with the frame saved as a
local JPG. Nothing else.
"""

import os
import threading
import datetime
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

# Hide OpenCV's console warnings emitted while probing camera indices.
try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass

CAPTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
PREVIEW_MAX_W, PREVIEW_MAX_H = 640, 360
THUMB_MAX_W, THUMB_MAX_H = 320, 180
# Ask the driver for a very high resolution; the camera negotiates down to
# the highest mode it actually supports.
REQUEST_W, REQUEST_H = 3840, 2160


def list_cameras():
    """Return [(index, name), ...] of attached camera devices.

    Prefers real device names via pygrabber's DirectShow enumeration, whose
    order matches OpenCV's camera indices on Windows in practice. Falls back
    to probing indices 0-9 if that fails. Use the live preview to confirm
    the right camera is selected.
    """
    try:
        from pygrabber.dshow_graph import FilterGraph

        names = FilterGraph().get_input_devices()
        if names:
            return [(i, name) for i, name in enumerate(names)]
    except Exception:
        pass

    found = []
    for i in range(10):
        cap = cv2.VideoCapture(i, cv2.CAP_MSMF)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                found.append((i, f"Camera {i}"))
        cap.release()
    return found


class CameraStream:
    """Background reader thread. Keeps the latest full-resolution frame."""

    def __init__(self, index):
        self.index = index
        self.cap = None
        self.latest_frame = None
        self.error = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self):
        # OpenCV 5.x on Windows opens cameras by index via Media Foundation.
        # DirectShow is kept as a fallback for older stacks.
        self.cap = cv2.VideoCapture(self.index, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError(
                "Could not open the camera. It may be in use by another "
                "application (Teams/Zoom/Camera app) or disconnected."
            )
        # MJPG allows high resolutions at usable frame rates on most UVC cams.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, REQUEST_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, REQUEST_H)

        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.cap.release()
            raise RuntimeError(
                "Camera opened but returned no frames. Check the USB "
                "connection and Windows camera privacy settings "
                "(Settings > Privacy & security > Camera)."
            )
        with self._lock:
            self.latest_frame = frame

        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while self._running:
            ok, frame = self.cap.read()
            if ok and frame is not None:
                with self._lock:
                    self.latest_frame = frame
                    self.error = None
            else:
                with self._lock:
                    self.error = "Lost frames from camera (disconnected?)."

    def get_frame(self):
        with self._lock:
            if self.latest_frame is None:
                return None, self.error
            return self.latest_frame.copy(), self.error

    def resolution(self):
        if self.cap is None:
            return None
        return (
            int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self.cap is not None:
            self.cap.release()
        self.cap = None


class App:
    def __init__(self, root):
        self.root = root
        self.stream = None
        self.cameras = []
        self._preview_photo = None
        self._thumb_photo = None

        root.title("VDMS CAMERA TEST")
        root.resizable(False, False)

        pad = {"padx": 10, "pady": 5}
        main = ttk.Frame(root, padding=10)
        main.grid()

        ttk.Label(main, text="VDMS CAMERA TEST", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=3, **pad
        )

        ttk.Label(main, text="Camera:").grid(row=1, column=0, sticky="e", **pad)
        self.camera_var = tk.StringVar()
        self.camera_combo = ttk.Combobox(
            main, textvariable=self.camera_var, state="readonly", width=40
        )
        self.camera_combo.grid(row=1, column=1, sticky="w", **pad)
        self.camera_combo.bind("<<ComboboxSelected>>", self.on_camera_selected)
        ttk.Button(main, text="Refresh", command=self.refresh_cameras).grid(
            row=1, column=2, **pad
        )

        self.preview_label = tk.Label(
            main,
            text="LIVE PREVIEW\n(select a camera)",
            width=91,
            height=22,
            bg="#202020",
            fg="#cccccc",
        )
        self.preview_label.grid(row=2, column=0, columnspan=3, **pad)

        self.res_label = ttk.Label(main, text="Preview resolution: -")
        self.res_label.grid(row=3, column=0, columnspan=3, **pad)

        self.capture_btn = ttk.Button(
            main, text="CAPTURE", command=self.on_capture, state="disabled"
        )
        self.capture_btn.grid(row=4, column=0, columnspan=3, ipadx=30, ipady=5, **pad)

        self.status_label = tk.Label(main, text="Status: Ready", fg="#006600")
        self.status_label.grid(row=5, column=0, columnspan=3, **pad)

        self.last_capture_label = ttk.Label(main, text="Last Capture: -")
        self.last_capture_label.grid(row=6, column=0, columnspan=3, **pad)

        self.captured_res_label = ttk.Label(main, text="Captured: -")
        self.captured_res_label.grid(row=7, column=0, columnspan=3, **pad)

        self.thumb_label = tk.Label(
            main, text="(no capture yet)", width=45, height=11, bg="#303030", fg="#cccccc"
        )
        self.thumb_label.grid(row=8, column=0, columnspan=3, **pad)

        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.refresh_cameras()
        self.update_preview()

    # ---------- camera handling ----------

    def refresh_cameras(self):
        self.set_status("Detecting cameras...", ok=True)
        self.root.update_idletasks()
        self.cameras = list_cameras()
        if not self.cameras:
            self.camera_combo["values"] = []
            self.camera_var.set("")
            self.set_status(
                "No camera detected. Connect a USB camera and click Refresh.",
                ok=False,
            )
            return
        self.camera_combo["values"] = [f"[{i}] {name}" for i, name in self.cameras]
        self.set_status(
            f"Found {len(self.cameras)} camera(s). Select one to start the preview.",
            ok=True,
        )

    def on_camera_selected(self, _event=None):
        sel = self.camera_combo.current()
        if sel < 0:
            return
        index, name = self.cameras[sel]

        if self.stream is not None:
            self.stream.stop()
            self.stream = None
        self.capture_btn.config(state="disabled")
        self.set_status(f"Opening '{name}'...", ok=True)
        self.root.update_idletasks()

        try:
            stream = CameraStream(index)
            stream.start()
        except RuntimeError as e:
            self.set_status(f"Failed to open '{name}': {e}", ok=False)
            return

        self.stream = stream
        w, h = stream.resolution()
        self.res_label.config(text=f"Preview resolution: {w} x {h}")
        self.capture_btn.config(state="normal")
        self.set_status(f"Preview running on '{name}'. Ready to capture.", ok=True)

    # ---------- preview loop ----------

    def update_preview(self):
        if self.stream is not None:
            frame, err = self.stream.get_frame()
            if frame is not None:
                img = self._to_tk_image(frame, PREVIEW_MAX_W, PREVIEW_MAX_H)
                self._preview_photo = img
                self.preview_label.config(image=img, text="", width=img.width(), height=img.height())
            if err:
                self.set_status(err, ok=False)
        self.root.after(33, self.update_preview)

    # ---------- capture ----------

    def on_capture(self):
        if self.stream is None:
            self.set_status("No camera selected.", ok=False)
            return

        frame, err = self.stream.get_frame()
        if frame is None:
            self.set_status(f"Capture failed: no frame from camera. {err or ''}", ok=False)
            return
        if err:
            self.set_status(f"Capture failed: {err}", ok=False)
            return

        try:
            os.makedirs(CAPTURE_DIR, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(CAPTURE_DIR, f"card_{ts}.jpg")
            # Avoid overwriting if two captures happen within the same second.
            n = 1
            while os.path.exists(path):
                path = os.path.join(CAPTURE_DIR, f"card_{ts}_{n}.jpg")
                n += 1
            ok = cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise IOError("cv2.imwrite returned False")
        except Exception as e:
            self.set_status(f"Capture failed while saving file: {e}", ok=False)
            return

        h, w = frame.shape[:2]
        self.last_capture_label.config(text=f"Last Capture: {path}")
        self.captured_res_label.config(text=f"Captured: {w} x {h}")

        thumb = self._to_tk_image(frame, THUMB_MAX_W, THUMB_MAX_H)
        self._thumb_photo = thumb
        self.thumb_label.config(image=thumb, text="", width=thumb.width(), height=thumb.height())

        self.set_status("Capture successful", ok=True)

    # ---------- helpers ----------

    def _to_tk_image(self, bgr_frame, max_w, max_h):
        h, w = bgr_frame.shape[:2]
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            bgr_frame = cv2.resize(
                bgr_frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
            )
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(Image.fromarray(rgb))

    def set_status(self, message, ok):
        self.status_label.config(
            text=f"Status: {message}", fg="#006600" if ok else "#aa0000"
        )

    def on_close(self):
        if self.stream is not None:
            self.stream.stop()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
