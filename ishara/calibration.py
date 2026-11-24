"""Measures each hand's own pinch range so 0 % and 100 % feel natural for that person."""

import numpy as np

from .gestures import Pose, classify_pose, pinch_ratio


class Calibrator:
    DURATION = 5.0
    MIN_SAMPLES = 20
    MIN_SPAN = 0.30

    def __init__(self):
        self.active = False
        self._t0 = 0.0
        self.samples = {"Left": [], "Right": []}

    def start(self, t):
        self.active = True
        self._t0 = t
        self.samples = {"Left": [], "Right": []}

    def remaining(self, t):
        return max(0.0, self.DURATION - (t - self._t0))

    def feed(self, label, pts):
        if self.active and pts is not None and classify_pose(pts) == Pose.PINCH:
            self.samples[label].append(pinch_ratio(pts))

    def finish(self):
        """Returns {label: [lo, hi]} for every hand with enough good samples."""
        self.active = False
        ranges = {}
        for label, values in self.samples.items():
            if len(values) < self.MIN_SAMPLES:
                continue
            lo, hi = np.percentile(values, [5, 95])
            if hi - lo < self.MIN_SPAN:
                continue
            # A little inside the measured extremes so 0 and 100 are easy to hit.
            ranges[label] = [round(float(lo) + 0.03, 3), round(float(hi) - 0.05, 3)]
        return ranges
