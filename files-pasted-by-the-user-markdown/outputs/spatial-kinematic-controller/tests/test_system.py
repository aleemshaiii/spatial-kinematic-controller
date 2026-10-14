"""Deterministic geometry/protocol/concurrency tests, without hardware."""
import math
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
from core.filters import OneEuroFilter
from core.camera_stream import CameraStream
from core.kinematics import Kinematics, deadzone, geometry
from controllers.base_controller import BaseController, ControlState
from controllers.serial_sender import encode_packet, decode_packet, SerialSender
from controllers.virtual_gamepad import VirtualGamepad
from run import load_config


class Recorder(BaseController):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sent = []
        self.event = threading.Event()
        self.released = False

    def send(self, state):
        self.sent.append(state)
        self.event.set()

    def release(self):
        self.released = True


def points():
    p = np.zeros((21, 3))
    p[0] = (.5, .9, 0)
    p[5] = (.35, .6, 0)
    p[9] = (.5, .55, 0)
    p[13] = (.6, .6, 0)
    p[17] = (.7, .65, 0)
    p[4] = (.3, .3, 0)
    for i, x in zip((8, 12, 16, 20), (.35, .5, .6, .7)):
        p[i] = (x, .2, 0)
    return p


class SystemTests(unittest.TestCase):
    def test_filter_exact_step_and_variable_dt(self):
        f = OneEuroFilter(1, 0, 1)
        self.assertEqual(f(0, 1), 0)
        a = .1 / (.1 + 1 / (2 * math.pi))
        self.assertAlmostEqual(f(1, 1.1), a)
        b = .02 / (.02 + 1 / (2 * math.pi))
        self.assertAlmostEqual(f(1, 1.12), b + (1 - b) * a)
        with self.assertRaises(ValueError):
            f(1, 1.12)
        f.reset()
        self.assertEqual(f(7, 0), 7)

    def test_filter_adapts_to_fast_motion(self):
        slow = OneEuroFilter(1, 0, 1)
        fast = OneEuroFilter(1, .5, 1)
        slow(0, 0)
        fast(0, 0)
        self.assertGreater(fast(100, .016), slow(100, .016))

    def test_geometry_aspect_and_depth_invariance(self):
        p = points()
        base = geometry(p, 640, 480)
        self.assertAlmostEqual(base.roll_deg, -90)
        self.assertTrue(0 <= base.pitch_deg <= 180)
        scaled = p * .4 + np.array([.1, .1, .1])
        other = geometry(scaled, 640, 480)
        self.assertAlmostEqual(base.pinch_ratio, other.pinch_ratio)
        self.assertAlmostEqual(base.fist_ratio, other.fist_ratio)
        with self.assertRaises(ValueError):
            geometry(np.zeros((21, 3)), 640, 480)
        p[1, 0] = np.nan
        with self.assertRaises(ValueError):
            geometry(p, 640, 480)

    def test_deadzone_pinch_and_fist_hysteresis(self):
        k = Kinematics()
        self.assertEqual(deadzone(.02, .06), 0)
        self.assertEqual(deadzone(1, .06), 1)
        self.assertEqual(k.map(-90, .15, 2), (0, 1, 0))
        self.assertEqual(k.map(-90, 1.1, 2), (0, 0, 0))
        self.assertEqual(k.map(-30, .15, .8), (1, 0, 1))
        self.assertEqual(k.map(-90, .15, 1.0)[2], 1)
        self.assertEqual(k.map(-90, .15, 1.2)[2], 0)

    def test_serial_golden_bytes_roundtrip_and_corruption(self):
        state = ControlState(1, 1, 1)
        self.assertEqual(encode_packet(state), bytes.fromhex("aa bb ff 7f ff 01 7e cc"))
        for s in (state, ControlState(), ControlState(-1, .5, 0xA5)):
            decoded = decode_packet(encode_packet(s))
            self.assertAlmostEqual(s.roll, decoded.roll, delta=1 / 32767)
            self.assertAlmostEqual(s.throttle, decoded.throttle, delta=1 / 255)
            self.assertEqual(s.buttons, decoded.buttons)
        bad = bytearray(encode_packet(state))
        bad[3] ^= 1
        with self.assertRaises(ValueError):
            decode_packet(bad)

    def test_latest_output_slot_and_watchdog_neutral(self):
        r = Recorder(watchdog_s=.03, heartbeat_s=.005)
        r.submit(ControlState(.2, .1, 0), time.perf_counter())
        r.submit(ControlState(.8, .7, 1), time.perf_counter())
        self.assertEqual(r.overwritten, 1)
        r.start()
        try:
            self.assertTrue(r.event.wait(1))
            self.assertEqual(r.sent[0], ControlState(.8, .7, 1))
            deadline = time.perf_counter() + 1
            while r.sent[-1] != ControlState() and time.perf_counter() < deadline:
                time.sleep(.005)
            self.assertEqual(r.sent[-1], ControlState())
        finally:
            r.close()
        self.assertTrue(r.released)
        self.assertEqual(r.sent[-1], ControlState())

    def test_stale_state_suppressed(self):
        r = Recorder()
        r.submit(ControlState(1, 1, 1), time.perf_counter() - 1)
        r.start()
        try:
            self.assertTrue(r.event.wait(1))
            self.assertEqual(r.sent[0], ControlState())
        finally:
            r.close()

    def test_output_error_propagated(self):
        class Broken(Recorder):
            def send(self, state):
                self.event.set()
                raise OSError("disconnected")
        r = Broken(heartbeat_s=.001)
        r.start()
        self.assertTrue(r.event.wait(1))
        r.thread.join(1)
        with self.assertRaises(RuntimeError):
            r.submit(ControlState(), time.perf_counter())
        with self.assertRaises(RuntimeError):
            r.close()
        self.assertTrue(r.released)

    def test_camera_latest_frame_and_shutdown(self):
        class Capture:
            def __init__(self, *args):
                self.n = 0
                self.released = False
            def isOpened(self):
                return True
            def set(self, *args):
                return True
            def get(self, *args):
                return 60
            def read(self):
                time.sleep(.002)
                self.n += 1
                return True, np.full((2, 2, 3), self.n % 256, np.uint8)
            def release(self):
                self.released = True
        cap = Capture()
        with patch("core.camera_stream.cv2.VideoCapture", return_value=cap):
            c = CameraStream().start()
            try:
                first = c.get_after(0)
                time.sleep(.03)
                last = c.get_after(first.sequence)
                self.assertGreater(last.sequence, first.sequence + 1)
                self.assertGreater(c.replacements, 0)
                self.assertGreater(last.timestamp, first.timestamp)
            finally:
                c.close()
        self.assertTrue(cap.released)
        self.assertFalse(c.thread.is_alive())

    def test_camera_open_failure_is_reported(self):
        from unittest.mock import MagicMock
        cap = MagicMock()
        cap.isOpened.return_value = False
        with patch("core.camera_stream.cv2.VideoCapture", return_value=cap):
            c = CameraStream()
            with self.assertRaisesRegex(RuntimeError, "cannot open camera"):
                c.start()
            c.close()
        cap.release.assert_called_once()

    def test_real_inference_on_blank_frames(self):
        from core.tracker import HandTracker
        tracker = HandTracker()
        try:
            for _ in range(3):
                self.assertEqual(tracker.process(np.zeros((480, 640, 3), dtype=np.uint8)), [])
        finally:
            tracker.close()

    def test_gamepad_mapping_with_mock_device(self):
        from unittest.mock import MagicMock
        vg = MagicMock()
        with patch.dict("sys.modules", vgamepad=vg):
            driver = VirtualGamepad()
            driver.send(ControlState(.5, .3, 1))
            device = vg.VX360Gamepad.return_value
            device.left_joystick_float.assert_called_with(.5, 0)
            device.right_trigger_float.assert_called_with(.3)
            device.press_button.assert_called_once()
            driver.send(ControlState())
            device.release_button.assert_called_once()
            driver.close()

    def test_serial_partial_write_fails(self):
        from unittest.mock import MagicMock
        device = MagicMock()
        device.write.return_value = 3
        with patch("serial.serial_for_url", return_value=device):
            driver = SerialSender("loop://")
            with self.assertRaises(RuntimeError):
                driver.send(ControlState())
            driver.close()

    def test_config_and_module_imports(self):
        cfg = load_config(Path(__file__).resolve().parents[1] / "config/settings.yaml")
        self.assertFalse(cfg["outputs"]["gamepad"])
        import ui.dashboard
        import ui.overlay
        self.assertTrue(callable(ui.dashboard.main))


if __name__ == "__main__":
    unittest.main()
