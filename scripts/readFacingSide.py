import json
import time

PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Street Fighter 6\reframework\data\p1_character.json"  # adjust to your install

def get_p1_state():
    try:
        with open(PATH, "r") as f:
            data = json.load(f)
        return {
            "name": data.get("p1_name") or None,
            "facing": data.get("p1_facing") or None,
            "side": data.get("p1_side") or None,
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return None

last = None
while True:
    state = get_p1_state()
    if state != last:
        last = state
        print(state)
    time.sleep(0.05)