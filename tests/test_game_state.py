"""Snapshot loading and controller integration without gamepad hardware."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from game_state import GameState, read_game_state
import run_controller


SAMPLE = {
    "p1_facing": "right",
    "p1_health": 6840,
    "p1_health_old": 6840,
    "p1_name": "Chun-Li",
    "p1_side": "left",
    "p1_take_damage": False,
}


class GameStateTests(unittest.TestCase):
    def test_loads_full_snapshot_and_legacy_export(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(SAMPLE), encoding="utf-8")
            self.assertEqual(read_game_state(path), GameState(**SAMPLE))
            path.write_text(json.dumps({"p1_name": "Ryu", "p1_facing": "left", "p1_side": "right"}),
                            encoding="utf-8")
            state = read_game_state(path)
            self.assertEqual(state.facing, "left")
            self.assertIsNone(state.p1_health)
            self.assertIsNone(state.p1_health_old)

    def test_health_bounds_and_schema_errors(self):
        for health in (0, 10000):
            self.assertEqual(GameState.from_dict({**SAMPLE, "p1_health": health}).p1_health, health)
        for field, value in (
            ("p1_health", -1), ("p1_health", 10001), ("p1_health", True),
            ("p1_health", "6840"), ("p1_health_old", 1.5),
            ("p1_facing", "up"), ("p1_facing", False), ("p1_side", "middle"),
            ("p1_name", "Not a fighter"), ("p1_take_damage", "false"),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                GameState.from_dict({**SAMPLE, field: value})

    def test_missing_partial_and_invalid_files_recover_next_read(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            self.assertIsNone(read_game_state(path))
            for contents in ('{"p1_facing":', '[]', '{"p1_health": 10001}'):
                path.write_text(contents, encoding="utf-8")
                self.assertIsNone(read_game_state(path))
            path.write_text(json.dumps(SAMPLE), encoding="utf-8")
            self.assertEqual(read_game_state(path).p1_name, "Chun-Li")
        with patch("game_state.open", side_effect=PermissionError):
            self.assertIsNone(read_game_state("inaccessible.json"))

    def test_side_precedence_and_facing_fallback(self):
        self.assertEqual(GameState(p1_facing="left", p1_side="left").facing, "right")
        self.assertEqual(GameState(p1_facing="right", p1_side="right").facing, "left")
        self.assertEqual(GameState(p1_facing="left").facing, "left")
        self.assertEqual(GameState.from_dict({"p1_name": "", "p1_facing": "", "p1_side": ""}).facing,
                         "right")

    def test_controller_resolves_supplied_facing_without_file_access(self):
        gamepad = Mock()
        with patch.dict("sys.modules", {"vgamepad": gamepad}):
            controller = run_controller.load_controller(
                run_controller.ROOT / "game-controller" / "controller.py"
            )
        with patch("builtins.open", side_effect=AssertionError("Controller must not read files")):
            held = {"forward", "light"}
            last = run_controller.update_controller(controller, held, None, facing="right")
            self.assertEqual(last, {"right", "light"})
            last = run_controller.update_controller(controller, held, last, facing="left")
            self.assertEqual(last, {"left", "light"})
            self.assertEqual(controller.resolve("back+drive parry", facing="left"),
                             {"right", "drive_parry"})
            self.assertEqual(controller.resolve({"special"}, facing="left"), {"special"})
            controller.apply({"special"})
            gamepad.VX360Gamepad.return_value.press_button.assert_called_with(
                button=gamepad.XUSB_BUTTON.XUSB_GAMEPAD_Y
            )


if __name__ == "__main__":
    unittest.main()
