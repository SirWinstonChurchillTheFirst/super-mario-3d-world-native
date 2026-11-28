#!/usr/bin/env python3
"""A scripted Wii U Pro Controller for unattended runs (test tool, off by default).

usage: patch_script_pro.py RUNTIME_DIR   (e.g. ~/wiiu/smash4/runtime)

Before: TTT2_INPUT_SCRIPT could only press the GamePad (or, with CAFE_WIIMOTE, Wii Remote 0), so a scene that
waits for a SECOND controller (Mario Kart 8: "Verbinde den Controller von Spieler 2 ...") could not be driven
without a real second pad. After: TTT2_SCRIPT_PRO="80:connect,84:a,86:l=1.5,95:off" puts a Pro Controller on
KPAD/WPAD channel TTT2_SCRIPT_PRO_CHANNEL (default 0): connected from the first "connect" (or from the start if
the script has none) until "off", buttons a b x y l r zl zr plus minus home up down left right, held 0.3 s or
"=seconds". Times are seconds since the first pad read. The scripted pad replaces a host pad on that channel.
Nothing changes without the variable.
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
    if text.count(old) != count:
        sys.exit(f"{path}: expected {count}x {old[:60]!r}, found {text.count(old)}")
    p.write_text(text.replace(old, new))
    print(f"{path}: ok")


sub("src/os/input.cpp", """void VPADInit() {}

void deliver_connects();
""", """void VPADInit() {}

void deliver_connects();

// port/patch_script_pro.py: TTT2_SCRIPT_PRO = a scripted Pro Controller on one KPAD channel
struct ScriptedProItem {
    double at;
    int kind; // 0 press, 1 connect, 2 off
    uint32_t button;
    double hold;
};
struct ScriptedPro {
    int channel = -1;
    bool has_connect = false;
    std::vector<ScriptedProItem> items;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
};
ScriptedPro& scripted_pro() {
    static ScriptedPro script = [] {
        ScriptedPro s;
        const char* env = std::getenv("TTT2_SCRIPT_PRO");
        if (env == nullptr || *env == 0) return s;
        const char* ch = std::getenv("TTT2_SCRIPT_PRO_CHANNEL");
        s.channel = std::clamp(ch ? std::atoi(ch) : 0, 0, pro::kChannels - 1);
        static const std::pair<const char*, uint32_t> kNames[] = {
            {"a", pro::kA}, {"b", pro::kB}, {"x", pro::kX}, {"y", pro::kY}, {"left", pro::kLeft},
            {"right", pro::kRight}, {"up", pro::kUp}, {"down", pro::kDown}, {"zl", pro::kZL}, {"zr", pro::kZR},
            {"l", pro::kL}, {"r", pro::kR}, {"plus", pro::kPlus}, {"minus", pro::kMinus}, {"home", pro::kHome},
        };
        const std::string text(env);
        size_t pos = 0;
        while (pos < text.size()) {
            const size_t end = text.find(',', pos) == std::string::npos ? text.size() : text.find(',', pos);
            const std::string item = text.substr(pos, end - pos);
            pos = end + 1;
            const size_t colon = item.find(':');
            if (colon == std::string::npos) continue;
            const double at = std::atof(item.substr(0, colon).c_str());
            const std::string name = item.substr(colon + 1);
            const size_t equals = name.find('=');
            const std::string key = name.substr(0, equals);
            const double hold = equals == std::string::npos ? 0.3 : std::atof(name.c_str() + equals + 1);
            if (key == "connect") {
                s.items.push_back({at, 1, 0, 0.0});
                s.has_connect = true;
            } else if (key == "off") {
                s.items.push_back({at, 2, 0, 0.0});
            }
            for (const auto& [n, bit] : kNames) {
                if (key == n) s.items.push_back({at, 0, bit, hold});
            }
        }
        return s;
    }();
    return script;
}
// The scripted pad's state now, if the script owns this channel.
bool scripted_pro_state(int channel, ProPadState& out) {
    ScriptedPro& s = scripted_pro();
    if (s.channel != channel) return false;
    const double t = std::chrono::duration<double>(std::chrono::steady_clock::now() - s.start).count();
    out = ProPadState{};
    out.connected = !s.has_connect;
    double last = -1.0;
    for (const ScriptedProItem& i : s.items) {
        if (t < i.at) continue;
        if (i.kind == 0 && t < i.at + i.hold) out.buttons |= i.button;
        if (i.kind != 0 && i.at >= last) {
            last = i.at;
            out.connected = i.kind == 1;
        }
    }
    if (!out.connected) out.buttons = 0;
    return true;
}
""")

sub("src/os/input.cpp", """    deliver_connects();
    if (channel != 0 || count == 0 || status == nullptr) {
        if (error) *error = kVpadNoController;""", """    if (const int scripted = scripted_pro().channel; scripted >= 0) { // port/patch_script_pro.py: also without a window
        set_pro_pad_state(scripted, ProPadState{});
    }
    deliver_connects();
    if (channel != 0 || count == 0 || status == nullptr) {
        if (error) *error = kVpadNoController;""")

sub("src/os/input.cpp", """void set_pro_pad_state(int channel, const ProPadState& state) {
    if (channel < 0 || channel >= pro::kChannels) return;
    std::lock_guard lock(g_input_mutex);
    ProChannel& c = g_pro[channel];""", """void set_pro_pad_state(int channel, const ProPadState& host_state) {
    if (channel < 0 || channel >= pro::kChannels) return;
    ProPadState state = host_state;
    scripted_pro_state(channel, state); // port/patch_script_pro.py
    std::lock_guard lock(g_input_mutex);
    ProChannel& c = g_pro[channel];""")
