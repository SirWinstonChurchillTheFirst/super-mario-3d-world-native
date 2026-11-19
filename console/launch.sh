#!/bin/bash
# Starts a Wii U game built with the cafe runtime on the Batocera box: launch.sh <name> "<game folder>"
#   name = folder under /userdata/ports-native/wiiu (3dworld, tennis, ...), holds cafegame, fonts/, save/
# Called from the hidden ports script "/userdata/roms/ports/<Title> (Nativ).sh".
# NOT RUN ON THE CONSOLE YET (19 November: prepared on the PC only).
NAME=$1
GAME=$2
BASE=/userdata/ports-native/wiiu/$NAME
cd "$BASE" || exit 1
[ -n "$DISPLAY" ] || export DISPLAY=:0.0
# shaderc comes with the Wii ports; everything else the binary needs is part of Batocera 43
export LD_LIBRARY_PATH=/userdata/ports-native/wiiu/lib:/userdata/ports-native/wiirecomp/lib
# Controllers through the normal input system, with the menu's mapping (as the other native ports)
export SDL_JOYSTICK_HIDAPI=0 SDL_JOYSTICK_HIDAPI_WII=0
export SDL_GAMECONTROLLERCONFIG="$(python3 /userdata/system/nova/padfix.py 2>/dev/null)"
export TTT2_FULLSCREEN=1 CAFE_SAVE_DIR=$BASE/save
mkdir -p "$BASE/save" /userdata/system/logs
# Extra switches for one test run (the file is gone after a restart): e.g. "export CAFE_SAVE_DIR=$BASE/save-test"
[ -f /tmp/wiiutest.env ] && . /tmp/wiiutest.env
./cafegame "$GAME" > /userdata/system/logs/native-wiiu-$NAME.log 2>&1 &
game=$!
trap 'kill $game 2>/dev/null; sleep 3; kill -9 $game 2>/dev/null' TERM INT HUP
wait $game
