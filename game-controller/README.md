# Street Fighter 6 Game Controller and State Integration

`controller.py` reads the game's facing-state JSON, resolves forward/back, and
applies inputs to the virtual Xbox controller. The root `run_controller.py`
imports this module and manages the input loop and shutdown.

## Game setup

1. Copy `dinput8.dll` into the Street Fighter 6 installation directory, beside
   `StreetFighter6.exe`.
2. Launch SF6 so REFramework creates its directories. Press Insert to check that
   the REFramework menu appears, then exit the game.
3. Copy `facingAndCharacterScript.lua` into `Street Fighter 6/reframework/autorun/`.

The Lua script runs automatically with SF6 and exports `p1_character.json` into
`reframework/data/`. Keep `controller.py` in this repository. Its
`GAME_STATE_PATH` must point to that JSON file, or use the main entry point's
`--game-state` option to supply the location.

## Controller bindings

Select Modern controls in SF6. The default Xbox mappings below are defined in
`BUTTONS` in `controller.py`; edit them if you use custom bindings.

| Input | Xbox button |
| --- | --- |
| `light` | X |
| `medium` | A |
| `heavy` | B |
| `special` | Y |
| `assist` | RT |
| `throw` | LT |
| `drive_impact` | LB |
| `drive_parry` | RB |

`forward` and `back` follow the character's position relative to the opponent.
`up`, `down`, `left`, and `right` are absolute directions. The controller accepts
multiple inputs together, such as `{"down", "medium"}`.

## Run

From the repository root:

```bash
python run_controller.py --port COM4
```

See the [project README](../README.md) for dependencies and input behavior.
