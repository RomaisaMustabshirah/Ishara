"""Everything drawn on screen."""

import time

import cv2

from .gestures import HAND_CONNECTIONS, INDEX_TIP, THUMB_TIP, Pose, palm_center, palm_size

FONT = cv2.FONT_HERSHEY_SIMPLEX

# BGR
GOLD = (70, 195, 255)      # brightness
TEAL = (190, 200, 40)      # volume
CORAL = (110, 120, 255)    # alerts / fist
WHITE = (245, 245, 245)
MUTED = (130, 130, 130)
PANEL = (28, 24, 22)


def text(img, s, org, scale=0.6, color=WHITE, thick=1, center=False):
    if center:
        (tw, _), _ = cv2.getTextSize(s, FONT, scale, thick)
        org = (int(org[0] - tw / 2), int(org[1]))
    org = (int(org[0]), int(org[1]))
    shadow = (org[0] + 1, org[1] + 2)
    cv2.putText(img, s, shadow, FONT, scale, (0, 0, 0), thick, cv2.LINE_AA)
    cv2.putText(img, s, org, FONT, scale, color, thick, cv2.LINE_AA)


def panel(img, x1, y1, x2, y2, alpha=0.6):
    x1, y1 = max(0, x1), max(0, y1)
    roi = img[y1:y2, x1:x2]
    if roi.size:
        dark = roi.copy()
        dark[:] = PANEL
        cv2.addWeighted(dark, alpha, roi, 1 - alpha, 0, roi)


def skeleton(img, pts, color):
    for a, b in HAND_CONNECTIONS:
        cv2.line(img, tuple(pts[a].astype(int)), tuple(pts[b].astype(int)), (220, 220, 220), 1, cv2.LINE_AA)
    for p in pts:
        cv2.circle(img, tuple(p.astype(int)), 3, color, -1, cv2.LINE_AA)


def dial(img, ctrl, t):
    """A 270-degree arc around the palm showing the level, plus the current pose."""
    pts = ctrl.pts
    cx, cy = palm_center(pts).astype(int)
    r = int(max(40, palm_size(pts) * 1.25))
    active = ctrl.pose == Pose.PINCH
    color = ctrl.color if active else MUTED

    cv2.ellipse(img, (cx, cy), (r, r), 0, 135, 405, (60, 60, 60), 6, cv2.LINE_AA)
    end = 135 + 270 * ctrl.level / 100.0
    if ctrl.level > 0.5:
        cv2.ellipse(img, (cx, cy), (r, r), 0, 135, end, color, 6, cv2.LINE_AA)

    text(img, f"{ctrl.worker.name} {int(round(ctrl.level))}%", (cx, cy - r - 14), 0.6, color, 2, center=True)

    if active:
        a = tuple(pts[THUMB_TIP].astype(int))
        b = tuple(pts[INDEX_TIP].astype(int))
        cv2.line(img, a, b, ctrl.color, 2, cv2.LINE_AA)
        cv2.circle(img, a, 7, ctrl.color, -1, cv2.LINE_AA)
        cv2.circle(img, b, 7, ctrl.color, -1, cv2.LINE_AA)

    label = {Pose.PINCH: "adjusting", Pose.OPEN: "resting", Pose.FIST: "hold...",
             Pose.OTHER: ""}[ctrl.pose]
    if label:
        text(img, label, (cx, cy + r + 24), 0.5, CORAL if ctrl.pose == Pose.FIST else WHITE, 1, center=True)

    progress = ctrl.fist.progress(t)
    if progress > 0:
        cv2.ellipse(img, (cx, cy), (r + 12, r + 12), 0, -90, -90 + 360 * progress, CORAL, 4, cv2.LINE_AA)


def status_card(img, x, y, ctrl, extra="", align_right=False):
    w, h = 210, 62
    if align_right:
        x = x - w
    panel(img, x, y, x + w, y + h)
    name = ctrl.worker.name
    if not ctrl.worker.available:
        text(img, name, (x + 12, y + 24), 0.55, MUTED)
        text(img, "not available", (x + 12, y + 48), 0.5, MUTED)
        return
    color = ctrl.color if ctrl.visible else MUTED
    text(img, name + (f"  ({extra})" if extra else ""), (x + 12, y + 24), 0.55, color)
    bar_x1, bar_x2, bar_y = x + 12, x + w - 60, y + 42
    cv2.rectangle(img, (bar_x1, bar_y), (bar_x2, bar_y + 8), (70, 70, 70), -1)
    fill = int(bar_x1 + (bar_x2 - bar_x1) * ctrl.level / 100.0)
    cv2.rectangle(img, (bar_x1, bar_y), (fill, bar_y + 8), color, -1)
    text(img, f"{int(round(ctrl.level))}%", (bar_x2 + 8, bar_y + 9), 0.55, WHITE)


class Toasts:
    """Short messages that fade out at the top of the screen."""

    def __init__(self, duration=1.4):
        self.duration = duration
        self._items = []

    def push(self, message, color=WHITE):
        self._items.append((message, color, time.monotonic() + self.duration))

    def draw(self, img):
        now = time.monotonic()
        self._items = [i for i in self._items if i[2] > now][-3:]
        w = img.shape[1]
        for n, (message, color, _) in enumerate(self._items):
            y = 70 + n * 38
            (tw, _), _ = cv2.getTextSize(message, FONT, 0.7, 2)
            panel(img, w // 2 - tw // 2 - 16, y - 26, w // 2 + tw // 2 + 16, y + 10, 0.7)
            text(img, message, (w // 2, y), 0.7, color, 2, center=True)


def help_overlay(img):
    lines = [
        "PINCH (ring + pinky folded): thumb-index distance sets level",
        "OPEN PALM: rest  |  swipe left / right: previous / next track",
        "FIST (hold): right = mute, left = play / pause",
        "C calibrate   D skeleton   H help   Q quit",
    ]
    h, w = img.shape[:2]
    top = h - 22 - 24 * len(lines)
    panel(img, 0, top - 8, w, h, 0.5)
    for i, line in enumerate(lines):
        text(img, line, (w // 2, top + 18 + 24 * i), 0.5, WHITE, 1, center=True)


def calibration_overlay(img, remaining, counts):
    h, w = img.shape[:2]
    panel(img, w // 2 - 330, h // 2 - 90, w // 2 + 330, h // 2 + 90, 0.75)
    text(img, "Calibrating", (w // 2, h // 2 - 50), 0.9, GOLD, 2, center=True)
    text(img, "Make the pinch pose with both hands.", (w // 2, h // 2 - 12), 0.6, WHITE, 1, center=True)
    text(img, "Close and open thumb + index fully, again and again.", (w // 2, h // 2 + 16), 0.6, WHITE, 1, center=True)
    text(img, f"{remaining:0.1f}s   left: {counts['Left']}   right: {counts['Right']}",
         (w // 2, h // 2 + 56), 0.6, TEAL, 1, center=True)
