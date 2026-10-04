# Lua and Python Scripts to Read Game Input/Output 

This folder contains the lua script to record character game state information and python script to read it for the rest of the program. 

The scripts in this file need to be manually placed in the game directory on your machine.

## Setup 

Find the Street Fighter 6 game directory on your computer and place the `dinput8.dll` file in your SF6 folder (should be on the same level as the `StreetFighter6.exe`)

Then launch the game as usual. The reframework directory will automatically be created upon launching the game. Try toggling the REFramework in-game menu with the 'Insert' button on the keyboard. If the menu appears, REFramework has been set up successfuly. 

Then exit the game and place the facingAndCharacterScript.lua into the `Street Fighter 6/reframework/autorun` directory.

## TODO Python script put where 

## Python controller (Modern controls)

Select **Modern** controls in Street Fighter 6 and use the default Xbox
bindings, or edit `BUTTONS` in `controller.py` to match your custom bindings.
Run `python controller.py` separately. It reads `inputs.json` from the directory
you run it in and holds all requested inputs simultaneously.

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

For down + medium, write this to `inputs.json`:

```json
{"held": ["down", "medium"]}
```

`{"held": ["down medium"]}` and `{"held": "down+medium"}` also work.
Combine any directions and buttons this way, such as `"forward+special"`,
`"assist+heavy"`, or `"down+back+light"`. `forward` and `back` follow the
character's facing direction; `up`, `down`, `left`, and `right` are absolute.
`drive impact` and `drive parry` are accepted as well as their underscore names.

Write `{"held": []}` to release every input. To press the same attack again,
release it first, then add it again; leave each change in place for at least a
game frame (the controller polls at 60 Hz). Ctrl+C also releases all inputs.

## Run

The Lua script runs automatically each time you boot up SF6. Start the Python
controller separately as described above.
