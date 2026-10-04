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

    def gyro_punch(self, gyro, peak=0.6):
        # Rotation begins before the acceleration burst, as in a sweeping motion.
        for t in range(0, 70, 10):
            self.assertIsNone(self.detector.update(t, (0, 0, 0), gyro))
        values = [self.detector.update(t, (g, 0, 0), gyro)
                  for t, g in ((70, peak), (80, 0.2), (90, 0.2), (100, 0.2))]
        self.assertEqual(values, [None] * 3 + [peak])

    def test_upward_axis_punch_is_uppercut_with_uncalibrated_sign(self):
        for rate in (250, -250):
            with self.subTest(rate=rate):
                self.detector.reset()
                self.gyro_punch((rate, 0, 0))
                self.assertEqual(self.detector.last_kind, "UPPERCUT")
                self.assertAlmostEqual(self.detector.last_turn_deg, 25)

    def test_low_rotation_punch_stays_straight(self):
        self.gyro_punch((40, 0, 0))
        self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_single_gyro_spike_does_not_make_an_uppercut(self):
        for t, g in ((0, 0.6), (10, 0.2), (20, 0.2), (30, 0.2)):
            self.detector.update(t, (g, 0, 0), (500 if t == 0 else 0, 0, 0))
        self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_rotation_without_acceleration_burst_does_not_fire(self):
        for t in range(0, 200, 10):
            self.assertIsNone(self.detector.update(t, (0.1, 0, 0), (300, 0, 0)))

    def test_alternating_rotation_cancels_uppercut_evidence(self):
        for t in range(0, 110, 10):
            rate = 300 if t % 20 == 0 else -300
            g = 0 if t < 70 else (0.6 if t == 70 else 0.2)
            self.detector.update(t, (g, 0, 0), (rate, 0, 0))
        self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_uppercut_axis_excludes_rotation_on_other_axes(self):
        self.detector = punch.PunchDetector(**dict(punch.CONFIG[0], uppercut_axis=2))
        self.gyro_punch((300, 0, 0))
        self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_horizontal_sweep_and_fist_roll_are_not_uppercuts(self):
        for gyro in ((0, 0, 300), (0, 300, 0)):
            with self.subTest(gyro=gyro):
                self.detector.reset()
                self.gyro_punch(gyro)
                self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_mixed_rotation_needs_dominant_upward_axis(self):
        self.gyro_punch((250, 400, 0))
        self.assertGreater(self.detector.last_turn_deg, self.detector.uppercut_turn_deg)
        self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_uppercut_direction_can_exclude_downward_swing(self):
        for direction in (-1, 1):
            for rate in (-250, 250):
                with self.subTest(direction=direction, rate=rate):
                    self.detector = punch.PunchDetector(
                        **dict(punch.CONFIG[0], uppercut_direction=direction))
                    self.gyro_punch((rate, 0, 0))
                    expected = "UPPERCUT" if rate * direction > 0 else "STRAIGHT"
                    self.assertEqual(self.detector.last_kind, expected)

    def test_uppercut_axis_can_be_remapped_for_mounting(self):
        self.detector = punch.PunchDetector(**dict(punch.CONFIG[0], uppercut_axis=2))
        self.gyro_punch((0, 0, 250))
        self.assertEqual(self.detector.last_kind, "UPPERCUT")

    def test_uppercut_config_rejects_ambiguous_or_invalid_settings(self):
        for settings in ({"uppercut_axis": None}, {"uppercut_direction": 2},
                         {"uppercut_axis_share": 0}, {"uppercut_axis_share": 1.1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                punch.PunchDetector(**dict(punch.CONFIG[0], **settings))

    def test_old_rotation_expires(self):
        for t in range(0, 200, 10):
            self.detector.update(t, (0, 0, 0), (300, 0, 0))
        for t in range(200, 400, 10):
            self.detector.update(t, (0, 0, 0), (0, 0, 0))
        for t, g in ((400, 0.6), (410, 0.2), (420, 0.2), (430, 0.2)):
            self.detector.update(t, (g, 0, 0), (0, 0, 0))
        self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_legacy_packet_cannot_reuse_gyro_evidence(self):
        for t in range(0, 100, 10):
            self.detector.update(t, (0, 0, 0), (300, 0, 0))
        for t, g in ((100, 0.6), (110, 0.2), (120, 0.2), (130, 0.2)):
            self.detector.update(t, (g, 0, 0))
        self.assertEqual(self.detector.last_kind, "STRAIGHT")

    def test_labels_include_hand_type_and_strength(self):
        for i, hand in ((0, "RIGHT"), (1, "LEFT")):
            for peak, strength in ((0.6, "LIGHT"), (1.0, "HARD")):
                with self.subTest(hand=hand, strength=strength):
                    for det in punch.detectors.values():
                        det.reset()
                    with patch("builtins.print") as output:
                        for t in range(0, 110, 10):
                            deltas = [(0, 0, 0), (0, 0, 0)]
                            gyros = [(0, 0, 0), (0, 0, 0)]
                            gyros[i] = (250, 0, 0)
                            if t >= 70:
                                deltas[i] = (peak if t == 70 else 0.2, 0, 0)
                            punch.handle_sample(t, (True, True), deltas, gyros)
                    output.assert_called_once()
                    self.assertTrue(output.call_args.args[0].startswith(f"{hand}_UPPERCUT_{strength}"))
                    self.assertIn("gyro_peak=250.0", output.call_args.args[0])

    def test_straight_labels_preserve_light_and_hard(self):
        for i, hand in ((0, "RIGHT"), (1, "LEFT")):
            for peak, strength in ((0.6, "LIGHT"), (0.9, "HARD")):
                with self.subTest(hand=hand, strength=strength):
                    for det in punch.detectors.values():
                        det.reset()
                    with patch("builtins.print") as output:
                        for t, g in ((0, peak), (10, 0.2), (20, 0.2), (30, 0.2)):
                            deltas = [(0, 0, 0), (0, 0, 0)]
                            deltas[i] = (g, 0, 0)
                            punch.handle_sample(t, (True, True), deltas)
                    output.assert_called_once()
                    self.assertTrue(output.call_args.args[0].startswith(f"{hand}_STRAIGHT_{strength}"))


if __name__ == "__main__":
    unittest.main()
