#!/usr/bin/env python3
r"""patch_trace_fmt.py RUNTIME_SRC_DIR : TTT2_TRACE_FMT=<GX2 surface format, hex> (tool, after patch_log_targets.py
and patch_cube_arrays.py).

Every draw whose colour target 0 has that format is traced like a draw of a traced frame (shaders, targets, textures,
samplers, uniform blocks; with TTT2_TRACE_TEX=p<ps hash> its textures are saved too), without tracing a whole frame.
For draws that happen once while a course loads, e.g. Mario Kart 8 compressing its reflection probes on the GPU
(colour target R32G32B32A32_UINT = 0x122 over the BC3 texture's memory): TTT2_TRACE_FMT=122.

TTT2_TRACE_TEX=a<texture address, hex>: the first traced draw that samples the texture at that address saves it
(once), whatever its pixel shader is."""
import sys

path = sys.argv[1] + "/gpu/vulkan/draw.cpp"
s = open(path, encoding="utf-8").read()
if "patch_trace_fmt" in s:
    print("already applied:", path)
    sys.exit(0)
old = ("            if (colors[i] && (colors[i]->tile_mode == 3 || colors[i]->tile_mode == 7)) trace_this_draw_ = true;\n"
       "        }\n")
assert s.count(old) == 1
new = old + ("        // port/patch_trace_fmt.py: TTT2_TRACE_FMT=<hex> traces draws into a colour target 0 of that format\n"
             "        static const char* tf = std::getenv(\"TTT2_TRACE_FMT\");\n"
             "        if (tf && colors[0] && colors[0]->format == std::strtoul(tf, nullptr, 16)) trace_this_draw_ = true;\n")
s = s.replace(old, new)

old = "(tex_draw[0] == 0x70 && std::strtoull(tex_draw + 1, nullptr, 16) == static_cast<unsigned long long>(ph)))) {\n"
assert s.count(old) == 1
s = s.replace(old, "(tex_draw[0] == 0x70 && std::strtoull(tex_draw + 1, nullptr, 16) == static_cast<unsigned long long>(ph)) ||\n"
              "                                                   trace_tex_address(tex_draw, w[2] << 8))) {\n")

old = "void Renderer::draw(const Registers& regs, const Draw& d) {\n"
assert s.count(old) == 1
s = s.replace(old, "// port/patch_trace_fmt.py: TTT2_TRACE_TEX=a<address> matches that texture once\n"
              "static bool trace_tex_address(const char* spec, uint32_t address) {\n"
              "    static bool done = false;\n"
              "    if (done || spec[0] != 'a' || std::strtoul(spec + 1, nullptr, 16) != address) return false;\n"
              "    done = true;\n"
              "    return true;\n"
              "}\n\n" + old)
open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched", path)
