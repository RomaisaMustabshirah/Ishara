"""Tests for the gesture logic using synthetic hands (no camera needed)."""

import numpy as np
import pytest

from ishara.calibration import Calibrator
from ishara.config import Settings
from ishara.controls import HandControl
from ishara.gestures import (
    FINGERS, INDEX_MCP, INDEX_TIP, MIDDLE_MCP, PINKY_MCP, RING_MCP, THUMB_TIP, WRIST,
    HoldTrigger, Pose, PoseFilter, SwipeDetector, assign_hands, classify_pose, pinch_ratio,
)

OPEN, CURLED, RELAXED = 1.35, 0.75, 1.0
X = {"index": -25, "middle": 0, "ring": 20, "pinky": 40}


def make_hand(index=OPEN, middle=OPEN, ring=OPEN, pinky=OPEN, pinch=0.6, offset=(300, 400)):
    """Palm length is 100 px, so `pinch` equals the pinch ratio."""
    pts = np.zeros((21, 2), dtype=np.float32)
    pts[WRIST] = [0, 0]
    pts[INDEX_MCP], pts[MIDDLE_MCP] = [-25, -95], [0, -100]
    pts[RING_MCP], pts[PINKY_MCP] = [20, -90], [40, -80]
    for name, reach in dict(index=index, middle=middle, ring=ring, pinky=pinky).items():
        pip, tip = FINGERS[name]
        pts[pip] = [X[name], -140]
        pts[tip] = pts[pip] * reach
    pts[THUMB_TIP] = pts[INDEX_TIP] + [-pinch * 100, 0]
    return pts + np.array(offset, dtype=np.float32)


def pinch_hand(pinch):
    return make_hand(index=RELAXED, middle=RELAXED, ring=CURLED, pinky=CURLED, pinch=pinch)


class FakeWorker:
    name, available, initial = "Test", True, 50.0

    def __init__(self):
        self.sent = []

    def submit_level(self, value):
        self.sent.append(value)


# --- poses ------------------------------------------------------------------
def test_pinch_ratio_is_scale_free():
    assert pinch_ratio(pinch_hand(0.6)) == pytest.approx(0.6, abs=0.01)
    assert pinch_ratio(pinch_hand(0.6) * 2) == pytest.approx(0.6, abs=0.01)


@pytest.mark.parametrize("hand, pose", [
    (make_hand(), Pose.OPEN),
    (make_hand(CURLED, CURLED, CURLED, CURLED), Pose.FIST),
    (pinch_hand(0.5), Pose.PINCH),
    (make_hand(OPEN, OPEN, OPEN, CURLED), Pose.OTHER),
])
def test_classify_pose(hand, pose):
    assert classify_pose(hand) == pose


# --- filters ----------------------------------------------------------------
def test_pose_filter_needs_consecutive_frames():
    f = PoseFilter(frames=3)
    assert f.update(Pose.OPEN) == Pose.OTHER
    assert f.update(Pose.OPEN) == Pose.OTHER
    assert f.update(Pose.OPEN) == Pose.OPEN
    assert f.update(Pose.FIST) == Pose.OPEN       # one noisy frame is ignored


def test_hold_trigger_fires_once():
    h = HoldTrigger(hold=0.5)
    assert not h.update(0.0, True)
    assert h.update(0.6, True)
    assert not h.update(1.0, True)                # still held: no repeat
    h.update(1.1, False)
    h.update(1.2, True)
    assert h.update(1.8, True)                    # released and held again


def test_swipe_detects_direction_and_cooldown():
    s = SwipeDetector(distance=0.25, window=0.4, cooldown=1.0)
    result = None
    for i in range(6):
        result = s.update(i * 0.05, 0.3 + i * 0.07, 0.5, True) or result
    assert result == "right"
    late = [s.update(0.4 + i * 0.05, 0.7 - i * 0.07, 0.5, True) for i in range(6)]
    assert "left" not in late                     # inside cooldown
    s2 = SwipeDetector(distance=0.25)
    slow = [s2.update(i * 0.1, 0.3 + i * 0.01, 0.5, True) for i in range(10)]
    assert not any(slow)


def test_assign_hands_falls_back_to_position():
    a, b = make_hand(offset=(100, 400)), make_hand(offset=(900, 400))
    hands = assign_hands([("Right", b), ("Right", a)])
    assert hands["Left"] is a and hands["Right"] is b


# --- control ----------------------------------------------------------------
def run(ctrl, hand, frames, t0=0.0):
    t = t0
    for _ in range(frames):
        ctrl.update(hand, t, 1280, 720)
        t += 1 / 30
    return t


def test_control_reaches_both_ends():
    ctrl = HandControl("Right", FakeWorker(), (0, 0, 0), Settings())
    run(ctrl, pinch_hand(1.3), 60)
    assert ctrl.level == 100.0
    run(ctrl, pinch_hand(0.1), 60)
    assert ctrl.level == 0.0
    assert ctrl.worker.sent[-1] == 0.0


def test_open_palm_rests_without_changing_level():
    ctrl = HandControl("Right", FakeWorker(), (0, 0, 0), Settings())
    t = run(ctrl, pinch_hand(0.65), 60)
    level = ctrl.level
    run(ctrl, make_hand(pinch=1.3), 30, t)          # wide open hand
    assert ctrl.pose == Pose.OPEN
    assert ctrl.level == pytest.approx(level, abs=1.0)


def test_fist_event():
    ctrl = HandControl("Right", FakeWorker(), (0, 0, 0), Settings())
    events, t = [], 0.0
    for _ in range(40):
        events += ctrl.update(make_hand(CURLED, CURLED, CURLED, CURLED), t, 1280, 720)
        t += 1 / 30
    assert events == [("fist", "Right")]


# --- calibration ------------------------------------------------------------
def test_calibration_measures_range():
    cal = Calibrator()
    cal.start(0.0)
    for r in np.linspace(0.1, 1.4, 60):
        cal.feed("Left", pinch_hand(r))
    ranges = cal.finish()
    lo, hi = ranges["Left"]
    assert 0.1 < lo < 0.3 and 1.2 < hi < 1.4
    assert "Right" not in ranges                     # no samples for that hand
