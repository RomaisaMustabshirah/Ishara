# Ishara · اشارہ

**Control your computer with your hands.** Ishara means *gesture* in Urdu. It watches your hands through the webcam and turns them into controls: your left hand sets screen brightness, your right hand sets volume, and simple poses play, pause, skip and mute.

No extra hardware is needed, only a webcam.

## Gestures

| Pose | Left hand | Right hand |
|---|---|---|
| **Pinch** (ring and pinky folded) | thumb–index distance sets **brightness** | thumb–index distance sets **volume** |
| **Open palm** | rest, nothing changes | rest, nothing changes |
| **Open palm + swipe** | swipe right / left: next / previous track | same |
| **Fist** (hold ~0.6 s) | play / pause | mute / unmute |

Ishara is built around an **open palm rest pose**. Levels only change while you hold the pinch pose, so you can move, wave or drop your hands without anything jumping.

## How it works

```
webcam ─► MediaPipe Hand Landmarker (21 points per hand)
        ─► pose classifier   (how far each fingertip reaches from the wrist)
        ─► pinch ratio       (thumb–index distance ÷ palm length)
        ─► smoothing + debouncing
        ─► background workers ─► brightness / volume / media keys
        ─► on-screen HUD (dials around each palm)
```

- **Distance-independent:** the pinch is measured relative to your palm size, so it feels the same close to the camera or far away.
- **Personal calibration:** press **C** and Ishara learns *your* pinch range and saves it.
- **Never freezes:** system calls run on background threads, so the camera stays smooth even when Windows is slow to change brightness.
- **Drift-free exits:** when you leave the pinch pose, Ishara rolls back the few frames where your fingers were still moving.

## Setup

Requires Python 3.10–3.12 and a webcam.

```bash
git clone https://github.com/<your-username>/ishara.git
cd ishara
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
python -m ishara
```

The hand model downloads automatically on the first run. Settings are saved in `~/.ishara/config.json`.

| Key | Action |
|---|---|
| `C` | calibrate (5 seconds: pinch open and closed with both hands) |
| `D` | show / hide hand skeleton |
| `H` | show / hide help |
| `Q` / `Esc` | quit |

Options: `python -m ishara --camera 1` uses another camera, and `python -m ishara --reset` restores the default settings.

### Platform support

| | Windows | Linux | macOS |
|---|---|---|---|
| Volume + mute | ✓ | ✓ (pactl / amixer) | ✓ |
| Brightness | ✓ | ✓ (supported displays) | — |
| Media keys | ✓ | ✓ (needs `playerctl`) | — |

## Project structure

```
ishara/
├── ishara/
│   ├── app.py          # main loop: camera → gestures → system → HUD
│   ├── gestures.py     # pose classification, filters, swipe detection (pure logic)
│   ├── controls.py     # one hand → one level control
│   ├── calibration.py  # learns each hand's pinch range
│   ├── system.py       # volume, brightness, media keys on background threads
│   ├── hud.py          # on-screen drawing
│   └── config.py       # settings in ~/.ishara/config.json
├── tests/
│   └── test_gestures.py
├── requirements.txt
└── LICENSE
```

## Tests

The gesture logic is separated from the camera, so it can be tested with synthetic hands:

```bash
pip install pytest
python -m pytest
```

## Roadmap

- [ ] Custom gesture mapping in the config file
- [ ] Scroll and cursor control mode
- [ ] Tray icon to run in the background
- [ ] Sign-language-inspired gesture set

## License

MIT © 2026 Romaisa
