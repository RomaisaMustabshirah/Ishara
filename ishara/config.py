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

    swipe_distance: float = 0.28     # fraction of frame width
    swipe_window: float = 0.35       # seconds
    swipe_cooldown: float = 1.0      # seconds between swipes

    show_skeleton: bool = True
    show_help: bool = True

    def range_for(self, label):
        return self.left_range if label == "Left" else self.right_range

    @classmethod
    def load(cls):
        settings = cls()
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                known = {f.name for f in fields(cls)}
                for key, value in data.items():
                    if key in known:
                        setattr(settings, key, value)
            except (OSError, ValueError) as exc:
                print(f"[config] ignoring unreadable config: {exc}")
        return settings

    def save(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
