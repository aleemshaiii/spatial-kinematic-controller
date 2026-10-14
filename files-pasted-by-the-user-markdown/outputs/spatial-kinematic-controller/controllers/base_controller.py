"""Latest-state output worker with independent tracking-loss watchdog."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import threading
import time


@dataclass(frozen=True)
class ControlState:
    roll: float = 0.0
    throttle: float = 0.0
    buttons: int = 0

    def __post_init__(self):
        if not math.isfinite(self.roll) or not -1 <= self.roll <= 1:
            raise ValueError("roll outside [-1, 1]")
        if not math.isfinite(self.throttle) or not 0 <= self.throttle <= 1:
            raise ValueError("throttle outside [0, 1]")
        if not isinstance(self.buttons, int) or not 0 <= self.buttons <= 255:
            raise ValueError("buttons outside [0, 255]")


class BaseController(ABC):
    def __init__(self, watchdog_s=0.15, heartbeat_s=0.05):
        if watchdog_s <= 0 or not 0 < heartbeat_s <= watchdog_s:
            raise ValueError("require 0 < heartbeat <= watchdog")
        self.watchdog_s, self.heartbeat_s = watchdog_s, heartbeat_s
        self.condition = threading.Condition()
        self.pending = None
        self.stopping = False
        self.thread = None
        self.error = None
        self.last_dispatch_ms = None
        self.dispatched = 0
        self.overwritten = 0

    def start(self):
        if self.thread is not None:
            raise RuntimeError("output already started")
        self.thread = threading.Thread(target=self._worker, name=type(self).__name__, daemon=True)
        self.thread.start()
        return self

    def submit(self, state, captured_at):
        if not math.isfinite(captured_at):
            raise ValueError("capture timestamp must be finite")
        with self.condition:
            if self.error:
                raise RuntimeError(f"{type(self).__name__}: {self.error}") from self.error
            if self.stopping:
                raise RuntimeError("output is closed")
            if self.pending is not None:
                self.overwritten += 1
            self.pending = (state, captured_at)
            self.condition.notify()

    def _worker(self):
        state, stamp = ControlState(), 0.0
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.pending is not None or self.stopping,
                                            timeout=self.heartbeat_s)
                    if self.stopping:
                        break
                    if self.pending is not None:
                        state, stamp = self.pending
                        self.pending = None
                now = time.perf_counter()
                fresh = now - stamp <= self.watchdog_s
                self.send(state if fresh else ControlState())
                completed = time.perf_counter()
                self.last_dispatch_ms = (completed - stamp) * 1000 if fresh else None
                self.dispatched += 1
        except Exception as exc:
            self.error = exc
        finally:
            try:
                self.send(ControlState())
            except Exception as exc:
                if self.error is None:
                    self.error = exc
            try:
                self.release()
            except Exception as exc:
                if self.error is None:
                    self.error = exc

    @abstractmethod
    def send(self, state):
        """Perform one bounded transport write on the worker thread."""
        raise NotImplementedError

    @abstractmethod
    def release(self):
        """Release transport resources after final neutral state."""
        raise NotImplementedError

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise RuntimeError("output worker failed to stop")
            if self.error:
                raise RuntimeError(f"{type(self).__name__} transport failed: {self.error}") from self.error
        else:
            self.release()
