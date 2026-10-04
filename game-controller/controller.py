"""Facing resolution and virtual Xbox output for run_controller.py."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Set
from typing import Any, Literal

import vgamepad as vg

# ---- adjust these ----
GAME_STATE_PATH: str = r"C:\Program Files (x86)\Steam\steamapps\common\Street Fighter 6\reframework\data\p1_character.json"
# ----------------------

B = vg.XUSB_BUTTON

# Absolute directions
DIRECTIONS: dict[str, vg.XUSB_BUTTON] = {
    "up": B.XUSB_GAMEPAD_DPAD_UP,
    "down": B.XUSB_GAMEPAD_DPAD_DOWN,
    "left": B.XUSB_GAMEPAD_DPAD_LEFT,
    "right": B.XUSB_GAMEPAD_DPAD_RIGHT,
}

# Default SF6 Modern Xbox layout. Select Modern controls in-game;
# edit these mappings if you use custom bindings.
BUTTONS: dict[str, vg.XUSB_BUTTON | Literal["RT", "LT"]] = {
    "light": B.XUSB_GAMEPAD_X,
    "medium": B.XUSB_GAMEPAD_A,
    "heavy": B.XUSB_GAMEPAD_B,
    "special": B.XUSB_GAMEPAD_Y,
    "drive_impact": B.XUSB_GAMEPAD_LEFT_SHOULDER,
    "drive_parry": B.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "assist": "RT",
    "throw": "LT",
}

pad: vg.VX360Gamepad = vg.VX360Gamepad()


def read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return None


def facing_right() -> bool:
    """True if 'forward' means pressing right."""
    state = read_json(GAME_STATE_PATH) or {}
    if state.get("p1_side"):                 # earlier signal, if your Lua writes it
        return state["p1_side"] == "left"    # P1 on the left of the opponent -> faces right
    return state.get("p1_facing", "right") == "right"


def resolve(held: str | Iterable[str]) -> set[str]:
    """Expand simultaneous inputs and resolve facing-relative directions.

    Accepts ["down", "medium"], ["down medium"], or "down+medium".
    """
    if isinstance(held, str):
        held = [held]
    right = facing_right()
    out: set[str] = set()
    for combination in held:
        combination = str(combination).strip().lower()
        # Preserve multiword button names before splitting combinations.
        combination = re.sub(r"drive\s+(impact|parry)", r"drive_\1", combination)
        for name in re.split(r"[\s+]+", combination):
            if name == "forward":
                out.add("right" if right else "left")
            elif name == "back":
                out.add("left" if right else "right")
            elif name:
                out.add(name)
    return out


def apply(resolved: Set[str]) -> None:
    pad.reset()
    for name in resolved:
        if name in DIRECTIONS:
            pad.press_button(button=DIRECTIONS[name])
        elif name in BUTTONS:
            button = BUTTONS[name]
            if button == "RT":
                pad.right_trigger(value=255)
            elif button == "LT":
                pad.left_trigger(value=255)
            else:
                pad.press_button(button=button)
        else:
            print("Unknown input:", name)
    pad.update()
