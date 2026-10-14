import ctypes
import time
import unittest
from controllers.base_controller import ControlState
from controllers.keyboard import KeyboardController, WindowsKeyboard, INPUT, LEFT, RIGHT


class FakeKeyboard:
    def __init__(self):
        self.title = "Hill Climb Racing"
        self.events = []
    def foreground_title(self):
        return self.title
    def key(self, key, down):
        self.events.append((key, down))
    def escape_down(self):
        return False


class KeyboardTests(unittest.TestCase):
    def make(self):
        backend = FakeKeyboard()
        return KeyboardController(backend=backend), backend

    def test_hold_hysteresis_and_no_duplicate_presses(self):
        d, b = self.make()
        for throttle in (.1, .8, 1, .5, .4):
            d.send(ControlState(throttle=throttle))
        self.assertEqual(b.events, [(RIGHT, True), (RIGHT, False)])
        d.close()

    def test_brake_priority_and_release_before_switch(self):
        d, b = self.make()
        d.send(ControlState(throttle=1))
        d.send(ControlState(throttle=1, buttons=1))
        d.send(ControlState())
        self.assertEqual(b.events, [(RIGHT, True), (RIGHT, False), (LEFT, True), (LEFT, False)])
        d.close()

    def test_focus_loss_releases_and_blocks_keys(self):
        d, b = self.make()
        d.send(ControlState(throttle=1))
        b.title = "PowerShell"
        d.send(ControlState(throttle=1))
        d.send(ControlState(buttons=1))
        self.assertEqual(b.events, [(RIGHT, True), (RIGHT, False)])
        self.assertFalse(d.status["focused"])
        d.close()

    def test_watchdog_releases_held_arrow(self):
        b = FakeKeyboard()
        d = KeyboardController(backend=b, watchdog_s=.03, heartbeat_s=.005)
        d.submit(ControlState(throttle=1), time.perf_counter())
        d.start()
        try:
            deadline = time.perf_counter() + 1
            while (RIGHT, False) not in b.events and time.perf_counter() < deadline:
                time.sleep(.005)
            self.assertEqual(b.events, [(RIGHT, True), (RIGHT, False)])
        finally:
            d.close()

    def test_close_releases_brake(self):
        d, b = self.make()
        d.send(ControlState(buttons=1))
        d.close()
        self.assertEqual(b.events, [(LEFT, True), (LEFT, False)])

    def test_native_abi_and_read_only_backend(self):
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        native = WindowsKeyboard()
        self.assertIsInstance(native.foreground_title(), str)
        self.assertIsInstance(native.escape_down(), bool)

    def test_native_extended_scancode_flags_without_injection(self):
        from unittest.mock import MagicMock
        native = WindowsKeyboard()
        captured = []
        def fake_send(count, pointer, size):
            event = ctypes.cast(pointer, ctypes.POINTER(INPUT)).contents
            captured.append((event.type, event.ki.wScan, event.ki.dwFlags, size))
            return 1
        native.api = MagicMock()
        native.api.SendInput.side_effect = fake_send
        native.key(RIGHT, True)
        native.key(RIGHT, False)
        self.assertEqual(captured, [(1, RIGHT, 9, ctypes.sizeof(INPUT)), (1, RIGHT, 11, ctypes.sizeof(INPUT))])

    def test_failed_down_is_released_on_cleanup(self):
        d, b = self.make()
        original = b.key
        def fail_down(key, down):
            if down:
                raise OSError("injection blocked")
            original(key, down)
        b.key = fail_down
        with self.assertRaises(OSError):
            d.send(ControlState(throttle=1))
        d.close()
        self.assertEqual(b.events, [(RIGHT, False)])
