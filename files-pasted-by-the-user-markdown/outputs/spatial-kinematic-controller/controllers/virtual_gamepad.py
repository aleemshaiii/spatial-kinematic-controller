"""Xbox 360 output via vgamepad / ViGEmBus."""
from .base_controller import BaseController


class VirtualGamepad(BaseController):
    def __init__(self, watchdog_s=0.15, heartbeat_s=0.05):
        super().__init__(watchdog_s, heartbeat_s)
        try:
            import vgamepad as vg
            self.vg = vg
            self.device = vg.VX360Gamepad()
        except ModuleNotFoundError as exc:
            raise RuntimeError(f"Gamepad package missing ({exc.name}): run .\\.venv\\Scripts\\python.exe -m pip install -r requirements-gamepad.txt") from exc
        except Exception as exc:
            raise RuntimeError(f"Gamepad initialization failed ({type(exc).__name__}: {exc}). Check that ViGEmBus is installed and running") from exc

    def send(self, state):
        self.device.left_joystick_float(state.roll, 0.0)
        self.device.right_trigger_float(state.throttle)
        button = self.vg.XUSB_BUTTON.XUSB_GAMEPAD_A
        if state.buttons & 1:
            self.device.press_button(button=button)
        else:
            self.device.release_button(button=button)
        self.device.update()

    def release(self):
        self.device.reset()
        self.device.update()
        self.device = None
