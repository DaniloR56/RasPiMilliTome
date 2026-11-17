#!/usr/bin/env python3
"""RasPi MilliTome — Pi Zero 2 W / Camera Module 3.

Reduced-resolution memory preset: 2304 × 1296 (3 MP), not native 12 MP.

Based on the fixed-focus workflow of RaspiCam3VideoRecordingV2.0.py:
- preview with crosshair and reference square
- autofocus once, read LensPosition and LOCK it
- coarse/fine/ultrafine manual adjustments
- save/restore focus in a JSON file
- capture 2304 × 1296 JPEGs without GUI overlays
- use one 2304 × 1296 sensor mode, with a small YUV preview (5 fps)
- stop accepting captures if the sensor stops sending frames
Optional physical capture button: BCM GPIO27 (header pin 13) to GND,
matching the reference's active-low input with internal pull-up. GUI capture
and focus controls remain available without GPIO. Requires RPi.GPIO (or a
compatible implementation) only for the physical button; no laser or TFT.
A held button captures once and must be released before another capture.
"""

import json
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import Tk, Label, Button, Frame, Canvas, Scrollbar, X

import cv2
from libcamera import controls
from picamera2 import Picamera2
from PIL import Image, ImageDraw, ImageTk

BASE = Path.home() / "MilliTomeDemos"
PHOTOS = BASE / "photos"
SETTINGS_PATH = BASE / "camera_settings.json"
FOCUS_PATH = BASE / "millitome_camera_focus.json"
PHOTOS.mkdir(parents=True, exist_ok=True)
PREVIEW_SIZE = (640, 480)
DISPLAY_SIZE = (240, 320)  # rotated 270° clockwise
CAPTURE_SIZE = (2304, 1296)  # Reduced-resolution preset for Pi Zero 2 W.
DEFAULT_FOCUS = 5.50
FOCUS_STEPS = (0.50, 0.05, 0.01)
GPIO_ENABLED = True  # Set False to use only the GUI capture button.
BUTTON_PIN = 27  # BCM numbering, physical header pin 13; switch to GND.
BUTTON_DEBOUNCE_SECONDS = 0.05
CAPTURE_DEBOUNCE_SECONDS = 0.30

DEFAULT_SETTINGS = {
    "brightness": 50, "contrast": 0, "shutter_speed": 0,
    "iso": 200, "target_size": 120,
}


def load_json(path):
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
            return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        print(f"Cannot read {path}: {exc}")
        return {}


settings = {**DEFAULT_SETTINGS, **load_json(SETTINGS_PATH)}
try:
    saved_focus = float(load_json(FOCUS_PATH).get("lens_position", DEFAULT_FOCUS))
except (TypeError, ValueError):
    saved_focus = DEFAULT_FOCUS


def next_filename():
    highest = 0
    for item in PHOTOS.iterdir():
        m = re.fullmatch(r"photo_(\d+)\.jpg", item.name)
        if m:
            highest = max(highest, int(m.group(1)))
    return PHOTOS / f"photo_{highest + 1:03d}.jpg"


commands = queue.Queue()
messages = queue.Queue()
stop_event = threading.Event()
image_lock = threading.Lock()
latest_preview = None
capture_lock = threading.Lock()
camera_ready = threading.Event()
capture_pending = False
last_capture_request = float("-inf")


def notify(kind, data):
    messages.put((kind, data))


def request_capture():
    """Accept at most one queued/in-progress capture, from any thread.

    Never access Tk or the camera here. All callers share this gate, including
    GPIO; pending stays set until the camera worker finishes the capture.
    """
    global capture_pending, last_capture_request
    with capture_lock:
        now = time.monotonic()
        if (stop_event.is_set() or not camera_ready.is_set()
                or capture_pending
                or now - last_capture_request < CAPTURE_DEBOUNCE_SECONDS):
            return False
        capture_pending = True
        last_capture_request = now
        commands.put(("capture", None))
        notify("status", "Capture requested...")
        print("Capture requested...", flush=True)
        return True


def finish_capture():
    global capture_pending
    with capture_lock:
        capture_pending = False


def gpio_worker():
    """Poll a debounced active-low switch; all GPIO calls stay in this thread.

    Start disarmed: a switch held at launch must first be released. Stable
    release rearms it, so holding a switch or bouncing cannot queue repeats.
    GPIO failure affects only the physical button. Clean up only our pin.
    """
    gpio = None
    owns_pin = False
    try:
        if not GPIO_ENABLED:
            notify("gpio_status", "Physical button disabled; GUI capture available")
            return
        import RPi.GPIO as gpio
        mode = gpio.getmode()
        if mode is None:
            gpio.setmode(gpio.BCM)
        elif mode != gpio.BCM:
            raise RuntimeError("GPIO numbering already configured differently")
        # Refuse to take over a pin already configured as an output/alternate
        # function. Do not disable GPIO warnings globally.
        if gpio.gpio_function(BUTTON_PIN) != gpio.IN:
            raise RuntimeError("GPIO27 is already configured for another function")
        owns_pin = True  # Also clean up if setup fails partway through.
        gpio.setup(BUTTON_PIN, gpio.IN, pull_up_down=gpio.PUD_UP)
        notify("gpio_status", "Physical button ready: GPIO27 to GND")
        candidate = gpio.input(BUTTON_PIN)
        changed_at = time.monotonic()
        stable = None
        armed = False
        while not stop_event.wait(0.01):
            level = gpio.input(BUTTON_PIN)
            now = time.monotonic()
            if level != candidate:
                candidate = level
                changed_at = now
            elif level != stable and now - changed_at >= BUTTON_DEBOUNCE_SECONDS:
                stable = level
                if level == gpio.HIGH:
                    armed = True
                elif armed:
                    armed = False
                    request_capture()
    except Exception as exc:
        print("Physical button unavailable:", exc)
        notify("gpio_status", f"Physical button unavailable; GUI capture available ({exc})")
    finally:
        if gpio is not None and owns_pin:
            try:
                gpio.cleanup(BUTTON_PIN)
            except Exception as exc:
                print("GPIO27 cleanup failed:", exc)


class CameraFrameTimeout(RuntimeError):
    pass


def wait_for_still_request(cam, timeout=30):
    """Use completion notification supported by older Picamera2 versions.

    get_result() is called only after completion, with no timeout argument.
    If completion arrives after our deadline, release the request there so a
    single camera buffer cannot remain held by an abandoned capture.
    """
    completed = threading.Event()
    result_lock = threading.Lock()
    outcome = {}
    abandoned = False

    def on_complete(job):
        try:
            request = job.get_result()
            error = None
        except Exception as exc:
            request, error = None, exc
        with result_lock:
            if abandoned:
                if request is not None:
                    request.release()
            else:
                outcome.update(request=request, error=error)
            completed.set()

    cam.capture_request(wait=False, signal_function=on_complete)
    completed.wait(timeout)
    with result_lock:
        if not outcome:
            abandoned = True
            raise CameraFrameTimeout(f"Camera stopped sending frames ({timeout}s timeout). Close the program and restart the Pi.")
        if outcome["error"] is not None:
            raise outcome["error"]
        return outcome["request"]


def capture_still(cam, filename):
    """Copy YUV to ordinary RAM and return the camera buffer before encoding.

    Convert explicitly with OpenCV because older Picamera2 releases cannot
    save a YUV stream through request.save(). Rotate before encoding so the
    output JPEG is written only once.
    """
    notify("status", "Capture: waiting for 2304 × 1296 image...")
    print("Capture: waiting for 2304 × 1296 image...", flush=True)
    request = wait_for_still_request(cam)
    try:
        yuv = request.make_array("main")
    finally:
        request.release()
    notify("status", "Capture: converting and saving JPEG...")
    print("Capture: converting and saving JPEG...", flush=True)
    # YUV arrays can include stride padding. Convert the full padded array,
    # then crop to the configured width, retaining the correct U/V layout.
    width, height = cam.camera_configuration()["main"]["size"]
    rgb = cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB_I420)[:height, :width]
    del yuv
    image = Image.fromarray(rgb)
    del rgb
    try:
        rotated = image.transpose(Image.Transpose.ROTATE_90)
        try:
            rotated.save(filename, "JPEG", quality=95)
        finally:
            rotated.close()
    finally:
        image.close()


def worker():
    global latest_preview
    cam = None
    lens = saved_focus
    can_focus = False
    focus_min, focus_max = 0.0, 15.0
    try:
        cam = Picamera2()
        sensor_size = tuple(cam.sensor_resolution)
        notify("info", f"Images: {PHOTOS} | Capture: {CAPTURE_SIZE[0]} × {CAPTURE_SIZE[1]} | Sensor: {sensor_size[0]} × {sensor_size[1]}")
        # Keep one sensor mode throughout the session. The main stream is
        # 2304 × 1296 resolution; only the small lores stream is copied for preview.
        # YUV420 uses 1.5 bytes/pixel versus 3 for RGB888. One buffer
        # and no exported RAW stream further reduce camera memory use.
        camera_config = cam.create_still_configuration(
            main={"size": CAPTURE_SIZE, "format": "YUV420"},
            lores={"size": PREVIEW_SIZE, "format": "YUV420"},
            raw=None, buffer_count=1, queue=False,
            controls={"FrameDurationLimits": (200000, 200000)}  # 5 fps
        )
        cam.configure(camera_config)
        available = cam.camera_controls
        can_focus = "AfMode" in available and "LensPosition" in available
        if can_focus:
            focus_min = max(0.0, float(available["LensPosition"][0]))
            focus_max = min(15.0, float(available["LensPosition"][1]))
            lens = max(focus_min, min(focus_max, lens))
            cam.set_controls({
                "AfMode": controls.AfModeEnum.Manual, "LensPosition": lens,
            })
            notify("focus_available", lens)
        else:
            notify("focus_unavailable", "No motorised focus on this camera")

        exposure_controls = {}
        brightness = max(0, min(100, int(settings.get("brightness", 50))))
        contrast = max(-100, min(100, int(settings.get("contrast", 0))))
        exposure_controls["Brightness"] = (brightness - 50) / 50.0
        exposure_controls["Contrast"] = max(0.0, 1.0 + contrast / 100.0)
        shutter = int(settings.get("shutter_speed", 0))
        if shutter > 0:
            exposure_controls.update({
                "AeEnable": False, "ExposureTime": shutter,
                "AnalogueGain": max(1., int(settings.get("iso", 200)) / 100.),
            })
        cam.set_controls({k: v for k, v in exposure_controls.items() if k in available})
        cam.options["quality"] = 95
        cam.start()
        notify("status", "Camera warming up...")
        time.sleep(2)
        locked_awb = {}
        try:
            request = wait_for_still_request(cam)
            try:
                gains = request.get_metadata().get("ColourGains")
            finally:
                request.release()
            if gains and "AwbEnable" in available:
                locked_awb = {"AwbEnable": False, "ColourGains": tuple(gains)}
                cam.set_controls(locked_awb)
        except CameraFrameTimeout:
            raise
        except Exception as exc:
            print("White balance lock unavailable:", exc)
        camera_ready.set()
        notify("status", "Ready")

        while not stop_event.is_set():
            try:
                action, value = commands.get_nowait()
            except queue.Empty:
                action = None
                value = None

            if action == "adjust" and can_focus:
                try:
                    lens = max(focus_min, min(focus_max, lens + float(value)))
                    cam.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                      "LensPosition": lens})
                    notify("focus_position", lens)
                except Exception as exc:
                    notify("focus_status", f"Manual focus error: {exc}")

            elif action == "autofocus" and can_focus:
                notify("focus_status", "Autofocusing...")
                try:
                    cam.set_controls({"AfMode": controls.AfModeEnum.Auto})
                    time.sleep(.2)
                    success = cam.autofocus_cycle()
                    metadata = cam.capture_metadata()
                    position = metadata.get("LensPosition")
                    if success and position is not None:
                        lens = max(focus_min, min(focus_max, float(position)))
                        notify("focus_status", "Autofocus successful; position LOCKED")
                    else:
                        notify("focus_status", "Autofocus not confirmed; previous focus restored")
                    cam.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                      "LensPosition": lens})
                    notify("focus_position", lens)
                except Exception as exc:
                    notify("focus_status", f"Autofocus error: {exc}")
                    cam.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                      "LensPosition": lens})

            elif action == "save_focus" and can_focus:
                try:
                    config = {
                        "camera": "Raspberry Pi Camera Module 3",
                        "sensor": "IMX708", "focus_mode": "manual",
                        "lens_position": round(lens, 4),
                        "saved": datetime.now().isoformat(timespec="seconds"),
                    }
                    FOCUS_PATH.write_text(json.dumps(config, indent=4) + "\n",
                                          encoding="utf-8")
                    notify("focus_status", f"Saved focus {lens:.4f} D")
                except OSError as exc:
                    notify("focus_status", f"Cannot save focus: {exc}")

            elif action == "capture":
                filename = None
                notify("status", "Capturing 2304 × 1296 image...")
                try:
                    filename = next_filename()
                    capture_still(cam, filename)
                    if can_focus:
                        cam.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                          "LensPosition": lens})
                    notify("last", f"Last image: {filename.name}")
                    notify("status", f"Saved: {filename.name}")
                    print("Saved", filename, "LensPosition", lens if can_focus else "N/A")
                except CameraFrameTimeout:
                    # No further capture requests on a dead stream. The outer
                    # handler reports the error and shuts down the camera.
                    raise
                except Exception as exc:
                    print(f"Capture failed: {exc}", flush=True)
                    notify("status", f"Capture failed: {exc}")
                    try:
                        if filename is not None:
                            filename.unlink(missing_ok=True)
                    except OSError:
                        pass
                    try:
                        if can_focus:
                            cam.set_controls({"AfMode": controls.AfModeEnum.Manual,
                                              "LensPosition": lens})
                    except Exception:
                        pass
                finally:
                    finish_capture()
                    notify("capture_done", None)
                continue

            # Bound preview frame waits too: a dead sensor must not leave a
            # queued capture showing "Capture requested" indefinitely.
            request = wait_for_still_request(cam, timeout=10)
            try:
                frame = request.make_array("lores").copy()
            finally:
                request.release()
            rgb = cv2.cvtColor(frame, cv2.COLOR_YUV2RGB_I420)
            image = Image.fromarray(rgb).transpose(Image.Transpose.ROTATE_90)
            image.thumbnail(DISPLAY_SIZE, Image.Resampling.BILINEAR)
            draw = ImageDraw.Draw(image)
            w, h = image.size
            cx, cy = w // 2, h // 2
            draw.line((cx, 0, cx, h), fill="lime")
            draw.line((0, cy, w, cy), fill="lime")
            half = max(1, round(int(settings.get("target_size", 120)) * w / 480 / 2))
            draw.rectangle((cx-half, cy-half, cx+half, cy+half),
                           outline="red", width=2)
            with image_lock:
                latest_preview = image
    except Exception as exc:
        print("Camera error:", exc)
        notify("status", f"Camera error: {exc}")
    finally:
        # Synchronize failure/shutdown with concurrent capture requests.
        with capture_lock:
            camera_ready.clear()
            stop_event.set()
        finish_capture()
        if cam is not None:
            try:
                cam.stop()
            except Exception:
                pass
            try:
                cam.close()
            except Exception:
                pass
        notify("stopped", None)


root = Tk()
root.title("RasPi MilliTome - (Camera 3)")
Label(root, text="RasPi MilliTome Aquisition Interface (camera 3)", font=("Arial", 12, "bold")).pack(pady=(5, 0))
# Keep camera controls beside the image rather than below a tall preview.
# The controls have a scrollbar as a fallback for small desktops/large fonts.
content = Frame(root)
content.pack(fill="both", expand=True, padx=6, pady=6)
preview_panel = Frame(content)
preview_panel.pack(side="left", anchor="n", padx=(0, 8))
video_label = Label(preview_panel, width=240, height=320)
video_label.pack()
# Label width/height are text units until an image is installed. Reserve the
# preview in pixels with a fixed-size parent during camera startup.
preview_panel.configure(width=240, height=320)
preview_panel.pack_propagate(False)
video_label.configure(width=0, height=0)

controls_area = Frame(content)
controls_area.pack(side="left", fill="both", expand=True)
controls_canvas = Canvas(controls_area, width=400, height=420, highlightthickness=0)
controls_scrollbar = Scrollbar(controls_area, orient="vertical",
                              command=controls_canvas.yview)
controls_scrollbar.pack(side="right", fill="y")
controls_canvas.pack(side="left", fill="both", expand=True)
controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
controls_panel = Frame(controls_canvas)
controls_window = controls_canvas.create_window((0, 0), window=controls_panel, anchor="nw")
controls_panel.bind("<Configure>", lambda event: controls_canvas.configure(
    scrollregion=controls_canvas.bbox("all")))
controls_canvas.bind("<Configure>", lambda event: controls_canvas.itemconfigure(
    controls_window, width=event.width))

window_width = min(720, root.winfo_screenwidth() - 40)
window_height = min(400, root.winfo_screenheight() - 90)
root.geometry(f"{window_width}x{window_height}+10+30")

focus_label = Label(controls_panel, text="Focus: initializing...", font=("Arial", 11))
focus_label.pack(fill=X)
focus_status = Label(controls_panel, text="", font=("Arial", 9), wraplength=380)
focus_status.pack(fill=X)

focus_frame = Frame(controls_panel)
focus_frame.pack(padx=8, pady=4)
focus_buttons = []
focus_available = False
current_focus = saved_focus


def adjust(step):
    if focus_available:
        commands.put(("adjust", step))


def autofocus():
    if focus_available:
        commands.put(("autofocus", None))


def save_focus():
    if focus_available:
        commands.put(("save_focus", None))


for index, (label, increment) in enumerate((
        ("−0.50", -0.50), ("−0.05", -0.05), ("−0.01", -0.01),
        ("+0.01", +0.01), ("+0.05", +0.05), ("+0.50", +0.50))):
    b = Button(focus_frame, text=label, width=6, state="disabled",
               command=lambda step=increment: adjust(step))
    b.grid(row=index // 3, column=index % 3, padx=2, pady=2)
    focus_buttons.append(b)

actions = Frame(controls_panel)
actions.pack(pady=3)
auto_button = Button(actions, text="AUTOFOCUS", width=16, state="disabled", command=autofocus)
auto_button.pack(side="left", padx=3)
save_button = Button(actions, text="SAVE FOCUS", width=16, state="disabled", command=save_focus)
save_button.pack(side="left", padx=3)


capture_button = Button(controls_panel, text="CAPTURE IMAGE", font=("Arial", 17, "bold"),
                        height=2, command=request_capture)
capture_button.pack(fill=X, padx=12, pady=6)
last_label = Label(controls_panel, text="Last image: none", font=("Arial", 11))
last_label.pack(fill=X)
status_label = Label(controls_panel, text="Starting camera...", font=("Arial", 10), wraplength=380)
status_label.pack(fill=X)
info_label = Label(controls_panel, text=f"Images: {PHOTOS}", font=("Arial", 9), wraplength=380)
info_label.pack(fill=X, pady=5)
gpio_label = Label(controls_panel, text="Physical button: initializing...", font=("Arial", 9),
                   wraplength=380)
gpio_label.pack(fill=X, pady=(0, 5))

# Keyboard shortcuts mirror the reference acquisition script.
root.bind("a", lambda event: autofocus())
root.bind("s", lambda event: save_focus())
root.bind("[", lambda event: adjust(-0.50))
root.bind("]", lambda event: adjust(+0.50))
root.bind("<Left>", lambda event: adjust(-0.05))
root.bind("<Right>", lambda event: adjust(+0.05))
root.bind("-", lambda event: adjust(-0.01))
root.bind("+", lambda event: adjust(+0.01))
root.bind("=", lambda event: adjust(+0.01))

closing = False
stopped = False


def update_ui():
    global closing, stopped, focus_available, current_focus
    while True:
        try:
            kind, value = messages.get_nowait()
        except queue.Empty:
            break
        if kind == "info":
            info_label.config(text=value)
        elif kind == "status":
            status_label.config(text=value)
        elif kind == "last":
            last_label.config(text=value)
        elif kind == "focus_available":
            focus_available = True
            current_focus = value
            focus_label.config(text=f"Fixed LensPosition: {value:.4f} D")
            for b in focus_buttons:
                b.config(state="normal")
            auto_button.config(state="normal")
            save_button.config(state="normal")
        elif kind == "focus_unavailable":
            focus_label.config(text=value)
        elif kind == "focus_position":
            current_focus = value
            focus_label.config(text=f"Fixed LensPosition: {value:.4f} D")
        elif kind == "focus_status":
            focus_status.config(text=value)
        elif kind == "gpio_status":
            gpio_label.config(text=value)
        elif kind == "stopped":
            stopped = True
            capture_button.config(state="disabled")
    with capture_lock:
        capture_enabled = (camera_ready.is_set() and not capture_pending
                           and not stop_event.is_set() and not closing)
    capture_button.config(state="normal" if capture_enabled else "disabled",
                          text="CAPTURING..." if capture_pending else "CAPTURE IMAGE")
    with image_lock:
        image = latest_preview
    if image is not None and not closing:
        photo = ImageTk.PhotoImage(image)
        video_label.imgtk = photo
        video_label.config(image=photo)
    if closing and stopped:
        root.destroy()
    else:
        root.after(100, update_ui)


def close():
    global closing
    closing = True
    capture_button.config(state="disabled")
    status_label.config(text="Closing camera...")
    with capture_lock:
        stop_event.set()
        camera_ready.clear()


root.protocol("WM_DELETE_WINDOW", close)
camera_thread = threading.Thread(target=worker, name="camera-worker")
button_thread = threading.Thread(target=gpio_worker, name="gpio27-button")
camera_thread.start()
button_thread.start()
try:
    update_ui()
    root.mainloop()
finally:
    # Also cover KeyboardInterrupt and unexpected GUI errors. Let the camera
    # finish its current operation before closing it; no daemon-thread teardown.
    with capture_lock:
        stop_event.set()
        camera_ready.clear()
    button_thread.join()
    camera_thread.join()
