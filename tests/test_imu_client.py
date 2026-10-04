"""Exercise the actual BLE packet decoder without a Bluetooth adapter."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


bleak = types.ModuleType("bleak")
bleak.BleakClient = Mock()
bleak.BleakScanner = Mock()
spec = importlib.util.spec_from_file_location(
    "imu_client_under_test",
    Path(__file__).resolve().parents[1] / "microcontroller" / "IMU_client.py",
)
imu = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"bleak": bleak}):
    spec.loader.exec_module(imu)


class ImuPacketTests(unittest.TestCase):
    def setUp(self):
        imu._pending.clear()
        self.handler = Mock()
        self.patch = patch.object(imu, "handle_sample", self.handler)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def packet(self, t, hand, ok=True):
        return imu.PACKET.pack(t, 0x80 | (hand << 2) | int(ok),
                               100, -200, 300, 3280, -6560, 9840)

    def test_legacy_acceleration_packets_still_work(self):
        imu.on_notify(None, imu.PACKET.pack(10, 1, 100, -200, 300, 400, 500, 600))
        self.handler.assert_called_once_with(
            10, (True, False), [(0.1, -0.2, 0.3), (0.4, 0.5, 0.6)])

    def test_v2_pair_decodes_acceleration_and_gyro_units(self):
        self.assertEqual(len(self.packet(10, 0)), 17)
        imu.on_notify(None, self.packet(10, 0))
        self.handler.assert_not_called()
        imu.on_notify(None, self.packet(10, 1, ok=False))
        self.handler.assert_called_once()
        timestamp, valid, deltas, gyros = self.handler.call_args.args
        self.assertEqual((timestamp, valid, deltas),
                         (10, (True, False), [(0.1, -0.2, 0.3)] * 2))
        for gyro in gyros:
            for actual, expected in zip(gyro, (100, -200, 300)):
                self.assertAlmostEqual(actual, expected)

    def test_reversed_hand_order_is_supported(self):
        imu.on_notify(None, self.packet(10, 1))
        imu.on_notify(None, self.packet(10, 0))
        self.handler.assert_called_once()

    def test_different_timestamps_are_not_combined(self):
        imu.on_notify(None, self.packet(10, 0))
        imu.on_notify(None, self.packet(20, 1))
        self.handler.assert_not_called()
        imu.on_notify(None, self.packet(20, 0))
        self.assertEqual(self.handler.call_args.args[0], 20)

    def test_duplicate_half_does_not_complete_pair(self):
        imu.on_notify(None, self.packet(10, 0))
        imu.on_notify(None, self.packet(10, 0))
        self.handler.assert_not_called()
        imu.on_notify(None, self.packet(10, 1))
        self.handler.assert_called_once()

    def test_missing_halves_have_bounded_storage(self):
        for t in range(100):
            imu.on_notify(None, self.packet(t, 0))
        self.assertLessEqual(len(imu._pending), 8)
        self.handler.assert_not_called()

    def test_malformed_and_unknown_packets_are_ignored(self):
        for packet in (b"", b"x" * 16, b"x" * 29,
                       imu.PACKET.pack(10, 0x82, *([0] * 6)),
                       imu.PACKET.pack(10, 4, *([0] * 6))):
            imu.on_notify(None, packet)
        self.handler.assert_not_called()

    def test_firmware_packets_drive_uppercut_debug_output(self):
        detector_spec = importlib.util.spec_from_file_location(
            "packet_punch_detector",
            Path(__file__).resolve().parents[1] / "microcontroller" / "punch_detector.py",
        )
        detector = importlib.util.module_from_spec(detector_spec)
        with patch.dict(sys.modules, {"IMU_client": imu}):
            detector_spec.loader.exec_module(detector)
        imu.handle_sample = self.handler
        self.handler.side_effect = detector.handle_sample
        with patch("builtins.print") as output:
            for t in range(0, 110, 10):
                delta = 0 if t < 70 else (600 if t == 70 else 200)
                imu.on_notify(None, imu.PACKET.pack(t, 0x81, delta, 0, 0, 8200, 0, 0))
                imu.on_notify(None, imu.PACKET.pack(t, 0x85, 0, 0, 0, 0, 0, 0))
        output.assert_called_once()
        self.assertEqual(output.call_args.args[0].split()[0], "RIGHT_UPPERCUT")


if __name__ == "__main__":
    unittest.main()
