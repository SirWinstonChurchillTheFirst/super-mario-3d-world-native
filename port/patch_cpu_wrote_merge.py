#!/usr/bin/env python3
r"""patch_cpu_wrote_merge.py RUNTIME_SRC_DIR (.../runtime/src) : CPU-write notices reach the renderer as their union
(sorted, overlapping and touching ranges joined) instead of one by one. Apply after patch_dcflush_nosync.py.
Found 28 Nov (wiiu-zusammenfuehren) when the night's patches were merged: Mario Kart 8 on the console fell from 59.6 to
48 frames/s in races (slowest 10 s 28 instead of 55) with all patches together, while every patch alone had been fine.
Cause: patch_dcflush_nosync.py (right for Super Mario 3D World's light cubes) turns DCFlushRangeNoSync into a CPU-write
notice. Mario Kart 8 calls it ~18,600 times a second (PC count, 25 MB/s: ~310 calls a frame, most of them 64-256 bytes,
the same 0x2580-byte block up to 16 times in a row). Each notice is handled on the GPU thread before the next command
buffer: textures over the range marked for a re-check, every render target from (address - largest target size) up to
the end looked at, shader programs over the range dropped. 310 of these a frame took the GPU thread's time.
Now the command processor sorts the notices of one batch and joins overlapping / touching ranges (the same bytes, no gap
is added, so exactly the same textures, targets and programs are marked): 620 calls of two MK8 frames -> 106 ranges.
TTT2_CPU_WROTE_MERGE=0 = one by one as before."""
import sys

path = sys.argv[1] + "/gpu/command_processor.cpp"
MARK = "patch_cpu_wrote_merge"
s = open(path, encoding="utf-8").read()
if MARK in s:
    print("already applied:", path)
    sys.exit(0)
old = "            for (const auto& [address, size] : written) g_backend->cpu_wrote(address, size);\n"
new = (
    "            // port/patch_cpu_wrote_merge.py: the union of the batch's CPU writes (same bytes, far fewer calls)\n"
    "            static const bool merge_written = [] {\n"
    "                const char* v = std::getenv(\"TTT2_CPU_WROTE_MERGE\");\n"
    "                return !(v && v[0] == '0');\n"
    "            }();\n"
    "            if (merge_written && written.size() > 1) {\n"
    "                std::sort(written.begin(), written.end());\n"
    "                uint64_t a = written[0].first, e = a + written[0].second;\n"
    "                for (size_t i = 1; i <= written.size(); ++i) {\n"
    "                    if (i < written.size() && written[i].first <= e) {\n"
    "                        e = std::max<uint64_t>(e, uint64_t{written[i].first} + written[i].second);\n"
    "                        continue;\n"
    "                    }\n"
    "                    for (uint64_t p = a; p < e;) { // sizes stay 32-bit\n"
    "                        const uint32_t n = static_cast<uint32_t>(std::min<uint64_t>(e - p, 0x80000000u));\n"
    "                        g_backend->cpu_wrote(static_cast<uint32_t>(p), n);\n"
    "                        p += n;\n"
    "                    }\n"
    "                    if (i < written.size()) { a = written[i].first; e = a + written[i].second; }\n"
    "                }\n"
    "            } else {\n"
    "                for (const auto& [address, size] : written) g_backend->cpu_wrote(address, size);\n"
    "            }\n"
)
if s.count(old) != 1:
    sys.exit(f"{MARK}: {path}: expected the cpu_wrote loop once, found {s.count(old)}")
s = s.replace(old, new)
# <algorithm> was only included under #ifdef __linux__ (the Windows build failed without this line).
first = s.index("#include <")
s = s[:first] + "#include <algorithm> // port/patch_cpu_wrote_merge.py\n" + s[first:]
open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched:", path)
