#!/usr/bin/env python3
r"""patch_target_pages.py RUNTIME_SRC_DIR (.../runtime/src) : CPU-write notices find the render targets over their memory
through a 64 KB page index (like the textures' texture_pages_) instead of walking the address-sorted target list from
"address minus the largest target size". Apply after patch_dcflush_nosync.py and patch_target_eviction.py.
Found 28 Nov (wiiu-zusammenfuehren) when the night's patches were merged: Mario Kart 8 on the console fell from 59.5 to
46-48 frames/s in races (slowest 10 s 34-36 instead of 56); the same build without patch_dcflush_nosync.py ran 59.5.
Measured: the console's "gpu" thread (command processor) went from 56 % at 59 frames/s (9.5 ms a frame) to 74 % at
45 frames/s (16.3 ms a frame). Mario Kart 8 calls DCFlushRangeNoSync ~18,600 times a second (now a CPU-write notice,
needed for Super Mario 3D World's light cubes); for each notice Renderer::cpu_wrote walked targets_sorted_ from
(address - max_target_span_), and the largest target spans 0x2000000 bytes (32 MB): ~1100 map entries per notice,
about 50 million a second on the PC (counted), while not one of them overlapped the written memory.
Now each target is also listed in target_pages_ for every 64 KB page it covers (added where it enters targets_sorted_,
removed where the eviction drops it); cpu_wrote looks only at the targets of the written pages, with the same exact
overlap test as before, so the same targets are marked. TTT2_TARGET_PAGES=0 = the old walk."""
import sys

d = sys.argv[1] + "/gpu/vulkan/"
MARK = "patch_target_pages"


def edit(name, pairs):
    path = d + name
    s = open(path, encoding="utf-8").read()
    if MARK in s:
        print("already applied:", path)
        return
    for old, new, count in pairs:
        if s.count(old) != count:
            sys.exit(f"{MARK}: {name}: expected {count}x {old[:70]!r}, found {s.count(old)}")
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched:", path)


edit("renderer.h", [(
    "    std::map<uint32_t, std::vector<Target*>> targets_sorted_; // port/patch_target_index.py: by address\n",
    "    std::map<uint32_t, std::vector<Target*>> targets_sorted_; // port/patch_target_index.py: by address\n"
    "    std::unordered_map<uint32_t, std::vector<Target*>> target_pages_; // port/patch_target_pages.py: 64 KB page -> targets\n"
    "    void index_target_pages(Target* t, bool add) { // port/patch_target_pages.py\n"
    "        if (t->end <= t->address) return;\n"
    "        for (uint64_t page = t->address >> 16; page <= (uint64_t{t->end} - 1) >> 16; ++page) {\n"
    "            if (add) {\n"
    "                target_pages_[static_cast<uint32_t>(page)].push_back(t);\n"
    "            } else if (const auto it = target_pages_.find(static_cast<uint32_t>(page)); it != target_pages_.end()) {\n"
    "                std::erase(it->second, t);\n"
    "                if (it->second.empty()) target_pages_.erase(it);\n"
    "            }\n"
    "        }\n"
    "    }\n",
    1)])

edit("targets.cpp", [
    ("    targets_sorted_[t->address].push_back(t.get());\n",
     "    targets_sorted_[t->address].push_back(t.get());\n"
     "    index_target_pages(t.get(), true); // port/patch_target_pages.py\n",
     2),
    ("        drop(targets_sorted_);\n",
     "        drop(targets_sorted_);\n"
     "        index_target_pages(t, false); // port/patch_target_pages.py\n",
     1),
])

edit("textures.cpp", [(
    "        for (auto it = targets_sorted_.lower_bound(from); it != targets_sorted_.end() && it->first < end; ++it) {\n"
    "            for (Target* t : it->second) {\n"
    "                if (t->address < end && t->end > address) t->overwritten = now ? now : (now = stamp());\n"
    "            }\n"
    "        }\n",
    "        // port/patch_target_pages.py: only the targets listed for the written 64 KB pages (same overlap test).\n"
    "        static const bool by_pages = [] {\n"
    "            const char* v = std::getenv(\"TTT2_TARGET_PAGES\");\n"
    "            return !(v && v[0] == '0');\n"
    "        }();\n"
    "        if (by_pages) {\n"
    "            for_pages(address, end, [&](uint32_t page) {\n"
    "                const auto it = target_pages_.find(page);\n"
    "                if (it == target_pages_.end()) return;\n"
    "                for (Target* t : it->second) {\n"
    "                    if (t->address < end && t->end > address) t->overwritten = now ? now : (now = stamp());\n"
    "                }\n"
    "            });\n"
    "        } else {\n"
    "        for (auto it = targets_sorted_.lower_bound(from); it != targets_sorted_.end() && it->first < end; ++it) {\n"
    "            for (Target* t : it->second) {\n"
    "                if (t->address < end && t->end > address) t->overwritten = now ? now : (now = stamp());\n"
    "            }\n"
    "        }\n"
    "        }\n",
    1)])
