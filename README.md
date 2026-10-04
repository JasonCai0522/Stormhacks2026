# Stormhacks2026

## Project layout

- `run_controller.py`: main entry point combining webcam movement and BLE punches.
- `computer-vision/`: pose detection, webcam tools, and downloaded models.
- `game-controller/`: virtual Xbox controller, game-state reader, and SF6 REFramework integration.
- `microcontroller/`: ESP32 connection tools.
- `tests/`: tests for the main controller integration.

## Street Fighter 6 controller

Run one program to combine webcam movement, ESP32 attacks, and the facing-state
JSON used by `game-controller/controller.py`. The program imports that controller and
uses its `resolve()` and `apply()` functions for facing and virtual Xbox output.
By default, the main program connects to `ESP32-IMU` over BLE using
`microcontroller/IMU_client.py`, classifies its samples with `punch_detector.py`,
and sends the resulting attacks through `ble_attacks.py`. Run only the main
program while playing; the standalone punch debugger uses the same BLE device.

From the repository root:

```bash
python -m pip install -r requirements.txt
python computer-vision/download_model.py
python run_controller.py
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

Use the acceleration+gyro firmware in `microcontroller/microcontroller_code.cpp`.
The gesture mapping is:

| Gesture | Game input | Default Modern Xbox button |
| --- | --- | --- |
| Left straight | light | X |
| Left uppercut | medium | A |
| Right straight | heavy | B |
| Right uppercut | special | Y |

These game button names do not classify punch strength. Each detected gesture
presses its button for 100 ms, then releases it. Adjust the press duration with
`--attack-pulse 0.08` (seconds). Punches are queued with a released frame between
them so repeated punches produce separate button presses. Old queued punches
expire after 500 ms; a disconnect or 500 ms without complete samples clears
attacks. BLE scanning/reconnection runs in the background while webcam movement
continues. Punch debug measurements still print in the same console. Detection
thresholds and uppercut axes remain in `punch_detector.py`'s `CONFIG`.

The previous newline-based COM-port receiver is available with
`python run_controller.py --transport serial --port COM4 --baud 115200`.
Providing `--port` or `--baud` without a transport also selects serial mode.
That mode expects `light`, `medium`, `heavy`, or `special` messages and uses
`--attack-timeout` (default 250 ms) to release an attack after messages stop.

Movement uses the existing priority: jump (up), crouch (down), forward lean
(forward), backward lean (back), otherwise neutral. Forward/back are resolved by
`controller.py` every frame, so they change direction when the characters swap
sides. Movement and an attack can be held together; diagonal movement is deferred.
Missing poses release movement. Keep the feet visible and start grounded for
jump calibration. Press q, Escape, or Ctrl+C to stop and release all inputs.
Camera/reader errors also exit and release inputs.

Run the input integration tests without hardware:

```bash
python -m unittest discover -s tests -p test_controller_inputs.py
python -m unittest discover -s tests -p test_ble_attacks.py
```

## BLE punch and uppercut debugging

Flash `microcontroller/microcontroller_code.cpp` as an ESP32 Arduino sketch.
Keep both sensors still during startup so the self-test can estimate gyro bias.
The sketch sends acceleration changes and gyroscope readings at about 100 Hz,
using two 17-byte BLE notifications per sample. `imu_client.py` pairs the hand
packets by timestamp. Its legacy 17-byte acceleration-only format is still
supported, but cannot classify uppercuts.
Gyro range and scaling follow the manufacturer's
[MPU6050 register map](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Register-Map.pdf).

```powershell
python -m pip install bleak
python microcontroller/punch_detector.py
```

Output distinguishes `LEFT_STRAIGHT`, `LEFT_UPPERCUT`, `RIGHT_STRAIGHT`,
and `RIGHT_UPPERCUT`.
It prints peak acceleration change, peak gyro speed in degrees/second, and
estimated net turn in degrees. The standalone debugger only prints events;
`run_controller.py` uses the same classifier and receives its events directly.

Tune each hand separately in `punch_detector.py`'s `CONFIG`.
Uppercuts require a confirmed acceleration burst, a gyro peak of at least
`uppercut_gyro_dps=180`, and net rotation of at least `uppercut_turn_deg=12` over the
preceding `uppercut_window_ms=120`. These are provisional thresholds, evaluated
at punch confirmation. Later rotation does not upgrade an emitted straight
punch to an uppercut. Net rotation must be dominated by the selected upward-swing
axis (`uppercut_axis_share=0.70`), rather than an arbitrary axis.

Set `METER=True` to inspect timestamped per-hand acceleration magnitudes and
gyro axes while throwing straight punches and uppercuts. Secure the sensors in
consistent positions. Set `uppercut_axis` to the axis of rotation during the
upward swing (`0=X`, `1=Y`, `2=Z`). The default `0` assumes the sensor's X axis
runs across the hand, Y points toward the knuckles, and Z points out of the back
of the hand. Remap this separately for each hand if the boards are oriented
differently. All-axis classification is disabled to help separate upward swings
from horizontal sweeps and fist rolls.

`uppercut_direction=0` initially accepts either rotation sign. Once the upward
sign is known from the meter, set it to `1` or `-1` to exclude downward rotation.
The sign can differ between hands. Raise the uppercut speed/turn thresholds if straight punches
get labelled as uppercuts; lower them if uppercuts get labelled as straight punches.
Gyroscope readings describe sensor rotation, so a curved hand path without
much sensor rotation may still be classified as straight.

Replay the decoder and detector tests without hardware:

```powershell
python -m unittest discover -s tests -p test_imu_client.py
python -m unittest discover -s tests -p test_punch_detector.py
```
