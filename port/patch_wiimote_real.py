#!/usr/bin/env python3
r"""Real Wii Remotes as Wii Remotes, everything else as before: CAFE_WIIMOTE=real.

usage: patch_wiimote_real.py RUNTIME_DIR   (after patch_wiimote.py, patch_wiimote_mpls.py)

Before: CAFE_WIIMOTE=1 turned EVERY host pad into a Wii Remote (+ Nunchuk) - right for titles that only take
remotes (Sochi 2014, Mario Party 10), wrong for titles that take GamePad, Pro Controllers AND remotes (Mario
Kart 8, 3D World, Tennis, Rio): there an Xbox pad must stay GamePad / Pro Controller. Without the switch a real
Wii Remote reached the title only through SDL as a "GamePad" with the menu's upright mapping (A <-> B swapped).
After, with CAFE_WIIMOTE=real:
 - real Wii Remotes (Linux, kernel driver hid-wiimote, read through evdev: buttons, accelerometer, IR, Nunchuk,
   MotionPlus) take the first KPAD channels as Wii Remotes - A is A, B is B, 1/2, +/-, D-pad, tilt, shake;
 - their SDL devices no longer count as pads (no GamePad presses, no pad slot), in CAFE_WIIMOTE=1 as well;
 - every other pad is what it was: GamePad (first) and Pro Controllers on the KPAD channels after the remotes;
 - no real remote there (or not Linux): nothing changes, a remote seen only through SDL is a pad with the
   launch script's mapping.
For unattended runs TTT2_INPUT_SCRIPT + TTT2_SCRIPT_REMOTE_ONLY=1 make remote 0 exist in this mode too
(TTT2_SCRIPT_NUNCHUK=0: without a Nunchuk, as a remote held sideways).
A channel that changes kind (remote <-> Pro Controller) is reported gone, then connected, so the title probes it.
"""
import pathlib
import sys

root = pathlib.Path(sys.argv[1])


def sub(path, old, new, count=1):
    p = root / path
    text = p.read_text()
    if new in text:
        print(f"{path}: already patched")
        return
    if text.count(old) < 1:
        sys.exit(f"{path}: not found: {old[:70]!r}")
    p.write_text(text.replace(old, new, count))
    print(f"{path}: patched")


# ---- include/cafe/input.h
sub("include/cafe/input.h",
    "bool wiimote_mode(); // CAFE_WIIMOTE=1\n",
    "bool wiimote_mode(); // CAFE_WIIMOTE=1\n"
    "// port/patch_wiimote_real.py: CAFE_WIIMOTE=real - only real Wii Remotes are Wii Remotes, other pads stay pads\n"
    "bool wiimote_real_mode();\n")

# ---- os/input.cpp
sub("src/os/input.cpp",
    r"""        const char* v = std::getenv("CAFE_WIIMOTE");
        return v != nullptr && *v != '\0' && *v != '0';
    }();
    return on;
}
""",
    r"""        const char* v = std::getenv("CAFE_WIIMOTE");
        return v != nullptr && *v != '\0' && *v != '0' && std::strcmp(v, "real") != 0;
    }();
    return on;
}

// port/patch_wiimote_real.py
bool wiimote_real_mode() {
    static const bool on = [] {
        const char* v = std::getenv("CAFE_WIIMOTE");
        return v != nullptr && std::strcmp(v, "real") == 0;
    }();
    return on;
}
""")
sub("src/os/input.cpp",
    r"""    ProChannel& c = g_pro[channel];
    c.host = state;
    if (!state.connected) {""",
    r"""    ProChannel& c = g_pro[channel];
    if (c.wiimote.connected) { // port/patch_wiimote_real.py: the channel was a Wii Remote
        c.wiimote = WiimoteState{};
        if (c.connected) g_pending_connects.push_back({channel, kWpadNoController});
        c.connected = false;
    }
    c.host = state;
    if (!state.connected) {""")
sub("src/os/input.cpp",
    r"""    ProChannel& c = g_pro[channel];
    const bool was = c.connected;
    const bool type_changed =""",
    r"""    ProChannel& c = g_pro[channel];
    if (!state.connected && !c.wiimote.connected) return; // port/patch_wiimote_real.py: not a remote's channel
    if (state.connected && c.connected && !c.wiimote.connected) { // it was a Pro Controller
        g_pending_connects.push_back({channel, kWpadNoController});
        c.connected = false;
    }
    const bool was = c.connected;
    const bool type_changed =""")

# ---- host/window.cpp
# the remotes are read before the pads are sorted (update_input), not inside update_wiimotes
sub("src/host/window.cpp",
    r"""#ifdef __linux__
    read_real_remotes();
    for (const RealRemote& r : g_real_remotes) {
        if (channel < os::wiimote::kChannels && r.state.connected) states[channel++] = r.state;
    }
#endif
    const int real = channel;""",
    r"""#ifdef __linux__
    for (const RealRemote& r : g_real_remotes) { // read in update_input (port/patch_wiimote_real.py)
        if (channel < os::wiimote::kChannels && r.state.connected) states[channel++] = r.state;
    }
#endif
    const int real = channel;""")
sub("src/host/window.cpp",
    r"""    const bool wiimotes = os::wiimote_mode(); // port/patch_wiimote.py
    const bool pros = os::pro_controllers_in_use() && !wiimotes;
    int count = 0;
    SDL_JoystickID* ids = SDL_GetGamepads(&count);
    if (pros || wiimotes) assign_pad_slots(ids, count);""",
    r"""    const bool wiimotes = os::wiimote_mode(); // port/patch_wiimote.py
    const bool real_only = os::wiimote_real_mode(); // port/patch_wiimote_real.py
    const bool pros = os::pro_controllers_in_use() && !wiimotes;
    int count = 0;
    SDL_JoystickID* ids = SDL_GetGamepads(&count);
    int real = 0; // Wii Remotes on the first KPAD channels in the real-only mode
    std::array<os::WiimoteState, os::wiimote::kChannels> real_states{};
#ifdef __linux__
    if (wiimotes || real_only) {
        read_real_remotes();
        int seen = 0;
        for (const RealRemote& r : g_real_remotes) {
            if (!r.state.connected) continue;
            if (real_only && real < os::wiimote::kChannels) real_states[real++] = r.state;
            ++seen;
        }
        // A remote read directly is not a pad as well: its SDL device takes no slot and presses nothing.
        int kept = 0;
        for (int i = 0; seen > 0 && ids != nullptr && i < count; ++i) {
            const char* name = SDL_GetGamepadNameForID(ids[i]);
            if (name && std::strstr(name, "Wii Remote") && !std::strstr(name, "Pro Controller") &&
                !std::strstr(name, "Classic") && !std::strstr(name, "Balance")) continue;
            ids[kept++] = ids[i];
        }
        if (seen > 0 && ids != nullptr) count = kept;
    }
#endif
    if (real_only) {
        static const bool scripted = std::getenv("TTT2_INPUT_SCRIPT") != nullptr && std::getenv("TTT2_SCRIPT_REMOTE_ONLY") != nullptr;
        if (real == 0 && scripted) { // unattended runs: remote 0 exists for the script (os/input.cpp)
            static const char* nunchuk = std::getenv("TTT2_SCRIPT_NUNCHUK");
            real_states[0].connected = true;
            real_states[0].nunchuk = nunchuk == nullptr || *nunchuk != '0';
            real = 1;
        }
        for (int c = 0; c < os::wiimote::kChannels; ++c) os::set_wiimote_state(c, c < real ? real_states[c] : os::WiimoteState{});
    }
    if (pros || wiimotes) assign_pad_slots(ids, count);""")
# Pro Controllers sit after the remotes
sub("src/host/window.cpp",
    r"""        os::set_gamepad_state(state);
        for (int c = 0; pros && c < os::pro::kChannels; ++c) os::set_pro_pad_state(c, channels[c]);
        return;""",
    r"""        os::set_gamepad_state(state);
        for (int c = real; pros && c < os::pro::kChannels; ++c) os::set_pro_pad_state(c, channels[c - real]);
        return;""")
sub("src/host/window.cpp",
    r"""    os::set_gamepad_state(state);
    for (int c = 0; pros && c < os::pro::kChannels; ++c) os::set_pro_pad_state(c, channels[c]);
}""",
    r"""    os::set_gamepad_state(state);
    for (int c = real; pros && c < os::pro::kChannels; ++c) os::set_pro_pad_state(c, channels[c - real]);
}""")

# ---- without a window (TTT2_GPU=null) nothing calls the host's update_input: the script's remote 0 is made here
sub("src/os/input.cpp",
    "GamepadState g_gamepad{};\n",
    "GamepadState g_gamepad{};\n"
    "bool g_host_input_seen = false; // port/patch_wiimote_real.py: the window's input loop runs\n")
sub("src/os/input.cpp",
    r"""int32_t VPADRead(int32_t channel, VPADStatus* status, uint32_t count, be<int32_t>* error) {
    deliver_connects();
""",
    r"""int32_t VPADRead(int32_t channel, VPADStatus* status, uint32_t count, be<int32_t>* error) {
    { // port/patch_wiimote_real.py: headless scripted runs
        static const bool script_remote = (wiimote_mode() || wiimote_real_mode()) && std::getenv("TTT2_INPUT_SCRIPT") != nullptr &&
                                          std::getenv("TTT2_SCRIPT_REMOTE_ONLY") != nullptr;
        if (script_remote && !g_host_input_seen) {
            static const char* nunchuk = std::getenv("TTT2_SCRIPT_NUNCHUK");
            WiimoteState w;
            w.connected = true;
            w.nunchuk = nunchuk == nullptr || *nunchuk != '0';
            w.buttons = script_wiimote_buttons(g_script_vpad); // a press reconnects a remote the title dropped
            set_wiimote_state(0, w);
        }
    }
    deliver_connects();
""")
sub("src/os/input.cpp",
    r"""    std::lock_guard lock(g_input_mutex);
    g_gamepad = state;
""",
    r"""    std::lock_guard lock(g_input_mutex);
    g_host_input_seen = true; // port/patch_wiimote_real.py
    g_gamepad = state;
""")

# ---- KPADReadEx on an empty channel: error -2 (no controller). It was -1, which is "no new samples": sead-based
# titles (Mario Kart 8, 3D World) then took all four channels for connected remotes that never send anything.
sub("src/os/input.cpp",
    r"""    if (channel < 0 || channel >= pro::kChannels || !g_pro[channel].connected || status == nullptr || count == 0) {
        if (error) *error = kWpadNoController;
        return 0;
    }
    ProChannel& c = g_pro[channel];
    std::memset(status, 0, sizeof(KPADStatus));""",
    r"""    if (channel < 0 || channel >= pro::kChannels || !g_pro[channel].connected || status == nullptr || count == 0) {
        if (error) *error = -2; // KPAD_ERROR_INVALID_CONTROLLER (port/patch_wiimote_real.py)
        return 0;
    }
    ProChannel& c = g_pro[channel];
    std::memset(status, 0, sizeof(KPADStatus));""")
sub("src/os/input.cpp",
    r"""    ProChannel& c = g_pro[channel];
    if (!c.connected) return;
    c.connected = false;
    c.dropped = true;""",
    r"""    ProChannel& c = g_pro[channel];
    static const bool trace = std::getenv("TTT2_TRACE_WIIMOTE") != nullptr; // port/patch_wiimote_real.py
    if (trace) std::fprintf(stderr, "wiimote: WPADDisconnect(%d), connected %d\n", channel, c.connected ? 1 : 0);
    if (!c.connected) return;
    c.connected = false;
    c.dropped = true;""")

