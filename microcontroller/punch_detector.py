"""
Punch classifier built on imu_client.py.

IMU2 = left hand  -> JAB
IMU1 = right hand -> CROSS

How a punch is counted
----------------------
A punch has two phases: the extension (out) and the retraction (back). Either one
can be the fast part, so BOTH are treated as punch evidence:

  * The first spike (dmag >= onset_g) from a hand fires a punch. That spike might be
    the extension (fast punch) or the retraction (slow extension that never crossed
    the threshold, followed by a fast pull-back).
  * That spike opens a "cycle window" (cycle_window_ms). Any spike inside the window
    is treated as the other half of the SAME punch and ignored. This is what stops a
    fast punch + fast retraction from counting twice.
  * After the window, the hand re-arms only once it has been quiet for
    rearm_samples samples in a row, so a slow drift back to rest never fires.

Put this file in the same folder as imu_client.py and run:
    py punch_detector.py
"""
import asyncio
import math

import imu_client

VERBOSE = False  # True = also print every raw sample (imu_client's default output)
METER = False    # True = print any sample with dmag above METER_MIN_G, to help tune onset_g
METER_MIN_G = 0.05

# ---- Tuning ----------------------------------------------------------------
# onset_g         : dmag (g, change per sample) that counts as a punch spike
# rearm_g         : dmag must stay below this to re-arm after the window
# rearm_samples   : ...for this many samples in a row
# cycle_window_ms : after a punch fires, spikes within this time are the same punch
#                   (its retraction). Too short -> retraction double-fires.
#                   Too long -> a quick second punch from the same hand is missed.
CONFIG = {
    0: dict(label="CROSS", imu="IMU1", onset_g=0.15, rearm_g=0.06, rearm_samples=4,
            cycle_window_ms=300),
    1: dict(label="JAB",   imu="IMU2", onset_g=0.15, rearm_g=0.06, rearm_samples=4,
            cycle_window_ms=300),
}
# -----------------------------------------------------------------------------


class PunchDetector:
    def __init__(self, label, imu, onset_g, rearm_g, rearm_samples, cycle_window_ms):
        self.label, self.imu = label, imu
        self.onset_g, self.rearm_g = onset_g, rearm_g
        self.rearm_samples, self.cycle_window_ms = rearm_samples, cycle_window_ms
        self.armed = True
        self.window_end_ms = 0
        self.quiet = 0

    def reset(self):
        self.armed = True
        self.window_end_ms = 0
        self.quiet = 0

    def update(self, t_ms, d):
        """Returns the magnitude if a punch fired on this sample, else None."""
        mag = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)

        # Inside the cycle window: this is the other half of the same punch. Ignore.
        if t_ms < self.window_end_ms:
            self.quiet = 0
            return None

        if self.armed:
            if mag >= self.onset_g:
                self.armed = False
                self.window_end_ms = t_ms + self.cycle_window_ms
                self.quiet = 0
                return mag
            return None

        # Window over, not yet re-armed: wait for a quiet stretch.
        self.quiet = self.quiet + 1 if mag < self.rearm_g else 0
        if self.quiet >= self.rearm_samples:
            self.armed = True
        return None


detectors = {i: PunchDetector(**cfg) for i, cfg in CONFIG.items()}
_original_handler = imu_client.handle_sample


def handle_sample(t_ms, imu_ok, deltas):
    if VERBOSE:
        _original_handler(t_ms, imu_ok, deltas)

    for i, det in detectors.items():
        if not imu_ok[i]:
            det.reset()
            continue
        d = deltas[i]
        if METER:
            m = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
            if m >= METER_MIN_G:
                print(f"    {det.imu} dmag={m:.2f}")
        mag = det.update(t_ms, d)
        if mag is not None:
            x, y, z = d
            print(f"{det.label:<5} ({det.imu})  dmag={mag:.2f} g  d=({x:+.2f}, {y:+.2f}, {z:+.2f})")


# imu_client.on_notify looks up handle_sample at call time, so swapping it out here
# makes the client call our classifier without editing imu_client.py.
imu_client.handle_sample = handle_sample

if __name__ == "__main__":
    try:
        asyncio.run(imu_client.run())
    except KeyboardInterrupt:
        print("\nStopped.")