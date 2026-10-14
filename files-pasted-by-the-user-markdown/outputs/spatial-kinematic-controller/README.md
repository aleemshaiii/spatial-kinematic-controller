# Low-Latency Spatial Vision & Kinematic Controller

Windows x64 webcam hand tracking with a single-slot DirectShow producer, MediaPipe
Hands inference, anatomical normalization, adaptive One Euro filtering, and independent
Xbox 360 / serial output workers. Camera reads, serial writes, and telemetry disk writes
run outside inference. Each output drops superseded states and neutralizes itself when
the last capture becomes older than the watchdog deadline.

## Setup in VS Code / PowerShell

Use **Python 3.12 x64**. MediaPipe is pinned to 0.10.21 for the requested legacy
`mediapipe.solutions.hands` API; newer releases are not assumed compatible.

The project created in this chat is at the following absolute path. Its Python
3.12 environment and core dependencies are already installed; run it directly:

```powershell
Set-Location -LiteralPath 'C:\Users\Dell\Documents\Codex\2026-10-14\files-pasted-by-the-user-markdown\outputs\spatial-kinematic-controller' -ErrorAction Stop
.\.venv\Scripts\python.exe run.py --diagnose
.\.venv\Scripts\python.exe run.py --dry-run
```

For a fresh checkout or extracted ZIP, first change to the actual project folder
containing `requirements.txt` and `run.py`, then run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe run.py --diagnose
.\.venv\Scripts\python.exe run.py --dry-run
```

An environment already provisioned by Codex may also be used directly with
`.\.venv\Scripts\python.exe`. The local environment is machine-specific and is
excluded from the source archive. Select that interpreter in VS Code.

MediaPipe depends on `opencv-contrib-python`, so this project uses that single cv2
provider instead of installing a competing `opencv-python` distribution. NumPy stays
below 2 for the selected MediaPipe release. The specification's `vgamepad>=0.3.3`
does not exist on PyPI; the published package is 0.1.0. It is isolated in
`requirements-gamepad.txt` because its Windows installation can launch the ViGEmBus
installer. Install that optional package and driver when enabling gamepad output:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gamepad.txt
.\.venv\Scripts\python.exe run.py --gamepad
.\.venv\Scripts\python.exe run.py --serial COM3 --headless
.\.venv\Scripts\python.exe run.py --gamepad --serial COM3
```

Outputs are disabled by default. `--dry-run` and `--diagnose` suppress all outputs,
including those enabled in YAML. `--diagnose` runs capture and real inference for
five seconds with no GUI. `--duration 10` bounds any run. Startup/runtime errors log
one actionable message and exit with status 1; Ctrl+C, Q, and Escape stop cleanly.

## Calibration and controls

### Hill Climb Racing (keyboard arrows)

No ViGEmBus or extra package installation is needed for this mode:

```powershell
.\.venv\Scripts\python.exe run.py --hill-climb
```

Start the controller, then click into Hill Climb Racing and start a race. Keep
your palm visible: pinch thumb/index together to hold Right Arrow (accelerator),
close your fist to hold Left Arrow (brake), and open/remove your hand to release
both. Keep the other fingers extended during a pinch so it is not classified as
a fist. Steering/roll is ignored in this mode. Keyboard acceleration is on/off:
it engages at trigger 0.65 and releases at 0.40, with hysteresis to reduce chatter.
Brake takes priority; both arrows are never intentionally held together.

Arrow presses are enabled only while the foreground window title contains
`Hill Climb` (case-insensitive). The overlay shows `Game focused`, `GAS`, and
`BRAKE`; focus loss releases held arrows. If the game uses another window title,
pass its identifying text with `--keyboard-window 'Actual game title'`. For example,
an emulator may use its emulator title instead of the game's title.

Press Escape to stop even while the game is focused, or Ctrl+C in the terminal.
The output watchdog releases held arrows after tracking stalls; normal shutdown
also releases them. Run the game and controller with matching privilege levels.
Windows can reject injected input into applications with greater privileges, and
some games do not accept injected keyboard events. This adapter uses the native
[Windows SendInput API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)
with extended arrow scan codes. End-to-end game compatibility requires testing
in your installed game. Avoid using physical arrow keys simultaneously with gestures.

Edit `config/settings.yaml`. Default capture requests MJPEG 640x480 at 60 FPS;
try 1280x720 if your camera supports it. Drivers may ignore buffer size / FPS requests;
the negotiated format is logged. The application keeps only the newest unread frame.
No automatic mode enumeration is implied by a requested FPS.

Hold one hand upright, palm visible. Wrist-to-middle-MCP pointing upward is -90°
in unmirrored image coordinates. Roll maps to left stick X, ±60° from neutral maps
to full travel, and the center deadzone is rescaled to avoid a discontinuity. Press C
in the overlay to calibrate the current roll to center (session only). Change
`steering_sign` to -1 to reverse steering.

Thumb/index distance is normalized by index/little MCP width. Closing the pinch
increases right trigger; tune `pinch_closed` / `pinch_open` to your hand. A mean
fingertip-to-wrist / MCP-to-wrist ratio estimates a closed fist with hysteresis,
mapped to button A / handbrake. Fist suppresses throttle. This is a geometric
heuristic, requiring calibration for individual hands and camera angles.

World landmarks are used for 3D distances and palm normals when available. Image
landmarks have their aspect ratio corrected (x and z scaled by width, y by height).
Roll uses image x/y. Pitch is the palm normal's 0–180° angle to +Z camera optic axis;
yaw is atan2(normal.x, normal.z), with normal sign canonicalized by handedness.
MediaPipe handedness labels assume mirrored input; capture here is unmirrored,
so physical left/right labels may be swapped. Relative controls are unaffected,
but absolute orientation conventions should be calibrated before use.

No hand or invalid geometry publishes neutral immediately. Filters reset after
tracking loss or a handedness change, and roll unwraps across ±180° before smoothing.
With two hands enabled, the strongest detection is selected; keep one control hand
visible for predictable identity. This is not persistent multi-hand identity tracking.

## Serial receiver contract

Eight bytes at 115200 baud, 8N1:

| Offset | Meaning |
| --- | --- |
| 0, 1 | AA BB header |
| 2, 3 | signed int16 little-endian steering, -32767..32767 |
| 4 | uint8 throttle, 0..255 |
| 5 | buttons mask: bit 0 = A / handbrake |
| 6 | XOR of bytes 2 through 5 |
| 7 | CC footer |

The detailed packet requirement specifies **XOR**, not a CRC. `encode_packet` and
`decode_packet` implement that exact format. Full right / full throttle / A produces
`AA BB FF 7F FF 01 7E CC`. A receiver must find the header, consume exactly eight
bytes, validate footer/XOR, and resynchronize on malformed input; payloads can contain
header/footer byte values. Quantization uses nearest integer.

Writes on physical COM ports have a zero timeout; full buffers, partial writes, and disconnects fail the
output worker and terminate the application. The host attempts a final neutral
packet, but cannot guarantee delivery after disconnection. Firmware must apply an
independent timeout (e.g. 200 ms) that neutralizes hardware if valid packets stop.
The host sends heartbeat states every 50 ms and neutral after 150 ms without a fresh
capture. Serial submission completion measures host buffering, not receiver actuation.

## Diagnostics and performance

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui/dashboard.py -- --telemetry telemetry.json
```

The separate dashboard reads an atomic JSON snapshot once per second. It displays
measured capture/processed FPS, read-to-submit p95, dropped captures, and each enabled output's latest
read-to-dispatch time. Disk writing occurs on a telemetry worker. Dashboard failure
does not stop input dispatch. `telemetry.json` is written relative to the project;
`.env.example` documents process environment overrides, but is not loaded automatically.

**60 FPS and <25 ms are acceptance targets, not guaranteed results.** A 30 FPS webcam,
slow CPU, camera exposure/USB buffering, reacquisition, or an overlay can exceed these
budgets. One Euro filtering reduces the jitter/lag tradeoff; it cannot provide zero
phase delay or recover missing information. Monocular world coordinates estimate 3D
geometry and do not provide calibrated metric depth or precision guarantees.

Capture timestamps are taken immediately after `VideoCapture.read()`, not at exposure.
Read-to-submit includes queue age, inference, geometry, filtering, and output enqueue;
the output metric includes dispatch scheduling and the driver call. Neither includes
camera exposure/buffering or the game's input polling. Use an external high-speed
camera/LED measurement to validate true physical end-to-end latency. Run headless
with outputs enabled on target hardware for sustained acceptance testing; compare
processed throughput and dispatch latency under both tracking and reacquisition.
Watchdog timing is best effort under OS scheduling and cannot interrupt a blocked
native driver call. DirectShow read can hang; capture shutdown is bounded and logs it.

PySerial's `loop://` emulator models transmission time and rejects a zero write
timeout; it is not a supported nonblocking runtime output. Packet loopback checks
can use it separately with a positive write timeout.

## Dependency references

- [MediaPipe 0.10.21 wheels / Python support](https://pypi.org/project/mediapipe/0.10.21/)
- [MediaPipe Hands landmark semantics](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/hands.md)
- [vgamepad installation and driver](https://pypi.org/project/vgamepad/)
- [One Euro filter reference](https://gery.casiez.net/1euro/)

See `VALIDATION.md` for the actual checks performed on this machine.
