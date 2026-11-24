"""Ishara main loop: camera -> MediaPipe -> gestures -> system + HUD."""

import argparse
import platform
import sys
import time
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from . import hud
from .calibration import Calibrator
from .config import APP_DIR, MODEL_PATH, MODEL_URL, Settings
from .controls import HandControl
from .gestures import assign_hands
from .system import BrightnessBackend, MediaBackend, SystemWorker, VolumeBackend

WINDOW = "Ishara"


def ensure_model():
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 1_000_000:
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading MediaPipe hand model (~8 MB)...")
    tmp = MODEL_PATH.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    tmp.replace(MODEL_PATH)


def open_camera(settings):
    if platform.system() == "Windows":
        cap = cv2.VideoCapture(settings.camera_index, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(settings.camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.frame_height)
    if not cap.isOpened():
        sys.exit(f"Could not open camera {settings.camera_index}. Try --camera 1")
    return cap


def detect_hands(landmarker, frame, ts):
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
    found = []
    for i, landmarks in enumerate(result.hand_landmarks):
        pts = np.array([[p.x * w, p.y * h] for p in landmarks], dtype=np.float32)
        label = result.handedness[i][0].category_name if result.handedness else "Right"
        found.append((label, pts))
    return assign_hands(found)


def parse_args():
    parser = argparse.ArgumentParser(prog="ishara", description="Control your computer with hand gestures.")
    parser.add_argument("--camera", type=int, help="camera index (default from config, usually 0)")
    parser.add_argument("--reset", action="store_true", help="reset settings and calibration to defaults")
    return parser.parse_args()


def main():
    args = parse_args()
    settings = Settings() if args.reset else Settings.load()
    if args.reset:
        settings.save()
    if args.camera is not None:
        settings.camera_index = args.camera

    ensure_model()
    print("Connecting to system controls...")
    brightness = SystemWorker(BrightnessBackend)
    volume = SystemWorker(VolumeBackend)
    media = SystemWorker(MediaBackend)
    controls = {
        "Left": HandControl("Left", brightness, hud.GOLD, settings),
        "Right": HandControl("Right", volume, hud.TEAL, settings),
    }
    toasts = hud.Toasts()
    calibrator = Calibrator()
    muted = False

    options = vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    cap = open_camera(settings)
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    last_ts, fps, prev, bad = -1, 0.0, time.perf_counter(), 0
    toasts.push("Ishara is watching your hands", hud.GOLD)

    try:
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            while True:
                ok, frame = cap.read()
                if not ok:
                    bad += 1
                    if bad > 30:
                        print("Camera stopped sending frames.")
                        break
                    continue
                bad = 0

                frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                ts = max(int(time.monotonic() * 1000), last_ts + 1)
                last_ts = ts
                t = time.monotonic()
                hands = detect_hands(landmarker, frame, ts)

                # --- calibration mode ---
                if calibrator.active:
                    for label in ("Left", "Right"):
                        calibrator.feed(label, hands.get(label))
                        controls[label].pts = hands.get(label)
                        controls[label].visible = label in hands
                    if calibrator.remaining(t) <= 0:
                        ranges = calibrator.finish()
                        if "Left" in ranges:
                            settings.left_range = ranges["Left"]
                        if "Right" in ranges:
                            settings.right_range = ranges["Right"]
                        if ranges:
                            settings.save()
                            toasts.push("Calibrated: " + ", ".join(ranges).lower() + " hand", hud.GOLD)
                        else:
                            toasts.push("Calibration failed - try again with wider moves", hud.CORAL)

                # --- normal mode ---
                else:
                    for label, ctrl in controls.items():
                        for kind, value in ctrl.update(hands.get(label), t, w, h):
                            if kind == "fist" and value == "Right":
                                volume.run("toggle_mute")
                            elif kind == "fist" and value == "Left":
                                if media.available:
                                    media.run("play_pause")
                                    toasts.push("Play / Pause", hud.WHITE)
                                else:
                                    toasts.push("Media keys not available", hud.MUTED)
                            elif kind == "swipe" and media.available:
                                media.run("next" if value == "right" else "previous")
                                toasts.push("Next track  >>" if value == "right" else "<<  Previous track")

                while volume.results:
                    action, value = volume.results.popleft()
                    if action == "toggle_mute":
                        muted = bool(value)
                        toasts.push("Muted" if muted else "Unmuted", hud.CORAL if muted else hud.TEAL)
                media.results.clear()

                # --- draw ---
                for ctrl in controls.values():
                    if ctrl.visible:
                        if settings.show_skeleton:
                            hud.skeleton(frame, ctrl.pts, ctrl.color)
                        if not calibrator.active:
                            hud.dial(frame, ctrl, t)

                hud.status_card(frame, 16, 16, controls["Left"])
                hud.status_card(frame, w - 16, 16, controls["Right"], "muted" if muted else "", align_right=True)

                now = time.perf_counter()
                fps = 0.9 * fps + 0.1 / max(now - prev, 1e-6)
                prev = now
                hud.text(frame, f"{fps:4.1f} fps", (w // 2, 30), 0.5, hud.MUTED, 1, center=True)

                if calibrator.active:
                    counts = {k: len(v) for k, v in calibrator.samples.items()}
                    hud.calibration_overlay(frame, calibrator.remaining(t), counts)
                elif settings.show_help:
                    hud.help_overlay(frame)
                toasts.draw(frame)

                cv2.imshow(WINDOW, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    break
                if key in (ord("c"), ord("C")) and not calibrator.active:
                    calibrator.start(t)
                if key in (ord("d"), ord("D")):
                    settings.show_skeleton = not settings.show_skeleton
                if key in (ord("h"), ord("H")):
                    settings.show_help = not settings.show_help
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        for worker in (brightness, volume, media):
            worker.stop()
        settings.save()


if __name__ == "__main__":
    main()
