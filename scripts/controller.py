import json
import os
import time
import vgamepad as vg

# ---- adjust these ----
GAME_STATE_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Street Fighter 6\reframework\data\p1_character.json"
COMMAND_PATH = "inputs.json"   # relative to where you run the script
# ----------------------

B = vg.XUSB_BUTTON

# Absolute directions
DIRECTIONS = {
    "up": B.XUSB_GAMEPAD_DPAD_UP,
    "down": B.XUSB_GAMEPAD_DPAD_DOWN,
    "left": B.XUSB_GAMEPAD_DPAD_LEFT,
    "right": B.XUSB_GAMEPAD_DPAD_RIGHT,
}

# Attack buttons. This assumes a classic-style layout; the game's own
# bindings decide what each Xbox button actually does, so edit to match yours.
BUTTONS = {
    "lp": B.XUSB_GAMEPAD_X,
    "mp": B.XUSB_GAMEPAD_Y,
    "hp": B.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "lk": B.XUSB_GAMEPAD_A,
    "mk": B.XUSB_GAMEPAD_B,
    "hk": "RT",   # right trigger, handled separately
}

pad = vg.VX360Gamepad()


def read_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return None


def facing_right():
    """True if 'forward' means pressing right."""
    state = read_json(GAME_STATE_PATH) or {}
    if state.get("p1_side"):                 # earlier signal, if your Lua writes it
        return state["p1_side"] == "left"    # P1 on the left of the opponent -> faces right
    return state.get("p1_facing", "right") == "right"


def resolve(held):
    """Turn names like 'forward' into real directions."""
    right = facing_right()
    out = set()
    for name in held:
        name = str(name).lower()
        if name == "forward":
            out.add("right" if right else "left")
        elif name == "back":
            out.add("left" if right else "right")
        else:
            out.add(name)
    return out


def apply(resolved):
    pad.reset()
    for name in resolved:
        if name == "hk":
            pad.right_trigger(value=255)
        elif name in DIRECTIONS:
            pad.press_button(button=DIRECTIONS[name])
        elif name in BUTTONS:
            pad.press_button(button=BUTTONS[name])
        else:
            print("Unknown input:", name)
    pad.update()


def main():
    print("Controller running. Ctrl+C to stop.")
    last = None
    try:
        while True:
            cmd = read_json(COMMAND_PATH)
            held = cmd.get("held", []) if cmd else []
            resolved = resolve(held)
            if resolved != last:      # only talk to the driver on changes
                apply(resolved)
                last = resolved
            time.sleep(1 / 60)
    except KeyboardInterrupt:
        pass
    finally:
        pad.reset()
        pad.update()
        print("Released all inputs.")


if __name__ == "__main__":
    main()