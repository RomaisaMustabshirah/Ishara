"""User settings, stored as JSON in ~/.ishara/config.json."""

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR = Path.home() / ".ishara"
CONFIG_PATH = APP_DIR / "config.json"
MODEL_PATH = APP_DIR / "hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)

# Bump this when defaults change in a way old config files shouldn't override.
CONFIG_VERSION = 2
# Keys reset to the new defaults when an older config file is loaded.
# v2: smoother swipes, and calibration redone after the left/right hand fix.
RESET_ON_UPGRADE = {
    "swipe_distance", "swipe_window", "swipe_cooldown", "left_range", "right_range",
}


@dataclass
class Settings:
    camera_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720

    # Pinch ratio (thumb-index distance / palm length) mapped to 0 % and 100 %.
    # Calibration (press C) overwrites these with values measured from your hands.
    left_range: list = field(default_factory=lambda: [0.20, 1.15])
    right_range: list = field(default_factory=lambda: [0.20, 1.15])

    smoothing: float = 0.25          # 0..1, lower = smoother but slower
    apply_step: int = 1              # minimum change (in %) sent to the system
    pose_frames: int = 3             # frames a pose must hold before it counts
    fist_hold_seconds: float = 0.6   # how long to hold a fist to trigger it

    swipe_distance: float = 0.22     # fraction of frame width
    swipe_window: float = 0.5        # seconds
    swipe_cooldown: float = 0.8      # seconds between swipes

    show_skeleton: bool = True
    show_help: bool = True

    version: int = CONFIG_VERSION

    def range_for(self, label):
        return self.left_range if label == "Left" else self.right_range

    @classmethod
    def load(cls):
        settings = cls()
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                known = {f.name for f in fields(cls)}
                upgrading = data.get("version", 1) < CONFIG_VERSION
                for key, value in data.items():
                    if key == "version" or key not in known:
                        continue
                    if upgrading and key in RESET_ON_UPGRADE:
                        continue
                    setattr(settings, key, value)
                if upgrading:
                    print("[config] updated settings to the latest version - press C to recalibrate")
            except (OSError, ValueError) as exc:
                print(f"[config] ignoring unreadable config: {exc}")
        return settings

    def save(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
