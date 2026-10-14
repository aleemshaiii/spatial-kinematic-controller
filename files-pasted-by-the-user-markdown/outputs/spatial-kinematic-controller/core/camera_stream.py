"""Dedicated DirectShow producer with a single replaceable frame slot."""
from dataclasses import dataclass
from collections import deque
import threading
import time
import sys
import cv2


@dataclass(frozen=True)
class Frame:
    image: object
    timestamp: float  # perf_counter immediately after read; NOT exposure timestamp
    sequence: int


class CameraStream:
    def __init__(self, index=0, width=640, height=480, fps=60, fourcc="MJPG",
                 startup_timeout_s=10, stall_timeout_s=1):
        self.index, self.width, self.height, self.fps = index, width, height, fps
        self.fourcc = fourcc
        self.startup_timeout_s = startup_timeout_s
        self.stall_timeout_s = stall_timeout_s
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.latest = None
        self.error = None
        self.thread = None
        self.negotiated = {}
        self.replacements = 0
        self.last_consumed = 0
        self.capture_fps = 0.0

    def start(self):
        if self.thread is not None:
            raise RuntimeError("camera is already started")
        self.thread = threading.Thread(target=self._capture, name="camera", daemon=True)
        self.thread.start()
        if self.get_after(0, self.startup_timeout_s) is None:
            self.close()
            raise RuntimeError("camera startup timed out; check camera permissions/index")
        return self

    def _capture(self):
        cap = None
        try:
            backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            cap = cv2.VideoCapture(self.index, backend)
            if not cap.isOpened():
                raise RuntimeError(f"cannot open camera {self.index}")
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # best effort; many DShow drivers ignore it
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            self.negotiated = {"width": cap.get(cv2.CAP_PROP_FRAME_WIDTH),
                               "height": cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
                               "fps": cap.get(cv2.CAP_PROP_FPS)}
            sequence, failures = 0, 0
            timestamps = deque(maxlen=120)
            while not self.stop_event.is_set():
                ok, image = cap.read()
                stamp = time.perf_counter()
                if not ok or image is None:
                    failures += 1
                    if failures >= 10:
                        raise RuntimeError("camera stopped delivering frames")
                    self.stop_event.wait(0.01)
                    continue
                failures = 0
                sequence += 1
                timestamps.append(stamp)
                with self.condition:
                    if len(timestamps) > 1:
                        self.capture_fps = (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])
                    if self.latest is not None and self.latest.sequence > self.last_consumed:
                        self.replacements += 1
                    self.latest = Frame(image, stamp, sequence)
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = exc
                self.condition.notify_all()
        finally:
            if cap is not None:
                cap.release()

    def get_after(self, sequence, timeout=0.1):
        with self.condition:
            self.condition.wait_for(lambda: self.error is not None or self.stop_event.is_set()
                                    or (self.latest is not None and self.latest.sequence > sequence), timeout)
            if self.error is not None:
                raise RuntimeError(str(self.error)) from self.error
            if self.latest is not None and self.latest.sequence > sequence:
                self.last_consumed = self.latest.sequence
                return self.latest
            return None

    def close(self):
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                # Native camera read can hang; the output watchdog is independent.
                import logging
                logging.warning("Camera read did not exit within 2 seconds")
