#!/usr/bin/env python3
"""patch_probe_shader.py RUNTIME_SRC_DIR (.../runtime/src) : TOOL - put extra GLSL into one translated shader.

TTT2_PROBE_PS=<pixel shader hash hex>|<items>  (TTT2_PROBE_VS for a vertex shader). Items are split by "##"; an item
"@text@code" puts code after the first line that contains text, any other item goes to the end of main(). Example:
  TTT2_PROBE_PS='464e0e393cecee23|@texture(tex4,@R[104]=r;##o0=vec4(intBitsToFloat(R[104].xyz),1.0);'
shows what that texture fetch returned. Read the result with TTT2_PIXEL_WRITERS (one spot) or screen pictures.
Debugging only; nothing changes without the switch."""
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

ANCHOR = ("    // SPIR-V is cached on disk by the GLSL it came from, and modules are" + NL +
          "    // shared by it (precompile() makes those of earlier runs)." + NL +
          "    const uint64_t glsl_hash = fnv(entry->info.glsl.data(), entry->info.glsl.size());" + NL)

BLOCK = r'''    { // port/patch_probe_shader.py: TTT2_PROBE_PS / TTT2_PROBE_VS=<hash>|<items split by ##, @text@code after a line>
        static const char* probe_ps = std::getenv("TTT2_PROBE_PS");
        static const char* probe_vs = std::getenv("TTT2_PROBE_VS");
        const char* probe = stage == Stage::kVertex ? probe_vs : probe_ps;
        const char* bar = probe ? std::strchr(probe, '|') : nullptr;
        if (bar && std::strtoull(probe, nullptr, 16) == program_hash) {
            std::string& g = entry->info.glsl;
            const std::string spec = bar + 1;
            for (size_t from = 0; from < spec.size();) {
                size_t to = spec.find("##", from);
                if (to == std::string::npos) to = spec.size();
                const std::string item = spec.substr(from, to - from);
                from = to + 2;
                if (item.empty()) continue;
                if (item[0] == '@') {
                    const size_t at = item.find('@', 1);
                    const size_t hit = at == std::string::npos ? std::string::npos : g.find(item.substr(1, at - 1));
                    const size_t eol = hit == std::string::npos ? std::string::npos : g.find('\n', hit);
                    if (eol != std::string::npos) g.insert(eol + 1, item.substr(at + 1) + "\n");
                } else if (const size_t end = g.rfind('}'); end != std::string::npos) {
                    g.insert(end, "    " + item + "\n");
                }
            }
            std::fprintf(stderr, "ttt2: probe: %s %016llx gets: %s\n", kind, static_cast<unsigned long long>(program_hash), bar + 1);
        }
    }
'''

edit(d + "draw.cpp", "patch_probe_shader", [(ANCHOR, BLOCK + ANCHOR)])
