"""Windows arrow-key output for Hill Climb Racing; no extra dependencies."""
import ctypes
from ctypes import wintypes
import sys
from .base_controller import BaseController

RIGHT = 0x4D
LEFT = 0x4B


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]


class WindowsKeyboard:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Hill Climb keyboard mode requires Windows")
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.api.SendInput.restype = wintypes.UINT
        self.api.GetForegroundWindow.argtypes = []
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.api.GetWindowTextW.restype = ctypes.c_int
        self.api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.api.GetAsyncKeyState.restype = wintypes.SHORT

    def foreground_title(self):
        title = ctypes.create_unicode_buffer(1024)
        self.api.GetWindowTextW(self.api.GetForegroundWindow(), title, len(title))
        return title.value

    def escape_down(self):
        return bool(self.api.GetAsyncKeyState(0x1B) & 0x8000)

    def key(self, scan_code, down):
        # Arrows are extended scan codes; INPUT includes the full native union.
        event = INPUT(type=1)
        event.ki = KEYBDINPUT(0, scan_code, 0x0008 | 0x0001 | (0 if down else 0x0002), 0, 0)
        ctypes.set_last_error(0)
        if self.api.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise OSError(ctypes.get_last_error(), "Windows rejected keyboard input; check game privilege level")


class KeyboardController(BaseController):
    def __init__(self, window_title="Hill Climb", throttle_press=0.65,
                 throttle_release=0.4, watchdog_s=0.15, heartbeat_s=0.05, backend=None):
        super().__init__(watchdog_s, heartbeat_s)
        if not window_title.strip():
            raise ValueError("keyboard window title cannot be empty")
        if not 0 <= throttle_release < throttle_press <= 1:
            raise ValueError("require 0 <= throttle release < press <= 1")
        self.backend = WindowsKeyboard() if backend is None else backend
        self.window_title = window_title.casefold()
        self.press, self.release_threshold = throttle_press, throttle_release
        self.held = set()
        self.status = {"focused": False, "accelerator": False, "brake": False}

    def send(self, state):
        focused = self.window_title in self.backend.foreground_title().casefold()
        desired = set()
        if focused:
            if state.buttons & 1:
                desired.add(LEFT)
            elif state.throttle >= (self.release_threshold if RIGHT in self.held else self.press):
                # Use a strict release edge so a zero throttle always releases.
                if state.throttle > self.release_threshold or state.throttle >= self.press:
                    desired.add(RIGHT)
        # Release before pressing; accelerator and brake are never held together.
        for key in sorted(self.held - desired):
            self.backend.key(key, False)
            self.held.remove(key)
        for key in sorted(desired - self.held):
            # Track attempted downs too, so an ambiguous failure gets a release retry.
            self.held.add(key)
            self.backend.key(key, True)
        self.status = {"focused": focused, "accelerator": RIGHT in self.held,
                       "brake": LEFT in self.held}

    def escape_down(self):
        return self.backend.escape_down()

    def release(self):
        errors = []
        for key in list(self.held):
            try:
                self.backend.key(key, False)
                self.held.remove(key)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError("could not release held arrow keys") from errors[0]
