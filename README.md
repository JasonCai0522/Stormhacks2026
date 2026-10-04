# Stormhacks2026

## Project layout

- `run_controller.py`: main entry point combining all three inputs.
- `game_state.py`: typed game-state snapshots, validation, and JSON loading.
- `computer-vision/`: pose detection, webcam tools, and downloaded models.
- `game-controller/`: virtual Xbox controller, game-state reader, and SF6 REFramework integration.
- `microcontroller/`: ESP32 connection tools.
- `tests/`: tests for the main controller integration.

## Street Fighter 6 controller

Run one program to combine webcam movement, ESP32 attacks, and the facing-state
JSON loaded by `game_state.py`. The program passes the snapshot's facing direction
to `game-controller/controller.py` and uses its `resolve()` and `apply()` functions
for facing and virtual Xbox output.
The main program uses `BluetoothReceiver` in `microcontroller/bluetooth.py` for
incoming attack strings. That module currently connects through a serial COM
port; transport changes belong there as the Bluetooth implementation develops.
Do not run its standalone listener alongside the main program.

Voice attacks are enabled automatically when `ELEVENLABS_API_KEY` or `API_KEY`
is set in the environment or the repository-root `.env` file. Without a key,
voice is skipped and the other inputs keep working. Only `Hadouken` is currently
supported (`Hadoken` is accepted too). `VOICE_COMMAND_CONTROLS` in
`speech-to-text/voicelines.py` maps it to the `special` input understood by
`controller.py`, which presses Xbox Y with the default Modern layout.
For Ryu/Ken, Hadouken requires neutral + Special. Voice temporarily overrides
webcam directions and ESP32 attacks, releases all inputs for one frame, then
presses Special for the rest of the `--attack-timeout` window (default 0.25 s).
Normal inputs resume afterward. Select Modern controls and a character with
this shortcut; voice does not change the character's airborne state.
See the [Ryu Modern command guide](https://note.com/utontsuyu_room/n/n428a41694ecc?hl=en).
Use `--no-voice` to disable voice explicitly.
Microphone or transcription failures disable voice for that run.

Voice uses the default microphone and sends non-silent three-second recordings
to ElevenLabs Scribe v2 in a background thread. Commands take effect after the
recording and API response; the microphone pauses while transcribing. The webcam
loop continues throughout. Do not run `speech-to-text/voicelines.py` alongside
the controller; that script can be used on its own to check voice recognition.

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

This mode skips loading the Bluetooth module and opening its connection. Voice
attacks remain available when a key is configured. Add `--no-voice` for movement only.

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
