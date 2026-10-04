# lua and python scripts to read game input/output 

This folder contains the lua script to record character game state information and python script to read it for the rest of the program. 

## Set up 

Find the Street Fighter 6 game directory on your computer and place the `dinput8.dll` file in your SF6 folder (should be on the same level as the `StreetFighter6.exe`)

Then launch the game as usual. The reframework directory will automatically be created upon launching the game. Try toggling the REFramework in-game menu with the 'Insert' button on the keyboard. If the menu appears, REFramework has been set up successfuly. 

Then exit the game and place the facingAndCharacterScript.lua into the `Street Fighter 6/reframework/autorun` directory. If the 'autorun' directory was not automatically generated, make the directory and then place the lua script in. 

## TODO Python script put where 

## Run

The scripts will automatically run each time you boot up the SF6 game. 