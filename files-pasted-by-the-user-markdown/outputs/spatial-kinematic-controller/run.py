"""Bounded webcam -> Hands -> kinematics -> independent output workers."""
import argparse
from collections import deque
from contextlib import ExitStack
import logging
import math
import os
from pathlib import Path
import sys
import time
import cv2
import numpy as np
import yaml
from core.camera_stream import CameraStream
from core.tracker import HandTracker
from core.kinematics import Kinematics, geometry
from core.filters import OneEuroFilter
from controllers.base_controller import ControlState
from controllers.serial_sender import SerialSender
from controllers.virtual_gamepad import VirtualGamepad
from controllers.keyboard import KeyboardController
from ui import overlay
from ui.telemetry import Telemetry

ROOT = Path(__file__).resolve().parent


def load_config(path):
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("camera", "tracking", "kinematics", "filter", "outputs", "ui"):
        if not isinstance(config.get(key), dict):
            raise ValueError(f"missing configuration section {key}")
    if "SKC_CAMERA_INDEX" in os.environ:
        config["camera"]["index"] = int(os.environ["SKC_CAMERA_INDEX"])
    if "SKC_SERIAL_PORT" in os.environ:
        config["outputs"]["serial_port"] = os.environ["SKC_SERIAL_PORT"]
    c, t, u, o = (config[x] for x in ("camera", "tracking", "ui", "outputs"))
    if c["index"] < 0 or c["width"] <= 0 or c["height"] <= 0 or c["fps"] <= 0:
        raise ValueError("invalid camera index/dimensions/fps")
    if len(c["fourcc"]) != 4 or c["startup_timeout_s"] <= 0 or c["stall_timeout_s"] <= 0:
        raise ValueError("invalid camera timing/fourcc")
    if t["max_hands"] not in (1, 2) or t["model_complexity"] not in (0, 1):
        raise ValueError("invalid hand count/model complexity")
    if not all(0 <= t[x] <= 1 for x in ("min_detection_confidence", "min_tracking_confidence")):
        raise ValueError("invalid tracking confidence")
    if u["telemetry_interval_s"] <= 0 or not 0 < o["heartbeat_s"] <= o["watchdog_s"]:
        raise ValueError("invalid telemetry/output timing")
    if o["serial_baud"] <= 0:
        raise ValueError("serial baud must be positive")
    for section, key in ((o, "gamepad"), (o, "serial"), (u, "overlay")):
        if not isinstance(section[key], bool):
            raise ValueError(f"{key} must be a YAML boolean")
    for section in config.values():
        for value in section.values():
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError("configuration numbers must be finite")
    return config


def execute(args):
    # Avoid OpenCV spinning up a CPU pool alongside the inference graph.
    cv2.setNumThreads(1)
    config = load_config(args.config)
    kinematics = Kinematics(**config["kinematics"])
    roll_filter = OneEuroFilter(**config["filter"])
    pinch_filter = OneEuroFilter(**config["filter"])
    out = config["outputs"]
    if args.camera is not None:
        config["camera"]["index"] = args.camera
    display = config["ui"]["overlay"] and not args.headless and not args.diagnose
    telemetry_path = Path(config["ui"]["telemetry_path"])
    if not telemetry_path.is_absolute():
        telemetry_path = ROOT / telemetry_path
    with ExitStack() as stack:
        camera = CameraStream(**config["camera"])
        stack.callback(camera.close)
        camera.start()
        logging.info("Camera negotiated: %s", camera.negotiated)
        tracker = HandTracker(**config["tracking"])
        stack.callback(tracker.close)
        drivers = []
        keyboard = None
        timings = dict(watchdog_s=out["watchdog_s"], heartbeat_s=out["heartbeat_s"])
        if not (args.dry_run or args.diagnose):
            if args.hill_climb:
                keyboard = KeyboardController(window_title=args.keyboard_window, **timings)
                stack.callback(keyboard.close)
                drivers.append(keyboard.start())
                logging.info("Arrow controls active only when a window containing %r is focused; Esc stops", args.keyboard_window)
            if args.gamepad or out["gamepad"]:
                driver = VirtualGamepad(**timings)
                stack.callback(driver.close)
                drivers.append(driver.start())
            if args.serial or out["serial"]:
                driver = SerialSender(args.serial or out["serial_port"], out["serial_baud"], **timings)
                stack.callback(driver.close)
                drivers.append(driver.start())
        telemetry = Telemetry(telemetry_path, config["ui"]["telemetry_interval_s"])
        stack.callback(telemetry.close)
        if display:
            stack.callback(overlay.close)
        logging.info("Pipeline ready; outputs=%s", [type(d).__name__ for d in drivers] or "dry run")
        sequence = 0
        start = last_frame = time.perf_counter()
        durations = deque(maxlen=600)
        frame_times = deque(maxlen=120)
        inference_times = deque(maxlen=600)
        frame_ages = deque(maxlen=600)
        last_hand = None
        previous_roll = unwrapped_roll = None
        count = 0
        snapshot = {}
        duration = args.duration if args.duration is not None else (5.0 if args.diagnose else None)
        try:
            while duration is None or time.perf_counter() - start < duration:
                if keyboard is not None and keyboard.escape_down():
                    break
                for driver in drivers:
                    if driver.error is not None:
                        raise RuntimeError(f"{type(driver).__name__} failed: {driver.error}")
                frame = camera.get_after(sequence, timeout=0.05)
                if frame is None:
                    if time.perf_counter() - last_frame > camera.stall_timeout_s:
                        raise RuntimeError("camera stalled; output watchdog neutralized controls")
                    continue
                last_frame = time.perf_counter()
                sequence = frame.sequence
                inference_start = time.perf_counter()
                frame_ages.append((inference_start - frame.timestamp) * 1000)
                hands = tracker.process(frame.image)
                inference_times.append((time.perf_counter() - inference_start) * 1000)
                # Select strongest detected hand. Reset state on handedness change.
                hand = max(hands, key=lambda h: h.confidence) if hands else None
                state, pose = ControlState(), None
                if hand is not None:
                    try:
                        h, w = frame.image.shape[:2]
                        pose = geometry(hand.normalized, w, h, hand.world, hand.handedness)
                    except ValueError:
                        hand = None
                if hand is None or hand.handedness != last_hand:
                    roll_filter.reset()
                    pinch_filter.reset()
                    kinematics.reset()
                    previous_roll = unwrapped_roll = None
                if hand is not None and pose is not None:
                    # Unwrap before filtering to avoid discontinuity at +/-180 degrees.
                    if previous_roll is None:
                        unwrapped_roll = pose.roll_deg
                    else:
                        unwrapped_roll += (pose.roll_deg - previous_roll + 180) % 360 - 180
                    previous_roll = pose.roll_deg
                    roll = roll_filter(unwrapped_roll, frame.timestamp)
                    pinch = pinch_filter(pose.pinch_ratio, frame.timestamp)
                    state = ControlState(*kinematics.map(roll, pinch, pose.fist_ratio))
                last_hand = hand.handedness if hand is not None else None
                # Suppress stale inference results even when an output is disabled.
                if time.perf_counter() - frame.timestamp > out["watchdog_s"]:
                    state = ControlState()
                for driver in drivers:
                    driver.submit(state, frame.timestamp)
                done = time.perf_counter()
                latency = (done - frame.timestamp) * 1000
                durations.append(latency)
                frame_times.append(done)
                count += 1
                fps = ((len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
                       if len(frame_times) > 1 else 0.0)
                snapshot = {"running": True, "updated_unix": time.time(), "frames": count,
                            "fps": fps, "latency_ms": latency,
                            "latency_p95_ms": float(np.percentile(durations, 95)),
                            "inference_p95_ms": float(np.percentile(inference_times, 95)),
                            "frame_age_p95_ms": float(np.percentile(frame_ages, 95)),
                            "capture_replacements": camera.replacements,
                            "capture_fps": camera.capture_fps,
                            "camera": camera.negotiated, "hand": last_hand,
                            "roll": state.roll, "throttle": state.throttle, "buttons": state.buttons,
                            "pitch_deg": pose.pitch_deg if pose else None,
                            "yaw_deg": pose.yaw_deg if pose else None,
                            "outputs": {type(d).__name__: {"read_to_dispatch_ms": d.last_dispatch_ms,
                                         "overwritten": d.overwritten} for d in drivers},
                            "telemetry_error": telemetry.error}
                if keyboard is not None:
                    snapshot["keyboard"] = dict(keyboard.status)
                telemetry.update(snapshot)
                if display:
                    key = overlay.show(frame.image, hand, snapshot, state)
                    if key in (27, ord("q")):
                        break
                    if key == ord("c") and pose is not None:
                        kinematics.neutral = pose.roll_deg
                        roll_filter.reset()
                        previous_roll = unwrapped_roll = None
                        logging.info("Neutral roll calibrated to %.1f degrees", pose.roll_deg)
        finally:
            # Explicit neutral publication; worker close also sends a final neutral.
            for driver in drivers:
                if driver.error is None:
                    driver.submit(ControlState(), time.perf_counter())
            snapshot.update(running=False, updated_unix=time.time())
            telemetry.update(snapshot)
        logging.info("Processed %d frames; FPS %.1f; read->submit p95 %.1f ms",
                     count, snapshot.get("fps", 0), snapshot.get("latency_p95_ms", 0))
        logging.info("Measured capture FPS %.1f; inference p95 %.1f ms; queue age p95 %.1f ms",
                     snapshot.get("capture_fps", 0), snapshot.get("inference_p95_ms", 0),
                     snapshot.get("frame_age_p95_ms", 0))
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--camera", type=int)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="suppress all hardware/gamepad outputs")
    parser.add_argument("--gamepad", action="store_true")
    parser.add_argument("--hill-climb", action="store_true", help="pinch: Right Arrow; fist: Left Arrow")
    parser.add_argument("--keyboard-window", default="Hill Climb", help="foreground game title substring for arrow controls")
    parser.add_argument("--serial", metavar="PORT")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--diagnose", action="store_true", help="5-second camera/inference check without outputs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error("duration must be positive and finite")
    try:
        return execute(args)
    except KeyboardInterrupt:
        logging.info("Stopped by user")
        return 0
    except Exception as exc:
        logging.error("Controller stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
