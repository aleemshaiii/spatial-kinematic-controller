# Validation — 14 October 2026

## ViGEmBus installation and live adapter check

The user completed the ViGEmBus installer. `vgamepad==0.1.0` is now installed in
the project environment and the ViGEmBus system driver reports Running. A live
adapter check created an Xbox 360 controller, sent a neutral stick/trigger/button
report, reset it, and disconnected cleanly. This check found and fixed a keyword
argument mismatch in the original adapter; float methods now use positional arguments.
All 22 tests passed after the fix. Racing-game recognition is still to be checked.
The initial driver-unavailable notes below describe the earlier validation state.

## Hill Climb Racing keyboard update

Added `--hill-climb`: pinch holds Right Arrow; fist holds Left Arrow; open/no hand
releases both. Input is gated by the foreground window title (`Hill Climb` by
default), and Escape stops the controller globally. No driver/dependency installation
is needed. Re-ran the complete suite: **22 tests passed**.

Eight additional tests cover accelerator hysteresis, no repeated key-down events,
brake priority and release-before-switch, focus loss, watchdog release, shutdown
release, failed injection cleanup, and Windows native INPUT layout / extended scan
code flags. Native window-title / Escape state calls were exercised read-only;
SendInput events were intercepted in tests, so no actual keys were injected.
In-game compatibility and gesture usability still need the user's installed game.

Implementation and functional checks completed on Windows x64 with the bundled
CPython 3.12.14 runtime, in a dedicated `.venv`. Core dependencies installed
successfully. `requirements-lock.txt` records the resolved versions.

## Automated checks

`python -m unittest discover -s tests -v`: **14 tests passed**.

- Exact One Euro constant-cutoff recurrence, variable frame intervals, adaptive
  speed response, timestamp rejection, and reset.
- Palm geometry, degenerate/nonfinite landmark rejection, scale-invariant pinch,
  center deadzone, trigger calibration, and fist hysteresis.
- Serial golden packet, quantization roundtrip, and checksum corruption rejection.
- Latest-frame replacement and camera thread shutdown; camera-open failure.
- Latest-output replacement, independent watchdog neutralization, stale-state
  suppression, final neutral state, and output-error propagation.
- Gamepad API mapping against a mock device and partial serial write failure.
- All application modules import; actual MediaPipe graph processes blank frames.

Separate PySerial `loop://` packet test: eight bytes sent and received, decoded
steering/throttle/button values match within quantization. This check uses a positive
write timeout because that emulator rejects the production zero-timeout setting.
Running the pipeline with zero-timeout `loop://` correctly produces an actionable
transport error and status 1; it is not evidence of physical COM-port validation.

## Real camera and inference checks

`python run.py --diagnose --duration 10`: **exit status 0**, 198 frames processed,
capture and MediaPipe inference initialized, telemetry saved, then clean shutdown.

| Measurement | Result |
| --- | --- |
| Negotiated format reported by DirectShow | 640×480, 60.00024 FPS |
| Measured capture FPS, final rolling window | 19.9 FPS |
| Processed FPS, final rolling window | 19.6 FPS |
| Read-to-submit latency, 198 frames, p95 | 57.8 ms |
| Inference duration, p95 | 54.1 ms |
| Frame age at inference start, p95 | 7.1 ms |
| Replaced unread captures, including startup | 20 |

OpenCV CPU threading was limited to one thread to reduce contention with MediaPipe.
A previous 15-second run processed 297 frames at 19.6 FPS with 68.0 ms p95 latency;
results vary with tracking conditions and host load. No controlled hand-motion
sequence was supplied, so these are startup/live-scene measurements, not calibrated
gesture accuracy tests. No camera images were retained.

`python run.py --diagnose --camera 99`: unavailable-camera message, **status 1**,
no Python traceback or unhandled exception.

## Acceptance limits and remaining hardware validation

**The requested sustained ≥60 FPS and <25 ms end-to-end targets are not met on
this machine.** The reported driver FPS is not the delivered rate. Inference p95
also exceeds the latency budget. True exposure-to-input latency was not measured;
the timestamps start after camera read, and outputs were disabled during live tests.
Meeting the targets requires a camera delivering 60 FPS under the operating exposure
and a faster inference path/host, followed by sustained physical latency tests.

No ViGEmBus system driver was detected. The optional vgamepad package was not installed
because its source build launches an interactive MSI driver installation. The Xbox
360 adapter is implemented and API-tested with a mock, but driver/game integration
is unverified. Install `requirements-gamepad.txt` and ViGEmBus to enable it.

No physical microcontroller/serial port was supplied; physical COM writes, receiver
watchdog, and actuation latency remain unverified. The OpenCV overlay and Streamlit
dashboard import successfully but have not received interactive visual QA. This
delivery is a runnable implementation with functional validation, not certification
of production readiness or the requested hardware performance budgets.
