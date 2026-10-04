"""Input lifecycle tests that do not require a camera, serial port, or gamepad."""

import unittest
from unittest.mock import MagicMock, Mock, call, patch

import run_controller

from run_controller import (
    AttackInput, MicrocontrollerAttacks, ROOT, load_module,
    movement_input, update_controller,
)

bluetooth = load_module("test_esp32_bluetooth", ROOT / "microcontroller" / "bluetooth.py")


class ControllerInputTests(unittest.TestCase):
    def test_main_without_bluetooth_sends_movement_and_releases_on_exit(self):
        self.check_main_inputs(voice_enabled=False)

    def test_main_voice_uses_neutral_special_then_restores_movement(self):
        self.check_main_inputs(voice_enabled=True)

    def check_main_inputs(self, voice_enabled):
        cv2 = Mock()
        frame = Mock(shape=(480, 640, 3))
        cv2.VideoCapture.return_value.read.return_value = (True, frame)
        cv2.waitKey.return_value = ord("q")
        detector = Mock()
        detector.process_frame.return_value.pose_landmarks = [object()]
        detector.detect_jumping.return_value = False
        detector.detect_crouching.return_value = False
        detector.detect_leaning_forward.return_value = True
        pose_module = Mock()
        pose_module.PoseDetector = MagicMock()
        pose_module.PoseDetector.return_value.__enter__.return_value = detector
        controller = Mock()
        controller.resolve.return_value = {"right"}
        voice = Mock()
        if voice_enabled:
            voice.held.side_effect = [{"special"}, {"special"}, set()]
            cv2.waitKey.side_effect = [-1, -1, ord("q")]
            controller.resolve.side_effect = [set(), {"special"}, {"right"}]
        argv = ["run_controller.py", "--no-bluetooth"]
        if not voice_enabled:
            argv.append("--no-voice")
        with patch("sys.argv", argv), \
                patch("sys.path", list(run_controller.sys.path)), \
                patch.dict("sys.modules", {"cv2": cv2, "pose_detector": pose_module, "serial": None}), \
                patch.object(run_controller.Path, "is_file", return_value=True), \
                patch.object(run_controller, "load_controller", return_value=controller), \
                patch.object(run_controller, "start_voice_input", return_value=voice) as start_voice, \
                patch.object(run_controller, "load_module") as load_transport:
            run_controller.main()
        load_transport.assert_not_called()
        if voice_enabled:
            start_voice.assert_called_once()
            self.assertEqual(controller.resolve.call_args_list,
                             [call(set()), call({"special"}), call({"forward"})])
            self.assertEqual(controller.apply.call_args_list,
                             [call(set()), call({"special"}), call({"right"}), call(set())])
        else:
            start_voice.assert_not_called()
            controller.resolve.assert_called_once_with({"forward"})
            self.assertEqual(controller.apply.call_args_list, [call(set()), call({"right"}), call(set())])
        cv2.VideoCapture.return_value.release.assert_called_once()

    def test_repeated_messages_hold_until_silence(self):
        state = AttackInput(timeout=0.25)
        state.receive("light", 1.0)
        self.assertEqual(state.held(1.2), {"light"})
        state.receive("light", 1.2)
        self.assertEqual(state.held(1.4), {"light"})
        self.assertEqual(state.held(1.5), set())

    def test_partial_lines_and_switching_attacks(self):
        state = AttackInput()
        receiver = bluetooth.BluetoothReceiver()
        receiver.connection = Mock()
        receiver.connection.readline.side_effect = [b"med", b"ium\r\n"]
        self.assertIsNone(receiver.read_message())
        state.receive(receiver.read_message(), 1.1)
        self.assertEqual(state.held(1.1), {"medium"})
        state.receive("heavy", 1.2)
        state.receive("special", 1.2)
        self.assertEqual(state.held(1.2), {"special"})

    def test_invalid_messages_do_not_refresh_or_replace_attack(self):
        state = AttackInput()
        state.receive("light", 1.0)
        state.receive("debug log", 1.2)
        self.assertEqual(state.held(1.2), {"light"})
        self.assertEqual(state.held(1.3), set())

    def test_oversized_line_is_discarded_and_parser_recovers(self):
        receiver = bluetooth.BluetoothReceiver()
        receiver.connection = Mock()
        receiver.connection.readline.side_effect = [b"x" * 1025, b"light\n", b"heavy\n"]
        self.assertIsNone(receiver.read_message())
        self.assertIsNone(receiver.read_message())
        self.assertEqual(receiver.read_message(), "heavy")

    def test_background_reader_consumes_bluetooth_strings(self):
        connection = Mock()
        reader = MicrocontrollerAttacks(connection, 0.25)
        def read_message():
            reader.stop.set()
            return "light"
        connection.read_message.side_effect = read_message
        reader._read()
        self.assertEqual(reader.held(), {"light"})

    def test_background_reader_reports_disconnect(self):
        connection = Mock()
        connection.read_message.side_effect = OSError("disconnected")
        reader = MicrocontrollerAttacks(connection, 0.25)
        reader._read()
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            reader.held()

    def test_movement_priority_and_tracking_loss(self):
        detector = Mock()
        detector.detect_jumping.return_value = True
        self.assertEqual(movement_input(detector, object(), 100, (640, 480)), {"up"})
        detector.detect_crouching.assert_not_called()
        detector.detect_jumping.return_value = False
        detector.detect_crouching.return_value = True
        self.assertEqual(movement_input(detector, object(), 200, (640, 480)), {"down"})
        detector.detect_leaning_forward.assert_not_called()
        self.assertEqual(movement_input(detector, None, 300, (640, 480)), set())
        detector.detect_jumping.assert_called_with(None, 300, image_size=(640, 480))
        detector.detect_crouching.return_value = False
        detector.detect_leaning_forward.return_value = True
        self.assertEqual(movement_input(detector, object(), 400, (640, 480)), {"forward"})
        detector.detect_leaning_forward.return_value = False
        detector.detect_leaning_backward.return_value = True
        self.assertEqual(movement_input(detector, object(), 500, (640, 480)), {"back"})
        detector.detect_leaning_backward.return_value = False
        self.assertEqual(movement_input(detector, object(), 600, (640, 480)), set())

    def test_side_swap_reresolves_held_movement_with_attack(self):
        controller = Mock()
        controller.resolve.side_effect = [
            {"right", "light"}, {"right", "light"}, {"left", "light"},
        ]
        held = {"forward", "light"}
        last = update_controller(controller, held, None)
        last = update_controller(controller, held, last)
        last = update_controller(controller, held, last)
        self.assertEqual(last, {"left", "light"})
        self.assertEqual(controller.resolve.call_count, 3)
        self.assertEqual(controller.apply.call_count, 2)
        controller.apply.assert_called_with({"left", "light"})


if __name__ == "__main__":
    unittest.main()
