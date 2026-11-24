"""
Pure gesture logic: no camera, no OS calls, so it can be unit-tested.

All functions take `pts`, a (21, 2) array of hand landmarks in pixels
(MediaPipe's 21-point hand model).
"""

import math
from collections import deque

import numpy as np

# --- landmark indices -------------------------------------------------------
WRIST = 0
THUMB_TIP = 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP = 13, 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

FINGERS = {
    "index": (INDEX_PIP, INDEX_TIP),
    "middle": (MIDDLE_PIP, MIDDLE_TIP),
    "ring": (RING_PIP, RING_TIP),
    "pinky": (PINKY_PIP, PINKY_TIP),
}

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]

# A finger's "reach" = wrist->tip distance / wrist->PIP distance.
EXTENDED_REACH = 1.15   # above this the finger is straight
CURLED_REACH = 0.90     # below this the finger is folded into the palm


class Pose:
    PINCH = "pinch"   # thumb + index active, ring and pinky folded -> adjust level
    OPEN = "open"     # all fingers straight -> rest / swipe
    FIST = "fist"     # all fingers folded -> hold to trigger
    OTHER = "other"


# --- geometry ---------------------------------------------------------------
def dist(a, b):
    return float(math.hypot(a[0] - b[0], a[1] - b[1]))


def palm_size(pts):
    return dist(pts[WRIST], pts[MIDDLE_MCP])


def palm_center(pts):
    return pts[[WRIST, INDEX_MCP, PINKY_MCP]].mean(axis=0)


def pinch_ratio(pts):
    """Thumb-index distance divided by palm length, so camera distance doesn't matter."""
    size = palm_size(pts)
    return dist(pts[THUMB_TIP], pts[INDEX_TIP]) / size if size > 1e-6 else 0.0


def finger_reach(pts, finger):
    pip, tip = FINGERS[finger]
    base = dist(pts[WRIST], pts[pip])
    return dist(pts[WRIST], pts[tip]) / base if base > 1e-6 else 0.0


def classify_pose(pts):
    reach = {name: finger_reach(pts, name) for name in FINGERS}
    if all(r > EXTENDED_REACH for r in reach.values()):
        return Pose.OPEN
    if all(r < CURLED_REACH for r in reach.values()):
        return Pose.FIST
    if reach["ring"] <= EXTENDED_REACH and reach["pinky"] <= EXTENDED_REACH:
        return Pose.PINCH
    return Pose.OTHER


# --- temporal filters -------------------------------------------------------
class PoseFilter:
    """A new pose only counts after it is seen for `frames` frames in a row."""

    def __init__(self, frames=3):
        self.frames = frames
        self.reset()

    def reset(self):
        self.stable = Pose.OTHER
        self._candidate = None
        self._count = 0

    def update(self, pose):
        if pose == self.stable:
            self._candidate, self._count = None, 0
            return self.stable
        if pose == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = pose, 1
        if self._count >= self.frames:
            self.stable, self._candidate, self._count = pose, None, 0
        return self.stable


class HoldTrigger:
    """Fires once when a condition has been true for `hold` seconds."""

    def __init__(self, hold=0.6):
        self.hold = hold
        self._start = None
        self._fired = False

    def update(self, t, active):
        if not active:
            self._start, self._fired = None, False
            return False
        if self._start is None:
            self._start = t
        if not self._fired and t - self._start >= self.hold:
            self._fired = True
            return True
        return False

    def progress(self, t):
        if self._start is None or self._fired:
            return 0.0
        return min(1.0, (t - self._start) / self.hold)


class SwipeDetector:
    """Detects a fast horizontal movement. Positions are normalised (0..1)."""

    def __init__(self, distance=0.28, window=0.35, cooldown=1.0, max_slope=0.6):
        self.distance = distance
        self.window = window
        self.cooldown = cooldown
        self.max_slope = max_slope
        self._hist = deque()
        self._last = -1e9

    def update(self, t, x, y, active):
        if not active:
            self._hist.clear()
            return None
        self._hist.append((t, x, y))
        while self._hist and t - self._hist[0][0] > self.window:
            self._hist.popleft()
        if t - self._last < self.cooldown or len(self._hist) < 3:
            return None
        _, x0, y0 = self._hist[0]
        dx, dy = x - x0, y - y0
        if abs(dx) >= self.distance and abs(dy) <= abs(dx) * self.max_slope:
            self._last = t
            self._hist.clear()
            return "right" if dx > 0 else "left"
        return None


# --- handedness -------------------------------------------------------------
def assign_hands(found):
    """
    `found` is a list of (label, pts). Returns {"Left": pts, "Right": pts}.
    If both hands get the same label, falls back to screen position
    (the frame is mirrored, so the user's left hand is on the left).
    """
    if len(found) == 2 and found[0][0] == found[1][0]:
        ordered = sorted(found, key=lambda item: item[1][WRIST][0])
        found = [("Left", ordered[0][1]), ("Right", ordered[1][1])]
    hands = {}
    for label, pts in found:
        hands.setdefault(label, pts)
    return hands
