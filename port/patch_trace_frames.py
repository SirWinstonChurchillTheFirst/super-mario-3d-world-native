#!/usr/bin/env python3
"""patch_trace_frames.py RUNTIME_SRC_DIR : frame-trace helpers for flicker hunts.
TTT2_TRACE_FRAMES=n traces n frames in a row (default 1) from the TTT2_TRACE_FRAME/AT frame on;
TTT2_TRACE_SAVE=F4958800,F4994800 saves only the targets at those addresses at the end of each traced frame
(default: every target, as before);
TTT2_SEQ_TARGETS=F52A0000,F5624000 saves, with every TTT2_CAPTURE_SEQUENCE image, the targets at those addresses that were
written since the previous sequence image (sq_<index>_<frame>_<c|d>_<address>_<format>_<size>.png) - consecutive frames
without the slow full trace; the log line of each save gives mean and peak."""
import sys

d = sys.argv[1] + "/gpu/vulkan/"
p = d + "renderer.h"
s = open(p, encoding="utf-8").read()
if "patch_trace_frames" in s:
    print("already applied"); sys.exit(0)
BS = chr(92)
old = "    bool tracing() const { return frame_number_ == trace_frame_ || trace_this_draw_; }\n"
new = ("    // port/patch_trace_frames.py: TTT2_TRACE_FRAMES frames in a row\n"
       "    bool tracing() const { return (frame_number_ >= trace_frame_ && frame_number_ - trace_frame_ < trace_frames_) || trace_this_draw_; }\n"
       "    uint64_t trace_frames_ = 1;\n")
assert old in s, "renderer.h pattern"
open(p, "w", encoding="utf-8", newline="\n").write(s.replace(old, new))

p = d + "renderer.cpp"
s = open(p, encoding="utf-8").read()
old = """    if (const char* f = std::getenv("TTT2_TRACE_FRAME")) trace_frame_ = std::strtoull(f, nullptr, 10);
"""
new = old + """    if (const char* f = std::getenv("TTT2_TRACE_FRAMES")) trace_frames_ = std::max<uint64_t>(1, std::strtoull(f, nullptr, 10)); // port/patch_trace_frames.py
"""
assert old in s, "renderer.cpp pattern 1"
s = s.replace(old, new)
old = """        for (const auto& t : targets_) {
            char name[96];
            std::snprintf(name, sizeof(name), "/frame%llu_%s_%08X_%03X_%ux%u.png","""
new = """        static const char* only = std::getenv("TTT2_TRACE_SAVE"); // port/patch_trace_frames.py
        for (const auto& t : targets_) {
            char name[96];
            if (only != nullptr) {
                std::snprintf(name, sizeof(name), "%08X", t->address);
                if (std::strstr(only, name) == nullptr) continue;
            }
            std::snprintf(name, sizeof(name), "/frame%llu_%s_%08X_%03X_%ux%u.png","""
assert old in s, "renderer.cpp pattern 2"
s = s.replace(old, new)
old = """    save_image(scan_[0], std::string(std::getenv("TTT2_CAPTURE")) + name);
}
"""
new = """    save_image(scan_[0], std::string(std::getenv("TTT2_CAPTURE")) + name);
    { // port/patch_trace_frames.py: TTT2_SEQ_TARGETS
        static uint64_t last = 0;
        static const char* only = std::getenv("TTT2_SEQ_TARGETS");
        for (const auto& t : targets_) {
            if (t->written <= last || only == nullptr) continue;
            char a[16];
            std::snprintf(a, sizeof(a), "%08X", t->address);
            if (std::strstr(only, a) == nullptr) continue;
            char nm[128];
            std::snprintf(nm, sizeof(nm), "/sq_%04u_%03u_%s_%08X_%03X_%ux%u.png", sequence_index_, sequence_frame_,
                          t->depth ? "d" : "c", t->address, t->format, t->pitch, t->height);
            save_image(t->image, std::string(std::getenv("TTT2_CAPTURE")) + nm);
        }
        last = events_;
    }
}
"""
assert old in s, "renderer.cpp pattern 3"
s = s.replace(old, new)
if "#include <cstring>" not in s:
    s = s.replace("#include", "#include <cstring>\n#include", 1)
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched", d)
