"""One hand -> one level control (brightness or volume) plus its gesture triggers."""

from collections import deque

import numpy as np

from .gestures import (
    HoldTrigger, Pose, PoseFilter, SwipeDetector, classify_pose, palm_center, pinch_ratio,
)


class HandControl:
    def __init__(self, label, worker, color, settings):
        self.label = label                # "Left" or "Right"
        self.worker = worker
        self.color = color
        self.settings = settings
        self.level = float(worker.initial)
        self.applied = self.level
        self.visible = False
        self.pts = None
        self.pose = Pose.OTHER
        self._pose_filter = PoseFilter(settings.pose_frames)
        self._history = deque(maxlen=4)
        self.fist = HoldTrigger(settings.fist_hold_seconds)
        self.swipe = SwipeDetector(settings.swipe_distance, settings.swipe_window,
                                   settings.swipe_cooldown)

    def _apply(self, force=False):
        if force or abs(self.level - self.applied) >= self.settings.apply_step \
                or self.level in (0.0, 100.0):
            if force or round(self.level) != round(self.applied):
                self.worker.submit_level(self.level)
                self.applied = self.level

    def update(self, pts, t, frame_w, frame_h):
        """Feed one frame. Returns a list of events: ("fist", label) or ("swipe", direction)."""
        self.pts = pts
        self.visible = pts is not None
        if pts is None:
            self._pose_filter.reset()
            self.pose = Pose.OTHER
            self._history.clear()
            self.fist.update(t, False)
            self.swipe.update(t, 0, 0, False)
            return []

        raw = classify_pose(pts)
        previous = self.pose
        self.pose = self._pose_filter.update(raw)

        # Leaving the pinch pose: fingers move while the pose changes, so roll
        # back to the level from a few frames ago instead of keeping the drift.
        if previous == Pose.PINCH and self.pose != Pose.PINCH and self._history:
            self.level = self._history[0]
            self._apply(force=True)
            self._history.clear()

        if self.pose == Pose.PINCH and raw == Pose.PINCH:
            lo, hi = self.settings.range_for(self.label)
            target = float(np.interp(pinch_ratio(pts), [lo, hi], [0.0, 100.0]))
            self.level += self.settings.smoothing * (target - self.level)
            if target <= 0.5 and self.level < 2:
                self.level = 0.0
            elif target >= 99.5 and self.level > 98:
                self.level = 100.0
            self._history.append(self.level)
            self._apply()

        events = []
        if self.fist.update(t, self.pose == Pose.FIST):
            events.append(("fist", self.label))
        center = palm_center(pts)
        # Swipe as soon as one frame shows an open palm (no debounce delay),
        # and keep going while the steady pose is still "open" during motion blur.
        swiping = raw == Pose.OPEN or self.pose == Pose.OPEN
        direction = self.swipe.update(t, center[0] / frame_w, center[1] / frame_h, swiping)
        if direction:
            events.append(("swipe", direction))
        return events
