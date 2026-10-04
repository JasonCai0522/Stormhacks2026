"""Replay firmware packets through punch detection and controller button pulses."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

from run_controller import update_controller


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "microcontroller" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bleak = types.ModuleType("bleak")
bleak.BleakClient = Mock()
bleak.BleakScanner = Mock()
with patch.dict(sys.modules, {"bleak": bleak}):
    imu = load("bridge_imu", "IMU_client.py")
with patch.dict(sys.modules, {"IMU_client": imu}):
    classifier = load("bridge_classifier", "punch_detector.py")
with patch.dict(sys.modules, {"IMU_client": imu, "punch_detector": classifier}):
    bridge = load("bridge_attacks", "ble_attacks.py")


class BLEAttackTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.clock = patch.object(bridge.time, "monotonic", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.reader = bridge.BLEAttacks()
        self.reader._reset()
        imu._pending.clear()
        self.reader.last_sample_at = self.now

    def test_all_four_firmware_gestures_reach_their_mapped_buttons(self):
        for hand, kind, button in ((1, "STRAIGHT", "light"), (1, "UPPERCUT", "medium"),
                                   (0, "STRAIGHT", "heavy"), (0, "UPPERCUT", "special")):
            with self.subTest(hand=hand, kind=kind):
                self.reader._reset()
                with patch.object(classifier, "on_punch", self.reader._receive), \
                        patch.object(imu, "handle_sample", self.reader._handle_sample), \
                        patch("builtins.print") as output:
                    for t in range(0, 110, 10):
                        for i in (0, 1):
                            delta = (600 if t == 70 else 200) if i == hand and t >= 70 else 0
                            rate = 8200 if i == hand and kind == "UPPERCUT" else 0
                            packet = imu.PACKET.pack(t, 0x81 | (i << 2), delta, 0, 0, rate, 0, 0)
                            imu.on_notify(None, packet)
                output.assert_called_once()
                self.assertEqual(self.reader.held(), {button})
                self.now += 0.11
                self.assertEqual(self.reader.held(), set())
                self.assertEqual(self.reader.held(), set())

    def test_repeat_punches_have_separate_presses_and_keep_movement(self):
        self.reader._receive("LEFT_STRAIGHT")
        self.reader._receive("LEFT_STRAIGHT")
        controller = Mock()
        controller.resolve.side_effect = lambda held: held
        last = set()
        for offset in (0, 0.05, 0.11, 0.12, 0.23):
            self.now = 100 + offset
            last = update_controller(controller, {"up"} | self.reader.held(), last)
        self.assertEqual([call.args[0] for call in controller.apply.call_args_list],
                         [{"up", "light"}, {"up"}, {"up", "light"}, {"up"}])

    def test_events_queue_in_order_instead_of_overwriting_each_other(self):
        self.reader._receive("LEFT_UPPERCUT")
        self.reader._receive("RIGHT_STRAIGHT")
        self.assertEqual(self.reader.held(), {"medium"})
        self.now += 0.11
        self.assertEqual(self.reader.held(), set())
        self.assertEqual(self.reader.held(), {"heavy"})

    def test_disconnect_releases_active_and_discards_queued_punches(self):
        self.reader._receive("RIGHT_UPPERCUT")
        self.reader._receive("LEFT_STRAIGHT")
        self.assertEqual(self.reader.held(), {"special"})
        self.reader._reset()
        self.assertEqual(self.reader.held(), set())
        self.assertEqual(list(self.reader.queue), [])

    def test_packet_silence_discards_attacks_without_replaying_on_reconnect(self):
        self.reader._receive("LEFT_STRAIGHT")
        self.now += 0.6
        self.assertEqual(self.reader.held(), set())
        self.reader._handle_sample(0, (True, True), [(0, 0, 0)] * 2)
        self.assertEqual(self.reader.held(), set())

    def test_sensor_failure_clears_only_that_hands_attacks(self):
        self.reader._receive("LEFT_STRAIGHT")
        self.reader._receive("RIGHT_STRAIGHT")
        self.assertEqual(self.reader.held(), {"light"})
        self.reader._handle_sample(0, (True, False), [(0, 0, 0)] * 2)
        self.assertEqual(self.reader.held(), {"heavy"})

    def test_stale_queue_is_dropped_even_while_new_samples_arrive(self):
        self.reader._receive("LEFT_STRAIGHT")
        self.now += 0.6
        self.reader._handle_sample(0, (True, True), [(0, 0, 0)] * 2)
        self.assertEqual(self.reader.held(), set())

    def test_invalid_events_do_not_trigger_inputs(self):
        self.reader._receive("LEFT_HOOK")
        self.reader._receive("debug line")
        self.assertEqual(self.reader.held(), set())

    def test_close_cancels_worker_and_restores_callbacks(self):
        started = threading.Event()
        cancelled = threading.Event()

        async def stream(on_disconnect):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
                on_disconnect()

        original_sample, original_punch = imu.handle_sample, classifier.on_punch
        with patch.object(imu, "run", stream):
            with self.reader:
                self.assertTrue(started.wait(timeout=2))
                self.assertEqual(imu.handle_sample, self.reader._handle_sample)
            self.assertFalse(self.reader.thread.is_alive())
            self.assertTrue(cancelled.is_set())
        self.assertIs(imu.handle_sample, original_sample)
        self.assertIs(classifier.on_punch, original_punch)

    def test_worker_error_reaches_controller_and_clears_inputs(self):
        async def stream(on_disconnect):
            raise OSError("adapter failed")

        with patch.object(imu, "run", stream):
            self.reader._read()
        with self.assertRaisesRegex(RuntimeError, "adapter failed"):
            self.reader.held()
        self.assertIsNone(self.reader.active)


if __name__ == "__main__":
    unittest.main()
