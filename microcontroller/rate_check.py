"""
Checks whether the ESP32 + BLE link keeps up with the sketch's sample rate.

Set EXPECTED_MS to the same value as SAMPLE_MS in the Arduino sketch, then run
(in the same folder as imu_client.py):
    py rate_check.py

Every few seconds it prints one line:
  rate     complete samples/second received vs. what the sketch should send
           (v2 pairs two hand packets into one sample)
  esp gap  time between samples measured by the ESP32's own clock (avg / max).
           This is how fast the ESP32 loop + sensors really run.
  late     samples whose ESP32 gap was more than 1.5x EXPECTED_MS
           (the ESP32 skipped a sample, or a BLE packet was dropped)
  pc gap   max time between packets arriving on the PC. If this is much bigger
           than the esp gap, BLE is batching packets (delay, not data loss).
  imu bad  samples where one of the sensors reported not-ok
"""
import asyncio
import time

import imu_client

EXPECTED_MS = 10      # must match SAMPLE_MS in the sketch
REPORT_EVERY_S = 3.0

_last_t = None
_last_pc = None
_t0 = time.perf_counter()
_count = 0
_esp_gaps = []
_pc_gaps = []
_bad_imu = 0
_late = 0


def handle_sample(t_ms, imu_ok, deltas, gyros=None):
    global _last_t, _last_pc, _t0, _count, _esp_gaps, _pc_gaps, _bad_imu, _late

    now = time.perf_counter()
    _count += 1
    if not all(imu_ok):
        _bad_imu += 1

    if _last_t is not None:
        gap = t_ms - _last_t
        if 0 < gap < 1000:  # ignore reconnects / clock restarts
            _esp_gaps.append(gap)
            _pc_gaps.append((now - _last_pc) * 1000.0)
            if gap > 1.5 * EXPECTED_MS:
                _late += 1
    _last_t, _last_pc = t_ms, now

    elapsed = now - _t0
    if elapsed >= REPORT_EVERY_S:
        expected_rate = 1000.0 / EXPECTED_MS
        rate = _count / elapsed
        avg_gap = sum(_esp_gaps) / len(_esp_gaps) if _esp_gaps else 0
        max_gap = max(_esp_gaps) if _esp_gaps else 0
        max_pc = max(_pc_gaps) if _pc_gaps else 0
        ok = rate >= 0.95 * expected_rate and _late == 0
        print(f"rate {rate:5.1f}/{expected_rate:.0f} Hz | "
              f"esp gap avg {avg_gap:4.1f} max {max_gap:3.0f} ms | late {_late:3d} | "
              f"pc gap max {max_pc:4.0f} ms | imu bad {_bad_imu:3d} | "
              f"{'OK' if ok else 'NOT KEEPING UP'}")
        _t0, _count, _esp_gaps, _pc_gaps, _bad_imu, _late = now, 0, [], [], 0, 0


imu_client.handle_sample = handle_sample

if __name__ == "__main__":
    try:
        asyncio.run(imu_client.run())
    except KeyboardInterrupt:
        print("\nStopped.")
