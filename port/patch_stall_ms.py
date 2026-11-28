#!/usr/bin/env python3
"""patch_stall_ms.py RUNTIME_SRC_DIR (.../runtime/src) : TOOL - TTT2_STALL_MS sets the threshold of TTT2_TRACE_STALLS.

TTT2_TRACE_STALLS printed present gaps over 100 ms ("stall:") and draw-thread frames over 60 ms ("stall-cp:", see
patch_stall_trace.py). The single 28-50 ms frames seen in Mario Kart 8 races on the console need a lower threshold:
TTT2_STALL_MS=<ms> sets both (default: 100 and 60 as before)."""
import sys

NL = "\n"


def edit(path, marker, pairs):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        print("already applied:", path)
        return
    for old, new in pairs:
        assert s.count(old) == 1, "pattern not found once in %s: %r" % (path, old[:80])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


d = sys.argv[1] + "/gpu/vulkan/"

edit(d + "present.cpp", "patch_stall_ms", [
    ("    if (trace_stalls && last != 0 && presented - last > 0.1) {" + NL,
     "    static const double stall_s = [] { // port/patch_stall_ms.py" + NL +
     "        const char* v = std::getenv(\"TTT2_STALL_MS\");" + NL +
     "        return v ? std::atof(v) / 1000.0 : 0.1;" + NL +
     "    }();" + NL +
     "    if (trace_stalls && last != 0 && presented - last > stall_s) {" + NL),
])

edit(d + "renderer.cpp", "patch_stall_ms", [
    ("    if (last != 0 && now - last > 0.06) {" + NL,
     "    static const double stall_s = [] { // port/patch_stall_ms.py" + NL +
     "        const char* v = std::getenv(\"TTT2_STALL_MS\");" + NL +
     "        return v ? std::atof(v) / 1000.0 : 0.06;" + NL +
     "    }();" + NL +
     "    if (last != 0 && now - last > stall_s) {" + NL),
])
