"""Atomic telemetry snapshots off the inference path."""
import json
import os
from pathlib import Path
import threading


class Telemetry:
    def __init__(self, path, interval=0.5):
        self.path = Path(path)
        self.interval = interval
        self.lock = threading.Lock()
        self.snapshot = {}
        self.error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._worker, name="telemetry", daemon=True)
        self.thread.start()

    def update(self, snapshot):
        with self.lock:
            self.snapshot = dict(snapshot)

    def _write(self):
        with self.lock:
            snapshot = dict(self.snapshot)
        if snapshot:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(snapshot, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(temporary, self.path)

    def _worker(self):
        try:
            while not self.stop.wait(self.interval):
                self._write()
            self._write()
        except Exception as exc:
            self.error = str(exc)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
