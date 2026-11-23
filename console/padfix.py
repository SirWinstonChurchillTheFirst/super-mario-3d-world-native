#!/usr/bin/env python3
# Nova: Controller-Belegung fuer native Ports ergaenzen.
# Batocera uebergibt nativen Programmen die Belegung aller angemeldeten Controller in SDL_GAMECONTROLLERCONFIG
# (abgeleitet aus der Menue-Belegung). Controller ohne Analogstick (Wii-Fernbedienung, NES-/SNES-Pads ...)
# koennen damit in Spielen, die nur den Stick lesen, nicht lenken. Dieses Skript gibt die Belegung ergaenzt aus:
#   - kein linker Stick vorhanden  -> Steuerkreuz wirkt zusaetzlich als linker Stick
#   - Wii-Fernbedienung (ohne Classic Controller): Tasten 1 / 2 werden linker / rechter Trigger (Item / Driften)
# Aufruf im Startskript:  export SDL_GAMECONTROLLERCONFIG="$(python3 /userdata/system/nova/padfix.py)"
#
# Profil "quer" (nur fuer Spiele, die es ausdruecklich anfordern, z. B. New Super Mario Bros. U nativ):
#   python3 padfix.py --quer --sdl3      (--quer auch per NOVA_PADFIX_PROFIL=quer; --sdl3 siehe unten)
# Die Wii-Fernbedienung wird QUER gehalten (Steuerkreuz links, 1/2 rechts) und spielt sich wie auf der Wii U:
#   2 -> Wii-U-A (springen / bestaetigen)        1 -> Wii-U-Y (rennen / Feuerball)
#   A -> Wii-U-R (Drehsprung; Schuetteln loest ueber wiishake.py ebenfalls A aus)
#   B (Abzug) -> Wii-U-B (zurueck im Menue)      Plus/Minus/Home unveraendert
#   Steuerkreuz um 90 Grad gedreht (Pfeil "hoch" der Fernbedienung zeigt quer nach links)
# Das Spiel (nsmbu-recomp) liest Nintendo-Belegung nach Position: SDL "b" (Ost) = Wii-U-A, SDL "a" (Sued) = Wii-U-B,
# SDL "x" (West) = Wii-U-Y, SDL "y" (Nord) = Wii-U-X. Andere Spiele/Controller bleiben unveraendert.
#
# Profil "quer-ab" (Wii-U-Spiele der cafe-Laufzeit, die nur GamePad/Pro Controller kennen; gesetzt vom Wii-U-launch.sh):
#   python3 padfix.py --profil=quer-ab     (oder NOVA_PADFIX_PROFIL=quer-ab)
# Wii-Fernbedienung QUER wie ein NES-Pad:  2 -> Wii-U-A (bestaetigen / springen)   1 -> Wii-U-B (zurueck / rennen)
#   A -> Wii-U-X     B (Abzug) -> Wii-U-Y     Plus/Minus/Home unveraendert, Steuerkreuz um 90 Grad gedreht.
# Profil "quer-kart": wie quer-ab, aber B (Abzug) -> Wii-U-R (Driften) und A -> Wii-U-L (Item).
import os
import sys

PROFIL = os.environ.get("NOVA_PADFIX_PROFIL", "")
for _a in sys.argv[1:]:
    if _a == "--quer":
        PROFIL = "quer"
    elif _a.startswith("--profil="):
        PROFIL = _a.split("=", 1)[1]
QUER = PROFIL in ("quer", "quer-ab", "quer-kart")
# SDL-Namen nach Position: "b" Ost = Wii-U-A, "a" Sued = Wii-U-B, "x" West = Wii-U-Y, "y" Nord = Wii-U-X
QUER_TASTEN = {
    "quer": (("b", "2"), ("x", "1"), ("a", "B"), ("rightshoulder", "A")),
    "quer-ab": (("b", "2"), ("a", "1"), ("y", "A"), ("x", "B")),
    # Rennspiele (Mario Kart 8 am GamePad): 2 = A (Gas), 1 = B (Bremse), B (Abzug) = R (Driften), A = L (Item)
    "quer-kart": (("b", "2"), ("a", "1"), ("rightshoulder", "B"), ("leftshoulder", "A")),
}
# --sdl3: das Spiel nutzt SDL3 (nsmbu-recomp, Wii-U-cafegame, 3DS-Player, Solstice, eidos, Strikers, SPM ...).
# SDL3 nummeriert die Tasten eines Linux-Geraets anders als das SDL2 des Menues (es_input.cfg): erst alle Codes
# ab BTN_JOYSTICK (0x120) aufsteigend, dann die darunter (SDL2 hier: alle aufsteigend). Bei der Wii-Fernbedienung
# (Pfeile und 1/2 liegen unter 0x120) verschiebt das jede Taste - am 22.11.2026 mit den SDL3-Bibliotheken 3.4.2,
# 3.4.4 und 3.4.18 und einer virtuellen Fernbedienung nachgemessen. Umgerechnet wird nur fuer Geraete
# "Nintendo Wii Remote..." (Tastenliste aus dem echten Geraet, sonst die feste Liste von hid-wiimote);
# Xbox- und andere Pads bleiben unveraendert.
SDL3 = "--sdl3" in sys.argv[1:]
# Tasten des Treibers hid-wiimote: hoch links rechts runter 1 2 A B Home Plus Minus
WIIMOTE_CODES = [103, 105, 106, 108, 257, 258, 304, 305, 316, 407, 412]


def geraete_tasten(name):
    """Tastencodes des angeschlossenen Geraets mit diesem Namen (aufsteigend) oder None."""
    try:
        import evdev
        for path in evdev.list_devices():
            d = evdev.InputDevice(path)
            try:
                if d.name == name:
                    return sorted(d.capabilities().get(evdev.ecodes.EV_KEY, []))
            finally:
                d.close()
    except Exception:
        pass
    return WIIMOTE_CODES if name == "Nintendo Wii Remote" else None


def sdl3_umrechnen(name, kv):
    """Tastennummern ("b6") einer Wii-Fernbedienung von SDL2- auf SDL3-Zaehlung umstellen."""
    codes = geraete_tasten(name)
    if not codes:
        return kv
    sdl3 = [c for c in codes if c >= 0x120] + [c for c in codes if c < 0x120]
    if sdl3 == codes:
        return kv
    neu = {}
    for k, v in kv.items():
        if k != "platform" and v.startswith("b") and v[1:].isdigit() and int(v[1:]) < len(codes):
            v = "b%d" % sdl3.index(codes[int(v[1:])])
        neu[k] = v
    return neu


# Tasten-Nummern der Wii-Fernbedienung bei SDL2 (aufsteigender Tastencode, wie in es_input.cfg):
#   0 hoch  1 links  2 rechts  3 runter  4 "1"  5 "2"  6 A  7 B  8 Home  9 Plus  10 Minus
# Die Nummern werden aus der Menue-Belegung gelesen, nicht fest angenommen.


def quer_belegung(kv):
    """Wii-Fernbedienung quer: neue Belegung aus der aufrechten Menue-Belegung ableiten."""
    phys = {
        "A": kv.get("a"), "B": kv.get("b"), "1": kv.get("y"), "2": kv.get("x"),
        "hoch": kv.get("dpup"), "runter": kv.get("dpdown"), "links": kv.get("dpleft"), "rechts": kv.get("dpright"),
    }
    if not all(phys.values()):
        return None
    neu = [("platform", kv["platform"])] if "platform" in kv else []
    for k, taste in QUER_TASTEN[PROFIL]:
        neu.append((k, phys[taste]))
    for k, v in (("dpleft", phys["hoch"]), ("dpright", phys["runter"]), ("dpup", phys["rechts"]),
                 ("dpdown", phys["links"])):
        neu.append((k, v))
    for k in ("start", "back", "guide"):
        if k in kv:
            neu.append((k, kv[k]))
    return neu


out = []
for line in os.environ.get("SDL_GAMECONTROLLERCONFIG", "").splitlines():
    parts = [p for p in line.strip().split(",") if p != ""]
    if len(parts) < 3:
        if line.strip():
            out.append(line.strip())
        continue
    head, fields = parts[:2], parts[2:]
    name = head[1]
    kv = {}
    order = []
    for f in fields:
        k, _, v = f.partition(":")
        kv[k] = v
        order.append(k)

    def put(k, v):
        if k not in kv:
            order.append(k)
        kv[k] = v

    neu = quer_belegung(kv) if QUER and name == "Nintendo Wii Remote" and "leftx" not in kv else None
    if neu:
        kv = dict(neu)
        order = [k for k, _ in neu]
    elif "Wii Remote" in name and "Classic" not in name and "leftx" not in kv:
        for src, dst in (("y", "lefttrigger"), ("x", "righttrigger")):
            if src in kv and dst not in kv:
                put(dst, kv.pop(src))
                order.remove(src)
    if not any(k.lstrip("+-") == "leftx" for k in kv) and "dpleft" in kv and "dpright" in kv:
        put("-leftx", kv["dpleft"])
        put("+leftx", kv["dpright"])
    if not any(k.lstrip("+-") == "lefty" for k in kv) and "dpup" in kv and "dpdown" in kv:
        put("-lefty", kv["dpup"])
        put("+lefty", kv["dpdown"])
    if SDL3 and name.startswith("Nintendo Wii Remote"):
        kv = sdl3_umrechnen(name, kv)
    out.append(",".join(head + ["%s:%s" % (k, kv[k]) for k in order]) + ",")
sys.stdout.write("\n".join(out))
