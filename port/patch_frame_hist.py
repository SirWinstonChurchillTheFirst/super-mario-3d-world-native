#!/usr/bin/env python3
"""TTT2_TRACE_PACING: the 10-second "ttt2: present:" line also counts the long frames.

usage: patch_frame_hist.py RUNTIME_DIR   (e.g. ~/wiiu/smash4/runtime)

Before: the line gave mean, 5/50/95 % and the longest interval of the window - one number for "was there a
hitch", not how many. After: the line ends with "; over 25/50/100 ms: a/b/c" = how many shown pictures of the
window came more than 25, 50 and 100 ms after the one before (each count includes the larger ones).
tools/3dw_fps_sum.sh adds them up. Measuring only; nothing changes without TTT2_TRACE_PACING.
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


sub("src/gpu/vulkan/present.cpp",
    """                 "%u more than 2 ms late, %.2f ms late on average; lead %.1f ms\\n",
                 sorted.size() / (presented - window), mean, pct(0.05), pct(0.5), pct(0.95), sorted.back(), late,
                 late_total / (sorted.size() + 1), present_lead_.load() * 1000.0);
""",
    """                 "%u more than 2 ms late, %.2f ms late on average; lead %.1f ms; over 25/50/100 ms: %u/%u/%u\\n",
                 sorted.size() / (presented - window), mean, pct(0.05), pct(0.5), pct(0.95), sorted.back(), late,
                 late_total / (sorted.size() + 1), present_lead_.load() * 1000.0,
                 // port/patch_frame_hist.py: how many intervals of the window were long
                 static_cast<unsigned>(sorted.end() - std::upper_bound(sorted.begin(), sorted.end(), 25.0)),
                 static_cast<unsigned>(sorted.end() - std::upper_bound(sorted.begin(), sorted.end(), 50.0)),
                 static_cast<unsigned>(sorted.end() - std::upper_bound(sorted.begin(), sorted.end(), 100.0)));
""")
