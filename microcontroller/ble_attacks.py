"""Bridge decoded BLE punch events to short controller button presses."""
import asyncio
from collections import deque
import math
import threading
import time

import IMU_client as imu_client
import punch_detector


PUNCH_INPUTS = {
    "LEFT_STRAIGHT": "light",
    "LEFT_UPPERCUT": "medium",
    "RIGHT_STRAIGHT": "heavy",
    "RIGHT_UPPERCUT": "special",
}


class BLEAttacks:
    """Read BLE on a worker thread; the webcam loop polls held() for buttons."""

    def __init__(self, pulse_seconds=0.10, sample_timeout=0.5, queue_timeout=0.5):
        for value in (pulse_seconds, sample_timeout, queue_timeout):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("BLE attack timeouts must be finite and positive")
        self.pulse_seconds = pulse_seconds
        self.sample_timeout = sample_timeout
        self.queue_timeout = queue_timeout
        self.lock = threading.RLock()
        self.queue = deque(maxlen=16)
        self.active = None
        self.active_until = 0.0
        self.last_sample_at = None
        self.error = None
        self.stop = threading.Event()
        self.loop = self.task = None
        self.thread = threading.Thread(target=self._read, name="ESP32-BLE", daemon=True)
        self._installed = False

    def _receive(self, event):
        if event in PUNCH_INPUTS:
            with self.lock:
                self.queue.append((event, time.monotonic()))

    def _reset(self):
        with self.lock:
            self.queue.clear()
            self.active = None
            self.last_sample_at = None
            for detector in punch_detector.detectors.values():
                detector.reset()

    def _handle_sample(self, t_ms, imu_ok, deltas, gyros=None):
        with self.lock:
            self.last_sample_at = time.monotonic()
            for i, hand in ((0, "RIGHT"), (1, "LEFT")):
                if not imu_ok[i]:
                    self.queue = deque((item for item in self.queue
                                        if not item[0].startswith(hand + "_")), maxlen=16)
                    if self.active and self.active.startswith(hand + "_"):
                        self.active = None
            punch_detector.handle_sample(t_ms, imu_ok, deltas, gyros)

    def held(self):
        with self.lock:
            if self.error is not None:
                raise RuntimeError(f"BLE reader failed: {self.error}") from self.error
            now = time.monotonic()
            if self.last_sample_at is None or now - self.last_sample_at > self.sample_timeout:
                self._reset()
                return set()
            if self.active is not None:
                if now < self.active_until:
                    return {PUNCH_INPUTS[self.active]}
                self.active = None
                # Return a released frame before pressing even the same button again.
                return set()
            while self.queue:
                event, received_at = self.queue.popleft()
                if now - received_at > self.queue_timeout:
                    continue
                self.active = event
                self.active_until = now + self.pulse_seconds
                return {PUNCH_INPUTS[event]}
            return set()

    def _read(self):
        async def consume():
            with self.lock:
                self.loop = asyncio.get_running_loop()
                self.task = asyncio.current_task()
            if not self.stop.is_set():
                await imu_client.run(on_disconnect=self._reset)

        try:
            asyncio.run(consume())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            with self.lock:
                self.error = exc
        finally:
            self._reset()
            with self.lock:
                self.loop = self.task = None

    def __enter__(self):
        self._reset()
        self._original_sample = imu_client.handle_sample
        self._original_punch = punch_detector.on_punch
        imu_client.handle_sample = self._handle_sample
        punch_detector.on_punch = self._receive
        self._installed = True
        try:
            self.thread.start()
        except BaseException:
            self._restore_handlers()
            raise
        return self

    def _restore_handlers(self):
        if self._installed:
            imu_client.handle_sample = self._original_sample
            punch_detector.on_punch = self._original_punch
            self._installed = False

    def close(self):
        self.stop.set()
        with self.lock:
            loop, task = self.loop, self.task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The worker already closed its event loop.
        if self.thread.ident is not None:
            self.thread.join(timeout=5)
        self._reset()
        if self.thread.is_alive():
            raise RuntimeError("BLE worker did not stop within five seconds")
        self._restore_handlers()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
