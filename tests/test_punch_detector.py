"""Replay acceleration deltas without BLE hardware or the bleak dependency."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


client = types.ModuleType("imu_client")
client.handle_sample = lambda *args: None
spec = importlib.util.spec_from_file_location(
    "punch_detector_under_test",
    Path(__file__).resolve().parents[1] / "microcontroller" / "punch_detector.py",
)
punch = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"imu_client": client}):
    spec.loader.exec_module(punch)


class PunchDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = punch.PunchDetector(**punch.CONFIG[0])

    def replay(self, samples):
        return [self.detector.update(t, (g, 0, 0)) for t, g in samples]

    def test_small_movements_do_not_fire(self):
        self.assertTrue(all(value is None for value in self.replay(
            [(t, 0.18) for t in range(0, 200, 10)])))

    def test_sustained_movement_without_strong_peak_does_not_fire(self):
        self.assertTrue(all(value is None for value in self.replay(
            [(t, 0.3) for t in range(0, 200, 10)])))

    def test_isolated_large_spike_does_not_fire(self):
        self.assertEqual(self.replay([(0, 0), (10, 1.2), (20, 0), (30, 0)]),
                         [None] * 4)

    def test_burst_fires_once_and_returns_peak(self):
        self.assertEqual(self.replay([(0, 0.25), (10, 0.7), (20, 0.3),
                                     (30, 0.3), (40, 0.3)]),
                         [None] * 3 + [0.7, None])
        self.assertTrue(all(value is None for value in self.replay(
            [(t, 0.8) for t in range(50, 340, 10)])))

    def test_quiet_samples_rearm_for_next_punch(self):
        self.replay([(0, 0.6), (10, 0.3), (20, 0.25), (30, 0.3), (40, 0.3)])
        self.replay([(t, 0) for t in range(50, 380, 10)])
        self.assertEqual(self.replay([(380, 0.6), (390, 0.3), (400, 0.25),
                                     (410, 0.3), (420, 0.3)]),
                         [None] * 3 + [0.6, None])

    def test_packet_gap_preserves_retraction_cooldown(self):
        self.replay([(0, 0.6), (10, 0.3), (20, 0.25), (30, 0.3), (40, 0.3)])
        self.assertEqual(self.replay([(100, 0.8), (110, 0.3), (120, 0.3),
                                     (130, 0.3), (140, 0.3)]),
                         [None] * 5)

    def test_confirmation_uses_sensor_time(self):
        self.assertEqual(self.replay([(0, 0.6), (1, 0.3), (2, 0.3),
                                     (3, 0.3), (4, 0.3)]), [None] * 5)
        self.assertEqual(self.detector.update(40, (0.3, 0, 0)), 0.6)

    def test_duplicate_packet_does_not_confirm(self):
        self.assertEqual(self.replay([(0, 0.6), (0, 0.6), (10, 0.3),
                                     (30, 0.3)]), [None] * 4)

    def test_short_tap_burst_does_not_fire(self):
        self.assertEqual(self.replay([(0, 1.2), (10, 0.8), (20, 0.5),
                                     (30, 0.1), (40, 0)]), [None] * 5)

    def test_alternating_tap_vibration_does_not_fire(self):
        self.assertTrue(all(value is None for value in self.replay(
            [(t, 0.8 if t % 20 == 0 else -0.8) for t in range(0, 200, 10)])))

    def test_negative_direction_punch_can_fire(self):
        self.assertEqual(self.replay([(0, -0.6), (10, -0.3), (20, -0.25),
                                     (30, -0.3), (40, -0.3)]),
                         [None] * 3 + [0.6, None])

    def test_light_short_punch_can_fire(self):
        self.assertEqual(self.replay([(0, 0.48), (10, 0.16), (20, 0.15),
                                     (30, 0.16)]), [None] * 3 + [0.48])

    def test_moderate_bump_below_peak_threshold_does_not_fire(self):
        self.assertEqual(self.replay([(0, 0.43), (10, 0.2), (20, 0.18),
                                     (30, 0.16)]), [None] * 4)

    def test_strong_bump_with_weak_tail_does_not_fire(self):
        self.assertEqual(self.replay([(0, 0.6), (10, 0.18), (20, 0.13),
                                     (30, 0.14), (40, 0)]), [None] * 5)

    def test_punch_acceleration_then_deceleration_can_fire(self):
        self.assertEqual(self.replay([(0, 0.45), (10, 0.15), (20, -0.3),
                                     (30, -0.3)]), [None] * 3 + [0.45])

    def test_gap_or_clock_restart_discards_old_peak(self):
        for next_time in (100, 0):
            with self.subTest(next_time=next_time):
                self.detector.reset()
                self.assertEqual(self.replay([
                    (10, 0.8), (20, 0.3), (next_time, 0.3),
                    (next_time + 10, 0.3), (next_time + 20, 0.3),
                    (next_time + 30, 0.3), (next_time + 40, 0.3),
                ]), [None] * 7)

    def test_sensor_failure_clears_pending_burst(self):
        for det in punch.detectors.values():
            det.reset()
        with patch("builtins.print") as output:
            punch.handle_sample(0, (True, False), [(0.8, 0, 0), (0, 0, 0)])
            punch.handle_sample(10, (False, False), [(0, 0, 0), (0, 0, 0)])
            for t in (20, 30, 40, 50, 60):
                punch.handle_sample(t, (True, False), [(0.3, 0, 0), (0, 0, 0)])
        output.assert_not_called()


if __name__ == "__main__":
    unittest.main()
