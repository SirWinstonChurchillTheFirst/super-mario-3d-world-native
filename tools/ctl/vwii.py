#!/usr/bin/env python3
# vwii.py: a stand-in Wii Remote for tests ON THE CONSOLE (uinput), shaped like the kernel driver hid-wiimote makes
# the real one: "Nintendo Wii Remote" (keys), optionally "... Accelerometer" / "... IR" / "... Nunchuk", same
# vendor/product/version as the user's remote (GUID 050000007e0500000603000000060000), same phys on all parts.
#   vwii.py --wait 20 --seq "up,left,right,down,1,2,a,b,plus,minus" [--hold 0.5] [--gap 1.0]
#           [--parts accel,ir,nunchuk] [--acc x,y,z] (raw, 100 = 1 g; flat = 0,0,100)
# A step "name=seconds" holds that long; "acc=x/y/z" changes the accelerometer; "ir=x/y" points (0..1023, 0..767);
# "stick=x/y" moves the Nunchuk stick (-100..100); "wait=seconds" pauses. Prints each step with its time since start.
import argparse, sys, time
from evdev import UInput, AbsInfo, ecodes as e

KEYS = {"up": 103, "left": 105, "right": 106, "down": 108, "1": 257, "2": 258, "a": 304, "b": 305,
        "home": 316, "plus": 407, "minus": 412}
ap = argparse.ArgumentParser()
ap.add_argument("--wait", type=float, default=15)
ap.add_argument("--seq", default="")
ap.add_argument("--hold", type=float, default=0.5)
ap.add_argument("--gap", type=float, default=1.0)
ap.add_argument("--parts", default="")
ap.add_argument("--acc", default="0,0,100")
ap.add_argument("--tail", type=float, default=1.0)
a = ap.parse_args()
ID = dict(vendor=0x057E, product=0x0306, version=0x0600, bustype=0x05, phys="vwii-test")
parts = [p for p in a.parts.split(",") if p]
keys = UInput({e.EV_KEY: sorted(KEYS.values())}, name="Nintendo Wii Remote", **ID)
acc = ir = nun = None
if "accel" in parts:
    acc = UInput({e.EV_ABS: [(c, AbsInfo(0, -500, 500, 2, 4, 0)) for c in (e.ABS_RX, e.ABS_RY, e.ABS_RZ)]},
                 name="Nintendo Wii Remote Accelerometer", **ID)
if "ir" in parts:
    ir = UInput({e.EV_ABS: [(c, AbsInfo(1023, 0, 1023 if i % 2 == 0 else 767, 2, 4, 0))
                            for i, c in enumerate(range(e.ABS_HAT0X, e.ABS_HAT3Y + 1))]},
                name="Nintendo Wii Remote IR", **ID)
if "nunchuk" in parts:
    nun = UInput({e.EV_KEY: [e.BTN_C, e.BTN_Z],
                  e.EV_ABS: [(c, AbsInfo(0, -120, 120, 2, 4, 0)) for c in (e.ABS_HAT0X, e.ABS_HAT0Y)] +
                            [(c, AbsInfo(0, -500, 500, 2, 4, 0)) for c in (e.ABS_RX, e.ABS_RY, e.ABS_RZ)]},
                 name="Nintendo Wii Remote Nunchuk", **ID)
t0 = time.monotonic()


def say(*x):
    print("%7.2f" % (time.monotonic() - t0), *x, flush=True)


def set_acc(dev, v):
    for c, x in zip((e.ABS_RX, e.ABS_RY, e.ABS_RZ), v):
        dev.write(e.EV_ABS, c, int(x))
    dev.syn()


say("devices up:", "keys", *parts)
cur = [float(x) for x in a.acc.split(",")]
end = t0 + a.wait
n = 0
while time.monotonic() < end:      # the accelerometer talks all the time, as the real one
    if acc:
        n += 1
        set_acc(acc, [cur[0], cur[1], cur[2] + (n % 2)])
    time.sleep(0.05)
for step in [s for s in a.seq.split(",") if s]:
    name, _, arg = step.partition("=")
    if name == "wait":
        time.sleep(float(arg)); continue
    if name == "acc":
        cur = [float(x) for x in arg.split("/")]
        if acc: set_acc(acc, cur)
        say("acc", cur); time.sleep(a.gap); continue
    if name == "ir":
        x, y = [int(v) for v in arg.split("/")]
        if ir:
            for c, v in ((e.ABS_HAT0X, x - 60), (e.ABS_HAT0Y, y), (e.ABS_HAT1X, x + 60), (e.ABS_HAT1Y, y)):
                ir.write(e.EV_ABS, c, v)
            ir.syn()
        say("ir", x, y); time.sleep(a.gap); continue
    if name == "stick":
        x, y = [int(v) for v in arg.split("/")]
        if nun:
            nun.write(e.EV_ABS, e.ABS_HAT0X, x); nun.write(e.EV_ABS, e.ABS_HAT0Y, y); nun.syn()
        say("stick", x, y); time.sleep(a.gap); continue
    if name == "shake":
        say("shake")
        for i in range(int(float(arg or 0.6) / 0.03)):
            if acc: set_acc(acc, [cur[0], cur[1] + (300 if i % 2 else -300), cur[2] + (250 if i % 4 < 2 else -250)])
            time.sleep(0.03)
        if acc: set_acc(acc, cur)
        time.sleep(a.gap); continue
    dev, code = (nun, {"c": e.BTN_C, "z": e.BTN_Z}[name]) if name in ("c", "z") else (keys, KEYS[name])
    if dev is None:
        continue
    hold = float(arg) if arg else a.hold
    say("press", name)
    dev.write(e.EV_KEY, code, 1); dev.syn()
    time.sleep(hold)
    dev.write(e.EV_KEY, code, 0); dev.syn()
    time.sleep(a.gap)
say("done")
time.sleep(a.tail)
for d in (keys, acc, ir, nun):
    if d: d.close()
