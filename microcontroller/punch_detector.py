"""
Punch classifier built on imu_client.py.

IMU2 = left hand  -> JAB
IMU1 = right hand -> CROSS

Output includes hand, STRAIGHT/HOOK and LIGHT/HARD. Hooks require a confirmed
acceleration burst plus sustained gyroscope rotation. This is an experimental
heuristic; tune each hand with its sensor secured in a consistent orientation.
Legacy acceleration-only firmware supports straight punches only.

How a punch is counted
----------------------
A punch has two phases: the extension (out) and the retraction (back). Either one
can be the fast part, so BOTH are treated as punch evidence:

  * A short burst must contain a strong peak (dmag >= onset_g) and at least
    confirm_samples consecutive samples above sustain_g, spanning confirm_ms.
    One reversal in acceleration change is allowed; repeated strong reversals
    are rejected as likely vibration. These are heuristics: delta-only packets cannot
    reliably identify every tap versus punch. The burst can come from either
    extension or retraction.
  * Confirmation opens a "cycle window" (cycle_window_ms). Any spike inside the window
    is treated as the other half of the SAME punch and ignored. This is what stops a
    fast punch + fast retraction from counting twice.
  * After the window, the hand re-arms only once it has been quiet for
    rearm_samples samples in a row, so a slow drift back to rest never fires.

Put this file in the same folder as imu_client.py and run:
    py punch_detector.py
"""
import asyncio
import math
from collections import deque

import imu_client

VERBOSE = False  # True = also print every raw sample (imu_client's default output)
METER = False    # True = print any sample with dmag above METER_MIN_G, to help tune onset_g
METER_MIN_G = 0.05

# ---- Tuning ----------------------------------------------------------------
# Values are acceleration CHANGE per sample in g, not absolute acceleration.
# Defaults target the supplied sketch's SAMPLE_MS=10 (about 100 Hz).
# onset_g         : minimum peak dmag in a confirmed burst
# hard_g          : confirmed acceleration-change peak for HARD (not impact force)
# hook_gyro_dps   : minimum rotational speed for a hook
# hook_turn_deg   : minimum net rotation in the recent hook_window_ms
# hook_axis       : None = use all axes; 0/1/2 = use sensor X/Y/Z. Selecting the
#                   hook's sweep axis can help exclude wrist rolls.
# hook_window_ms  : gyro history leading up to punch confirmation
# sustain_g       : minimum dmag for each consecutive sample in the burst
# confirm_samples : minimum number of consecutive active samples
# confirm_ms      : minimum duration of the burst (uses the ESP32 timestamps)
# max_reversals   : allowed strong reversals between consecutive delta vectors.
#                   One allows acceleration then deceleration; repeated reversals
#                   suggest vibration. A reversal means an angle greater than 120
#                   degrees in acceleration CHANGE, not hand travel direction.
# max_gap_ms      : discard pending confirmation / quiet streak across data gaps
# rearm_g         : dmag must stay below this to re-arm after the window
# rearm_samples   : ...for this many samples in a row
# cycle_window_ms : after a punch fires, spikes within this time are the same punch
#                   (its retraction). Too short -> retraction double-fires.
#                   Too long -> a quick second punch from the same hand is missed.
CONFIG = {
    0: dict(label="CROSS", imu="IMU1", onset_g=0.45, rearm_g=0.06, rearm_samples=4,
            cycle_window_ms=300, sustain_g=0.15, confirm_samples=4, confirm_ms=30,
            max_gap_ms=50, max_reversals=1, hand="RIGHT", hard_g=0.90,
            hook_gyro_dps=180, hook_turn_deg=12, hook_axis=None, hook_window_ms=120),
    1: dict(label="JAB",   imu="IMU2", onset_g=0.45, rearm_g=0.06, rearm_samples=4,
            cycle_window_ms=300, sustain_g=0.15, confirm_samples=4, confirm_ms=30,
            max_gap_ms=50, max_reversals=1, hand="LEFT", hard_g=0.90,
            hook_gyro_dps=180, hook_turn_deg=12, hook_axis=None, hook_window_ms=120),
}
# -----------------------------------------------------------------------------


class PunchDetector:
    def __init__(self, label, imu, onset_g, rearm_g, rearm_samples, cycle_window_ms,
                 sustain_g=0.15, confirm_samples=4, confirm_ms=30, max_gap_ms=50,
                 max_reversals=1, hand=None, hard_g=0.90, hook_gyro_dps=180,
                 hook_turn_deg=12, hook_axis=None, hook_window_ms=120):
        if not math.isfinite(hard_g) or hard_g <= onset_g:
            raise ValueError("hard_g must be finite and greater than onset_g")
        if hook_axis not in (None, 0, 1, 2):
            raise ValueError("hook_axis must be None, 0, 1 or 2")
        if any(not math.isfinite(v) or v <= 0
               for v in (hook_gyro_dps, hook_turn_deg, hook_window_ms)):
            raise ValueError("hook thresholds and window must be finite and positive")
        self.label, self.imu = label, imu
        self.hand = hand if hand is not None else imu
        self.hard_g = hard_g
        self.hook_gyro_dps, self.hook_turn_deg = hook_gyro_dps, hook_turn_deg
        self.hook_axis, self.hook_window_ms = hook_axis, hook_window_ms
        self.onset_g, self.rearm_g = onset_g, rearm_g
        self.rearm_samples, self.cycle_window_ms = rearm_samples, cycle_window_ms
        self.sustain_g = sustain_g
        self.confirm_samples, self.confirm_ms = confirm_samples, confirm_ms
        self.max_gap_ms = max_gap_ms
        self.max_reversals = max_reversals
        self.reset()

    def reset(self):
        self.armed = True
        self.window_end_ms = 0
        self.quiet = 0
        self.last_sample_ms = None
        self.gyro_history = deque()
        self.last_kind = "STRAIGHT"
        self.last_gyro_peak = self.last_turn_deg = 0.0
        self.clear_burst()

    def strength_for_peak(self, peak_g):
        return "HARD" if peak_g >= self.hard_g else "LIGHT"

    def rotation_metrics(self):
        """Peak angular speed and net short-window turn; opposing motion cancels."""
        turn = [0.0, 0.0, 0.0]
        peak = 0.0
        previous = None
        for timestamp, gyro in self.gyro_history:
            speed = (math.sqrt(sum(v * v for v in gyro)) if self.hook_axis is None
                     else abs(gyro[self.hook_axis]))
            peak = max(peak, speed)
            if previous is not None:
                prev_t, prev_gyro = previous
                dt = (timestamp - prev_t) / 1000.0
                for axis in range(3):
                    turn[axis] += (prev_gyro[axis] + gyro[axis]) * 0.5 * dt
            previous = timestamp, gyro
        angle = (math.sqrt(sum(v * v for v in turn)) if self.hook_axis is None
                 else abs(turn[self.hook_axis]))
        return peak, angle

    def clear_burst(self):
        self.burst_start_ms = None
        self.burst_samples = 0
        self.burst_peak = 0.0
        self.previous_delta = None
        self.previous_mag = 0.0
        self.burst_reversals = 0

    def update(self, t_ms, d, gyro=None):
        """Return the burst's peak magnitude on confirmation, otherwise None."""
        if self.last_sample_ms is not None:
            gap = t_ms - self.last_sample_ms
            if gap == 0:
                return None  # Duplicate packets are not confirmation evidence.
            if gap < 0:
                self.reset()
            elif gap > self.max_gap_ms:
                self.clear_burst()
                self.quiet = 0
                self.gyro_history.clear()
        self.last_sample_ms = t_ms
        if gyro is None:
            self.gyro_history.clear()
        else:
            self.gyro_history.append((t_ms, tuple(gyro)))
            while self.gyro_history[0][0] < t_ms - self.hook_window_ms:
                self.gyro_history.popleft()
        mag = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)

        # Inside the cycle window: this is the other half of the same punch. Ignore.
        if t_ms < self.window_end_ms:
            self.quiet = 0
            return None

        if self.armed:
            if mag < self.sustain_g:
                self.clear_burst()
                return None
            if self.burst_start_ms is None:
                self.burst_start_ms = t_ms
            self.burst_samples += 1
            self.burst_peak = max(self.burst_peak, mag)
            if self.previous_delta is not None:
                dot = sum(a * b for a, b in zip(self.previous_delta, d))
                if dot < -0.5 * self.previous_mag * mag:
                    self.burst_reversals += 1
            self.previous_delta = tuple(d)
            self.previous_mag = mag
            if (self.burst_peak >= self.onset_g
                    and self.burst_samples >= self.confirm_samples
                    and t_ms - self.burst_start_ms >= self.confirm_ms
                    and self.burst_reversals <= self.max_reversals):
                peak = self.burst_peak
                self.last_gyro_peak, self.last_turn_deg = self.rotation_metrics()
                self.last_kind = ("HOOK" if self.last_gyro_peak >= self.hook_gyro_dps
                                  and self.last_turn_deg >= self.hook_turn_deg
                                  else "STRAIGHT")
                self.armed = False
                self.window_end_ms = t_ms + self.cycle_window_ms
                self.quiet = 0
                self.clear_burst()
                return peak
            return None

        # Window over, not yet re-armed: wait for a quiet stretch.
        self.quiet = self.quiet + 1 if mag < self.rearm_g else 0
        if self.quiet >= self.rearm_samples:
            self.armed = True
        return None


detectors = {i: PunchDetector(**cfg) for i, cfg in CONFIG.items()}
_original_handler = imu_client.handle_sample


def handle_sample(t_ms, imu_ok, deltas, gyros=None):
    if VERBOSE:
        _original_handler(t_ms, imu_ok, deltas, gyros)

    for i, det in detectors.items():
        if not imu_ok[i]:
            det.reset()
            continue
        d = deltas[i]
        gyro = None if gyros is None else gyros[i]
        if METER:
            m = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
            speed = 0.0 if gyro is None else math.sqrt(sum(v * v for v in gyro))
            if m >= METER_MIN_G or speed >= det.hook_gyro_dps:
                gyro_text = "unavailable" if gyro is None else str(tuple(round(v, 1) for v in gyro))
                print(f"t={t_ms} {det.hand} dmag={m:.3f} g gyro={gyro_text} deg/s")
        mag = det.update(t_ms, d, gyro)
        if mag is not None:
            x, y, z = d
            event = f"{det.hand}_{det.last_kind}_{det.strength_for_peak(mag)}"
            punch_label = "HOOK" if det.last_kind == "HOOK" else det.label
            print(f"{event} {punch_label} ({det.imu})  peak dmag={mag:.2f} g  "
                  f"gyro_peak={det.last_gyro_peak:.1f} deg/s turn={det.last_turn_deg:.1f} deg  "
                  f"current d=({x:+.2f}, {y:+.2f}, {z:+.2f})")


# imu_client.on_notify looks up handle_sample at call time, so swapping it out here
# makes the client call our classifier without editing imu_client.py.
imu_client.handle_sample = handle_sample

if __name__ == "__main__":
    try:
        asyncio.run(imu_client.run())
    except KeyboardInterrupt:
        print("\nStopped.")
