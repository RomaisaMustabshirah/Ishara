"""
OS integrations: volume + mute, screen brightness, media keys.
Each backend lives on its own background thread (SystemWorker) so slow
system calls never freeze the camera loop.
"""

import platform
import re
import shutil
import subprocess
import threading
from collections import deque

SYSTEM = platform.system()


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout


# --- backends ---------------------------------------------------------------
class VolumeBackend:
    name = "Volume"

    def __init__(self):
        self.kind = None
        if SYSTEM == "Windows":
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            speakers = AudioUtilities.GetSpeakers()
            endpoint = getattr(speakers, "EndpointVolume", None)   # newer pycaw
            if endpoint is None:                                    # older pycaw
                from ctypes import POINTER, cast
                from comtypes import CLSCTX_ALL

                iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                endpoint = cast(iface, POINTER(IAudioEndpointVolume))
            self._ep = endpoint
            self.kind = "pycaw"
        elif SYSTEM == "Darwin":
            self.kind = "osascript"
        elif SYSTEM == "Linux":
            self.kind = "pactl" if shutil.which("pactl") else ("amixer" if shutil.which("amixer") else None)
        if self.kind is None:
            raise RuntimeError("no volume backend found")

    def get(self):
        if self.kind == "pycaw":
            return self._ep.GetMasterVolumeLevelScalar() * 100
        if self.kind == "osascript":
            return float(_run(["osascript", "-e", "output volume of (get volume settings)"]))
        out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"] if self.kind == "pactl"
                   else ["amixer", "sget", "Master"])
        match = re.search(r"(\d+)%", out)
        return float(match.group(1)) if match else 50.0

    def set(self, pct):
        pct = int(round(max(0, min(100, pct))))
        if self.kind == "pycaw":
            self._ep.SetMasterVolumeLevelScalar(pct / 100.0, None)
        elif self.kind == "osascript":
            _run(["osascript", "-e", f"set volume output volume {pct}"])
        elif self.kind == "pactl":
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"])
        else:
            _run(["amixer", "-q", "sset", "Master", f"{pct}%"])

    def toggle_mute(self):
        """Returns True if now muted, False if unmuted, None if unknown."""
        if self.kind == "pycaw":
            muted = not bool(self._ep.GetMute())
            self._ep.SetMute(int(muted), None)
            return muted
        if self.kind == "osascript":
            _run(["osascript", "-e",
                  "set volume output muted not (output muted of (get volume settings))"])
            return _run(["osascript", "-e", "output muted of (get volume settings)"]).strip() == "true"
        if self.kind == "pactl":
            _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
            return "yes" in _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        out = _run(["amixer", "sset", "Master", "toggle"])
        return "[off]" in out


class BrightnessBackend:
    name = "Brightness"

    def __init__(self):
        import screen_brightness_control as sbc

        self._sbc = sbc
        self.get()  # raises if the display doesn't support it

    def get(self):
        value = self._sbc.get_brightness(display=0)
        return float(value[0] if isinstance(value, list) else value)

    def set(self, pct):
        self._sbc.set_brightness(int(round(max(0, min(100, pct)))), display=0)


class MediaBackend:
    name = "Media"

    _VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
    _PLAYERCTL = {"play_pause": "play-pause", "next": "next", "previous": "previous"}

    def __init__(self):
        if SYSTEM == "Windows":
            import ctypes

            self._user32 = ctypes.windll.user32
            self.kind = "keybd"
        elif SYSTEM == "Linux" and shutil.which("playerctl"):
            self.kind = "playerctl"
        else:
            raise RuntimeError("media keys not supported here (Linux needs playerctl)")

    def _press(self, action):
        if self.kind == "keybd":
            vk = self._VK[action]
            self._user32.keybd_event(vk, 0, 0, 0)        # key down
            self._user32.keybd_event(vk, 0, 0x0002, 0)   # key up
        else:
            _run(["playerctl", self._PLAYERCTL[action]])
        return True

    def play_pause(self):
        return self._press("play_pause")

    def next(self):
        return self._press("next")

    def previous(self):
        return self._press("previous")


# --- worker -----------------------------------------------------------------
def _com_init():
    if SYSTEM != "Windows":
        return
    for module in ("comtypes", "pythoncom"):
        try:
            __import__(module).CoInitialize()
        except Exception:
            pass


class SystemWorker:
    """
    Owns one backend on a background thread.
    - submit_level(v): only the latest level is applied (old ones are dropped)
    - run(action): queued one-off actions such as "toggle_mute"
    Results of actions appear in `results` as (action, value) for the UI.
    """

    def __init__(self, backend_cls):
        self.name = backend_cls.name
        self.available = False
        self.initial = 50.0
        self.results = deque()
        self._backend_cls = backend_cls
        self._level = None
        self._actions = deque()
        self._stop = False
        self._cond = threading.Condition()
        self._ready = threading.Event()
        threading.Thread(target=self._loop, name=self.name, daemon=True).start()
        self._ready.wait(timeout=8)

    def _loop(self):
        _com_init()
        try:
            backend = self._backend_cls()
            if hasattr(backend, "get"):
                self.initial = backend.get()
            self.available = True
        except Exception as exc:
            print(f"[{self.name}] unavailable: {exc}")
            return
        finally:
            self._ready.set()

        while True:
            with self._cond:
                while self._level is None and not self._actions and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                actions = list(self._actions)
                self._actions.clear()
                level, self._level = self._level, None
            for action in actions:
                try:
                    self.results.append((action, getattr(backend, action)()))
                except Exception as exc:
                    print(f"[{self.name}] {action} failed: {exc}")
            if level is not None:
                try:
                    backend.set(level)
                except Exception as exc:
                    print(f"[{self.name}] set failed: {exc}")

    def submit_level(self, value):
        if self.available:
            with self._cond:
                self._level = value
                self._cond.notify()

    def run(self, action):
        if self.available:
            with self._cond:
                self._actions.append(action)
                self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()
