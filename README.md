# Stormhacks2026

## Project layout

- `run_controller.py`: main entry point combining all three inputs.
- `computer-vision/`: pose detection, webcam tools, and downloaded models.
- `game-controller/`: virtual Xbox controller, game-state reader, and SF6 REFramework integration.
- `microcontroller/`: ESP32 connection tools.
- `tests/`: tests for the main controller integration.

## Street Fighter 6 controller

Run one program to combine webcam movement, ESP32 attacks, and the facing-state
JSON used by `game-controller/controller.py`. The program imports that controller and
uses its `resolve()` and `apply()` functions for facing and virtual Xbox output.
The main program uses `BluetoothReceiver` in `microcontroller/bluetooth.py` for
incoming attack strings. That module currently connects through a serial COM
port; transport changes belong there as the Bluetooth implementation develops.
Do not run its standalone listener alongside the main program.

From the repository root:

```bash
python -m pip install -r requirements.txt
python computer-vision/download_model.py
python run_controller.py --port COM4 --baud 115200
```

To run webcam movement and gamepad control before Bluetooth is set up:

```bash
python run_controller.py --no-bluetooth
```

This mode skips loading the Bluetooth module and opening its connection. Attack
buttons remain released; facing resolution and movement work as usual.

The virtual controller requires Windows and the ViGEmBus driver used by
`vgamepad`. Configure SF6 with Modern controls. The existing controller's button
mappings and facing-state path are used directly. To change the JSON location:

```bash
python run_controller.py --game-state "C:/path/to/reframework/data/p1_character.json"
```

The ESP32 must send newline-terminated strings: `light`, `medium`, `heavy`, or
`special`. Repeat the current attack while the gesture is active. Each valid
message holds that attack and replaces the previous attack. The attack releases
after 250 ms without another valid message; adjust this to your message interval
with `--attack-timeout 0.5` (seconds). Unknown messages are ignored.

Movement uses the existing priority: jump (up), crouch (down), forward lean
(forward), backward lean (back), otherwise neutral. Forward/back are resolved by
`controller.py` every frame, so they change direction when the characters swap
sides. Movement and an attack can be held together; diagonal movement is deferred.
Missing poses release movement. Keep the feet visible and start grounded for
jump calibration. Press q, Escape, or Ctrl+C to stop and release all inputs.
Camera/serial errors also exit and release inputs.

Run the input integration tests without hardware:

```bash
python -m unittest discover -s tests -p test_controller_inputs.py
```
