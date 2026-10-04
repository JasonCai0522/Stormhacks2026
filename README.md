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

## BLE punch and hook debugging

Flash `microcontroller/microcontroller_code.cpp` as an ESP32 Arduino sketch.
Keep both sensors still during startup so the self-test can estimate gyro bias.
The sketch sends acceleration changes and gyroscope readings at about 100 Hz,
using two 17-byte BLE notifications per sample. `imu_client.py` pairs the hand
packets by timestamp. Its legacy 17-byte acceleration-only format is still
supported, but cannot classify hooks.
Gyro range and scaling follow the manufacturer's
[MPU6050 register map](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Register-Map.pdf).

```powershell
python -m pip install bleak
python microcontroller/punch_detector.py
```

Output distinguishes `LEFT_STRAIGHT_LIGHT`, `LEFT_STRAIGHT_HARD`,
`LEFT_HOOK_LIGHT`, `LEFT_HOOK_HARD`, and the corresponding `RIGHT` events.
It prints peak acceleration change, peak gyro speed in degrees/second, and
estimated net turn in degrees. This standalone debugger does not send these
events to `run_controller.py`.

Tune each hand separately in `punch_detector.py`'s `CONFIG`. `hard_g=0.90`
classifies the confirmed acceleration-change peak; it does not measure impact
force. Hooks require a confirmed acceleration burst, a gyro peak of at least
`hook_gyro_dps=180`, and net rotation of at least `hook_turn_deg=12` over the
preceding `hook_window_ms=120`. These are provisional thresholds, evaluated
at punch confirmation. Later rotation does not upgrade an emitted straight
punch to a hook.

Set `METER=True` to inspect timestamped per-hand acceleration magnitudes and
gyro axes while throwing straight punches and hooks. Secure the sensors in
consistent positions. If wrist twists get labelled as hooks, set `hook_axis`
to the axis corresponding to the hook's sweep (`0=X`, `1=Y`, `2=Z`);
`None` uses all axes. Raise the hook speed/turn thresholds if straight punches
get labelled as hooks; lower them if hooks get labelled as straight punches.
Gyroscope readings describe sensor rotation, so a curved hand path without
much sensor rotation may still be classified as straight.

Replay the decoder and detector tests without hardware:

```powershell
python -m unittest discover -s tests -p test_imu_client.py
python -m unittest discover -s tests -p test_punch_detector.py
```
