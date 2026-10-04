# Street Fighter 6 Game Controller and State Integration

The root `game_state.py` loads the game's JSON into a validated `GameState`
snapshot. `run_controller.py` reads one snapshot each frame and passes its
facing direction to `controller.resolve(held, facing=...)`. `controller.py`
resolves forward/back and applies inputs to the virtual Xbox controller.

## Game setup

1. Copy `dinput8.dll` into the Street Fighter 6 installation directory, beside
   `StreetFighter6.exe`.
2. Launch SF6 so REFramework creates its directories. Press Insert to check that
   the REFramework menu appears, then exit the game.
3. Copy `facingAndCharacterScript.lua` into `Street Fighter 6/reframework/autorun/`.

The Lua script runs automatically with SF6 and exports `p1_character.json` into
`reframework/data/`. Keep `controller.py` in this repository.
`GAME_STATE_PATH` in the root `game_state.py` must point to that JSON file, or use the main entry point's
`--game-state` option to supply the location.

`GameState` represents `p1_facing`, `p1_health`, `p1_health_old`, `p1_name`,
`p1_side`, and `p1_take_damage`. Facing/side values are `left` or `right`;
health values, when supplied, are integers from 0 to 10000; the name must be a
recognized SF6 character. The existing Lua exporter omits health/damage fields,
so absent health/name values remain `None` and damage defaults to `False`.
The side signal takes precedence over facing, as before. Missing, partially
written, or invalid JSON returns no snapshot; the main loop defaults to facing
right and retries on the next frame.

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
