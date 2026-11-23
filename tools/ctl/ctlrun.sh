#!/bin/bash
# ctlrun.sh NAME "PORTS TITLE" WAIT "SEQ" [PARTS] [EXTRA ENV]: runs ON THE CONSOLE. Starts the port through the menu's
# interface with a stand-in Wii Remote (vwii.py) plugged in, presses SEQ from second WAIT, then ends the game.
# Prints what the game received: pad record (TTT2_INPUT_RECORD), "wiimote:" trace lines, the controller mapping.
NAME=$1; TITLE=$2; WAIT=${3:-20}; SEQ=$4; PARTS=$5; EXTRA=$6
B=/userdata/ports-native/wiiu/$NAME
run=$(curl -s -m 3 localhost:1234/runningGame)
echo "$run" | grep -q "NO GAME RUNNING\|\"name\": \"Nova Home\"" || { echo "stop: a game is running"; exit 1; }
pgrep -x cafegame >/dev/null && { echo "stop: cafegame runs"; exit 1; }
rm -f /tmp/padrec.txt /tmp/sdlcfg.txt /tmp/ctl-*.jpg /tmp/vwii.log
python3 /tmp/vwii.py --wait $WAIT --seq "$SEQ" --parts "$PARTS" ${VWII_ARGS} > /tmp/vwii.log 2>&1 &
V=$!
sleep 4
if [ -d "$B" ]; then
rm -rf $B/save-ctl; [ -n "$KEEP_SAVE" ] || mkdir -p $B/save-ctl
cat > /tmp/wiiutest.env <<EOT
export TTT2_INPUT_RECORD=/tmp/padrec.txt TTT2_TRACE_WIIMOTE=1 $EXTRA
[ -n "$KEEP_SAVE" ] || export CAFE_SAVE_DIR=$B/save-ctl
EOT
fi
curl -s -m 5 -X POST localhost:1234/launch -d "/userdata/roms/ports/$TITLE.sh" >/dev/null
n=0
for i in $(seq 1 150); do            # until the stand-in remote is done (timeout 300 s)
  kill -0 $V 2>/dev/null || break
  sleep 2; n=$((n+1))
  if [ -n "$SHOTS" ] && [ $((n % SHOTS)) = 0 ]; then
    DISPLAY=:0.0 ffmpeg -loglevel error -y -f x11grab -i :0.0 -frames:v 1 -vf scale=640:-1 -q:v 5 /tmp/ctl-$(printf %03d $n).jpg
  fi
done
kill $V 2>/dev/null
DISPLAY=:0.0 ffmpeg -loglevel error -y -f x11grab -i :0.0 -frames:v 1 -vf scale=640:-1 -q:v 5 /tmp/ctl-end.jpg
pgrep -x cafegame >/dev/null && echo "game alive at the end" || echo "GAME NOT RUNNING at the end"
sensors 2>/dev/null | grep -i "tctl\|edge" | tr '\n' ' '; echo
rm -f /tmp/wiiutest.env
curl -s -m 5 localhost:1234/emukill >/dev/null; sleep 6
for p in cafegame $KILL; do pgrep -x $p >/dev/null && { echo "still running after emukill: $p -> kill"; pkill -x $p; sleep 2; }; done
[ -d "$B" ] && rm -rf $B/save-ctl
echo "== vwii"; cat /tmp/vwii.log
echo "== mapping"; grep -i "wii remote\|CAFE_WIIMOTE" /userdata/system/logs/native-wiiu-$NAME.log.pads 2>/dev/null
echo "== pad record"; head -c 3000 /tmp/padrec.txt
echo "== wiimote trace"; grep -a "wiimote" /userdata/system/logs/native-wiiu-$NAME.log 2>/dev/null | head -${TRACE_LINES:-60}
echo "== after"; curl -s -m 3 localhost:1234/runningGame | grep -m1 '"name"\|NO GAME'
for id in $(DISPLAY=:0.0 xinput list --id-only); do DISPLAY=:0.0 xinput query-state $id 2>/dev/null | grep -q '=down' && echo "KEY HELD DOWN on input device $id"; done
ls /dev/input/ | tr '\n' ' '
