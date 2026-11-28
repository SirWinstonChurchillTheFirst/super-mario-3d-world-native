#!/usr/bin/env python3
"""patch_dump_tex_at.py RUNTIME_SRC_DIR (.../runtime/src) : TOOL - save one texture's layers once, without a frame trace.

TTT2_DUMP_TEX_AT=<seconds>,<address hex>[,<count>]: the first <count> (default 1) times a texture whose base address is
<address> is bound after <seconds> (renderer clock), every layer of level 0 is saved as dumptex_<n>_L<layer>.png into
TTT2_CAPTURE, and one line "dumptex: ..." says its size, layers, format and source target. Meant for the console, where
full frame traces (TTT2_TRACE_AT + TTT2_TRACE_TEX) are too heavy. Costs nothing when the switch is not set."""
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

edit(d + "textures.cpp", "patch_dump_tex_at", [
    ("    entry->used_frame = frame_number_;" + NL + "    load_texture(*entry);" + NL + "    return entry.get();" + NL,
     "    entry->used_frame = frame_number_;" + NL + "    load_texture(*entry);" + NL +
     "    { // port/patch_dump_tex_at.py: TTT2_DUMP_TEX_AT=<seconds>,<address hex>[,<count>]" + NL +
     "        static const char* spec = std::getenv(\"TTT2_DUMP_TEX_AT\");" + NL +
     "        static const char* dir = std::getenv(\"TTT2_CAPTURE\");" + NL +
     "        if (spec && dir) {" + NL +
     "            static const double at = std::atof(spec);" + NL +
     "            static const uint32_t address = [] {" + NL +
     "                const char* c = std::strchr(spec, ',');" + NL +
     "                return c ? static_cast<uint32_t>(std::strtoul(c + 1, nullptr, 16)) : 0u;" + NL +
     "            }();" + NL +
     "            static int left = [] {" + NL +
     "                const char* c = std::strchr(spec, ',');" + NL +
     "                c = c ? std::strchr(c + 1, ',') : nullptr;" + NL +
     "                return c ? std::atoi(c + 1) : 1;" + NL +
     "            }();" + NL +
     "            static const auto start = std::chrono::steady_clock::now();" + NL +
     "            if (left > 0 && (words[2] << 8) == address &&" + NL +
     "                std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() >= at) {" + NL +
     "                static int n = 0;" + NL +
     "                --left;" + NL +
     "                end_rendering();" + NL +
     "                const Image& img = entry->image;" + NL +
     "                std::fprintf(stderr, \"dumptex: %d 0x%08X %ux%u layers %u levels %u vk format %d source %p (frame %llu)\\n\", n," + NL +
     "                             address, img.width, img.height, img.layers, img.levels, static_cast<int>(img.format)," + NL +
     "                             static_cast<const void*>(entry->source), static_cast<unsigned long long>(frame_number_));" + NL +
     "                for (uint32_t layer = 0; layer < img.layers; ++layer) {" + NL +
     "                    char nm[64];" + NL +
     "                    std::snprintf(nm, sizeof(nm), \"/dumptex_%d_L%02u.png\", n, layer);" + NL +
     "                    save_image_layer(img, layer, 0, std::string(dir) + nm);" + NL +
     "                }" + NL +
     "                ++n;" + NL +
     "            }" + NL +
     "        }" + NL +
     "    }" + NL +
     "    return entry.get();" + NL),
    ("#include <algorithm>" + NL, "#include <algorithm>" + NL + "#include <chrono> // port/patch_dump_tex_at.py" + NL),
])
