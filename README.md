# Low-Latency Spatial Vision & Kinematic Controller

Control games and serial devices using webcam hand tracking. This Windows Python
project combines MediaPipe Hands, anatomical gesture normalization, adaptive One Euro
filtering, and independent output workers for a virtual Xbox 360 controller,
keyboard arrows, or a microcontroller.

## Features

- Latest-frame camera buffer drops unread old frames instead of building a backlog.
- Hand tilt controls steering; thumb/index pinch controls throttle.
- A closed fist activates button A or braking in the Hill Climb keyboard mode.
- Tracking-loss watchdogs return outputs to neutral.
- OpenCV camera overlay and optional Streamlit telemetry dashboard.
- Eight-byte serial packets with little-endian steering and an XOR checksum.

## Project location

The application source is in
[`files-pasted-by-the-user-markdown/outputs/spatial-kinematic-controller`](files-pasted-by-the-user-markdown/outputs/spatial-kinematic-controller).
Run the following commands from the repository's top-level folder.

## Setup

Use **Python 3.12 x64 on Windows**. Create your own environment rather than using
any virtual-environment folders included in this repository.

```powershell
Set-Location -LiteralPath '.\files-pasted-by-the-user-markdown\outputs\spatial-kinematic-controller' -ErrorAction Stop
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe run.py --dry-run
```

The dry run shows landmarks and gesture values without controlling a game.
Hold your palm toward the camera, keep the hand upright, and press **C** in the
camera window to calibrate steering center. Tilt left/right to steer and pinch
thumb/index together to increase throttle. Press **Q** or **Escape** in the
camera window to stop.

## Virtual Xbox controller

Install the optional package and complete the ViGEmBus driver installer if it opens:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gamepad.txt
.\.venv\Scripts\python.exe run.py --gamepad
```

Keep the app running and open **Win + R → `joy.cpl`** to check the virtual Xbox
controller. Gamepad mode maps steering to left stick X, pinch to right trigger,
and fist to button A. The game must accept Xbox controller input; in-game actions
depend on its bindings. Beach Buggy Racing is a candidate for checking steering,
but compatibility with that installed game has not been validated.

## Hill Climb Racing keyboard mode

No virtual-gamepad driver is needed for this mode:

```powershell
.\.venv\Scripts\python.exe run.py --hill-climb
```

Click into Hill Climb Racing to focus the game. Pinch with your other fingers
extended to hold **Right Arrow** (accelerator), close your fist to hold **Left Arrow**
(brake), and open/remove your hand to release both. Press **Escape** to stop.
Arrow presses are enabled only when the focused window title contains `Hill Climb`.
Use `--keyboard-window 'Actual game title'` if your game or emulator has another title.

## Serial output and diagnostics

```powershell
.\.venv\Scripts\python.exe run.py --serial COM3 --headless
.\.venv\Scripts\python.exe run.py --diagnose
.\.venv\Scripts\python.exe -m streamlit run ui/dashboard.py -- --telemetry telemetry.json
```

Configure camera, filtering, gesture thresholds, and output timing in
[`settings.yaml`](files-pasted-by-the-user-markdown/outputs/spatial-kinematic-controller/config/settings.yaml).
See the [full application README](files-pasted-by-the-user-markdown/outputs/spatial-kinematic-controller/README.md)
for calibration, serial framing, dependency notes, and troubleshooting.

## Validation

**22 automated tests passed**, and a live ViGEmBus adapter check successfully created
an Xbox 360 controller and sent a neutral report. The measured live-camera run
processed **19.6 FPS with 57.8 ms p95 read-to-submit latency**. The intended sustained
60 FPS / below 25 ms end-to-end targets have not been achieved on the tested machine.
Read-to-submit timing excludes camera exposure and game polling.

See [VALIDATION.md](files-pasted-by-the-user-markdown/outputs/spatial-kinematic-controller/VALIDATION.md)
for the performed checks and remaining hardware/game validation.
