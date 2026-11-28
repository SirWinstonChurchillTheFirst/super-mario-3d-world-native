#!/usr/bin/env python3
r"""patch_shadow_compare.py RUNTIME_SRC_DIR : depth-compare sampling (SAMPLE_C*) is done by the translated shader.

The translator declared every texture a shader samples with SAMPLE_C / SAMPLE_C_LZ / SAMPLE_C_L as a GLSL
sampler*Shadow and the renderer bound it with a compare sampler. The images behind those slots are colour-format
images, though (a depth buffer read as a texture is copied into R16_UNORM / R32_SFLOAT, see copy_depth_to_texture):
Vulkan forbids a depth compare on such a view (VUID-vkCmdDraw*-None-06479, ten times in every validation run of
Mario Kart 8, 3D World and Tennis) and leaves the result undefined - in practice the compare happens but the 2x2
filtering of the compare results (what the Wii U's GPU does for a linear filter) is not guaranteed.

Now the shader does it itself, for every image format:
- the slot is a plain sampler, the VkSampler has no compare;
- per draw, one byte per texture slot goes into DrawConstants (vs_compare / ps_compare): bits 0-2 the sampler's
  DEPTH_COMPARE_FUNCTION, bit 3 magnification filter linear, bit 4 minification filter linear, bit 5 the texture's
  format is fixed-point (the reference is clamped to 0..1 as for a normalized depth format);
- 2D and 2D array textures: point filter = one tap + compare; linear filter = the four texels around the sample
  point are read at their centres (so the sampler's wrap mode still applies), each compared, the results weighted
  bilinearly. Cube and 1D textures: one tap + compare.
The extra DrawConstants members are only declared by shaders that sample with a compare: other shaders' GLSL (and
their SPIR-V cache entries) do not change.

TTT2_LOG_COMPARE=1 prints each distinct compare binding once; TTT2_COMPARE_POINT=1 forces one tap."""
import sys

root = sys.argv[1] + "/"


def edit(name, pairs):
    path = root + name
    s = open(path, encoding="utf-8").read()
    if "patch_shadow_compare" in s:
        print("already applied:", name)
        return
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


# ---- shader_abi.h: the per-slot compare bytes, at the end
edit("latte/shader_abi.h", [
    (r"""    Buffer gs_cb[16];   // port/patch_gs.py: geometry shader uniform blocks (SQ_ALU_CONST_CACHE_GS_n)
};""",
     r"""    Buffer gs_cb[16];   // port/patch_gs.py: geometry shader uniform blocks (SQ_ALU_CONST_CACHE_GS_n)
    // port/patch_shadow_compare.py: one byte per texture slot sampled with a depth compare (slot s: word s / 4,
    // byte s % 4): bits 0-2 compare function, bit 3 mag filter linear, bit 4 min filter linear, bit 5 clamp the
    // reference to 0..1 (fixed-point texture).
    uint32_t vs_compare[8];
    uint32_t ps_compare[8];
};"""),
])

# ---- translate.cpp
edit("latte/translate.cpp", [
    # the uniform block: the tail only where it is used
    (r"""    if (gs_) h += "    uvec4 gs_cb[16];\n"; // port/patch_gs.py
""",
     r"""    if (gs_ || shadow_mask_ != 0) h += "    uvec4 gs_cb[16];\n"; // port/patch_gs.py
    if (shadow_mask_ != 0) h += "    uvec4 vs_cmp[2];\n    uvec4 ps_cmp[2];\n"; // port/patch_shadow_compare.py
"""),
    # plain samplers
    (r"""                    (vs_ ? abi::kVsTextureBinding : abi::kPsTextureBinding) + slot, prefix, type,
                    (shadow_mask_ >> slot) & 1 ? "Shadow" : "", slot);""",
     r"""                    (vs_ ? abi::kVsTextureBinding : abi::kPsTextureBinding) + slot, prefix, type,
                    "", slot); // port/patch_shadow_compare.py: never a *Shadow sampler, the shader compares"""),
    # helpers
    (r"""    h += "uint bswap(uint x) { return (x << 24) | ((x << 8) & 0xFF0000u) | ((x >> 8) & 0xFF00u) | (x >> 24); }\n";
""",
     r"""    if (shadow_mask_ != 0) {
        // port/patch_shadow_compare.py: the depth compare of SAMPLE_C*, with the 2x2 filtering of the results.
        h += format("uint cmp_info(uint slot) { return (dc.%s_cmp[slot >> 4][(slot >> 2) & 3u] >> ((slot & 3u) * 8u)) & 0xFFu; }\n",
                    vs_ ? "vs" : "ps");
        h += "float cmp_test(float d, float ref, uint info) {\n"
             "    if ((info & 0x20u) != 0u) ref = clamp(ref, 0.0, 1.0);\n"
             "    switch (info & 7u) {\n"
             "    case 1u: return float(ref < d);\n"
             "    case 2u: return float(ref == d);\n"
             "    case 3u: return float(ref <= d);\n"
             "    case 4u: return float(ref > d);\n"
             "    case 5u: return float(ref != d);\n"
             "    case 6u: return float(ref >= d);\n"
             "    case 7u: return 1.0;\n"
             "    default: break;\n"
             "    }\n"
             "    return 0.0;\n"
             "}\n";
        // lod < 0: the implicit level of a pixel shader's SAMPLE_C
        const bool implicit = !vs_ && !gs_ && !es_;
        for (int arr = 0; arr < 2; ++arr) {
            const char* uv = arr ? "uv.xy" : "uv";
            h += format("float cmp_sample(%s s, %s uv, float ref, float lod, vec2 off, uint info) {\n",
                        arr ? "sampler2DArray" : "sampler2D", arr ? "vec3" : "vec2");
            h += format("    %s += off / vec2(textureSize(s, 0).xy);\n", uv);
            if (implicit) h += format("    if (lod < 0.0) lod = textureQueryLod(s, %s).y;\n", uv);
            h += "    if ((info & (lod > 0.0 ? 0x10u : 0x08u)) == 0u) return cmp_test(textureLod(s, uv, lod).x, ref, info);\n";
            h += "    int level = clamp(int(lod + 0.5), 0, textureQueryLevels(s) - 1);\n";
            h += "    vec2 size = vec2(textureSize(s, level).xy);\n";
            h += format("    vec2 p = %s * size - 0.5;\n", uv);
            h += "    vec2 b = floor(p);\n    vec2 f = p - b;\n";
            h += "    vec4 at = vec4(b + 0.5, b + 1.5) / size.xyxy;\n";
            const char* tap = arr ? "cmp_test(textureLod(s, vec3(at.%s, uv.z), float(level)).x, ref, info)"
                                  : "cmp_test(textureLod(s, at.%s, float(level)).x, ref, info)";
            h += "    return mix(mix(" + format(tap, "xy") + ", " + format(tap, "zy") + ", f.x),\n               mix(" +
                 format(tap, "xw") + ", " + format(tap, "zw") + ", f.x), f.y);\n}\n";
        }
    }
    h += "uint bswap(uint x) { return (x << 24) | ((x << 8) & 0xFF0000u) | ((x >> 8) & 0xFF00u) | (x >> 24); }\n";
"""),
    # the sampling call
    (r"""            const std::string ref = t.inst == kSampleCL ? c[2] : c[3];
            std::string sc;
            if (cube) sc = "vec4(" + coord + ", " + ref + ")";
            else if (coords == 1) sc = "vec3(" + coord + ", 0.0, " + ref + ")";
            else if (coords == 2) sc = "vec3(" + coord + ", " + ref + ")";
            else sc = "vec4(" + coord + ", " + ref + ")";
            if (t.inst == kSampleC && !vertex_lod) {
                call = format("vec4(texture%s(%s, %s%s))", offset.empty() ? "" : "Offset", sampler.c_str(), sc.c_str(), offset.c_str());
            } else if (cube || coords == 3) {
                // Array and cube shadow samplers have no explicit-LOD variant: use gradients of 0.
                const char* g = cube ? "vec3(0.0)" : "vec2(0.0)";
                call = format("vec4(textureGrad%s(%s, %s, %s, %s%s))", offset.empty() ? "" : "Offset", sampler.c_str(), sc.c_str(), g, g, offset.c_str());
            } else {
                const std::string lod = t.inst == kSampleCL ? c[3] : std::string("0.0");
                call = format("vec4(textureLod%s(%s, %s, %s%s))", offset.empty() ? "" : "Offset", sampler.c_str(), sc.c_str(), lod.c_str(), offset.c_str());
            }
            break;""",
     r"""            // port/patch_shadow_compare.py: the texture is a plain one (its image has a colour format, a compare
            // sampler on it is undefined); the shader compares and filters the results.
            const std::string ref = t.inst == kSampleCL ? c[2] : c[3];
            const std::string info = format("cmp_info(%uu)", slot);
            const bool implicit = t.inst == kSampleC && !vertex_lod && !gs_ && !es_;
            // As before: arrays and cubes take level 0 for the explicit forms.
            const std::string lod = t.inst == kSampleCL && !cube && coords != 3 ? "max(" + c[3] + ", 0.0)" : std::string("0.0");
            if (!cube && spatial == 2) {
                const std::string off = offset.empty() ? std::string("vec2(0.0)") : "vec2(" + offset.substr(2) + ")";
                call = format("vec4(cmp_sample(%s, %s, %s, %s, %s, %s))", sampler.c_str(), coord.c_str(), ref.c_str(),
                              implicit ? "-1.0" : lod.c_str(), off.c_str(), info.c_str());
            } else {
                std::string tap;
                if (implicit) tap = format("texture%s(%s, %s%s)", offset.empty() ? "" : "Offset", sampler.c_str(), coord.c_str(), offset.c_str());
                else tap = format("textureLod%s(%s, %s, %s%s)", offset.empty() ? "" : "Offset", sampler.c_str(), coord.c_str(), lod.c_str(), offset.c_str());
                call = format("vec4(cmp_test(%s.x, %s, %s))", tap.c_str(), ref.c_str(), info.c_str());
            }
            break;"""),
])

# ---- draw.cpp: no compare samplers; the compare bytes per draw
edit("gpu/vulkan/draw.cpp", [
    (r"""    struct Bound {
        VkImageView view;
        VkSampler sampler;
        bool scaled;
    };""",
     r"""    struct Bound {
        VkImageView view;
        VkSampler sampler;
        bool scaled;
        uint8_t compare = 0; // port/patch_shadow_compare.py: DrawConstants::*_compare byte
    };
    // port/patch_shadow_compare.py: what the shader needs for a SAMPLE_C* of this slot.
    const auto compare_byte = [&](const ShaderModule* s, uint32_t slot, const uint32_t* sampler_words,
                                  const uint32_t* words) -> uint8_t {
        if (!((s->info.shadow_mask >> slot) & 1)) return 0;
        static const bool point = std::getenv("TTT2_COMPARE_POINT") != nullptr;
        const uint32_t w0 = sampler_words[0];
        uint32_t b = (w0 >> 26) & 7;
        if (((w0 >> 9) & 1) && !point) b |= 0x08;
        if (((w0 >> 12) & 1) && !point) b |= 0x10;
        const uint32_t hw = words ? (words[1] >> 26) & 0x3F : 0;
        const bool is_float = hw == fmt::k16Float || hw == fmt::k32Float || hw == fmt::k8_24Float ||
                              hw == fmt::kX24_8_32Float || hw == fmt::k16_16Float || hw == fmt::k32_32Float ||
                              hw == fmt::k16_16_16_16Float || hw == fmt::k32_32_32_32Float;
        if (!is_float) b |= 0x20;
        if (static const bool log = std::getenv("TTT2_LOG_COMPARE") != nullptr; log) {
            static std::vector<uint64_t> seen;
            const uint64_t key = (uint64_t{words ? words[2] : 0u} << 32) | (uint64_t{hw} << 16) | (uint64_t{slot} << 8) | b;
            if (std::find(seen.begin(), seen.end(), key) == seen.end() && seen.size() < 256) {
                seen.push_back(key);
                std::fprintf(stderr,
                             "compare: %s slot %u texture word2 %08X hw format 0x%02X function %u mag %u min %u mip %u%s (frame %llu)\n",
                             s->stage_vertex ? "vs" : "ps", slot, words ? words[2] : 0u, hw, (w0 >> 26) & 7, (w0 >> 9) & 7,
                             (w0 >> 12) & 7, (w0 >> 17) & 3, is_float ? "" : " clamp",
                             static_cast<unsigned long long>(frame_number_));
            }
        }
        return static_cast<uint8_t>(b);
    };"""),
    (r"""                out[slot] = {null_texture().view, sampler(sampler_words, border, (s->info.shadow_mask >> slot) & 1), false};
                continue;""",
     r"""                out[slot] = {null_texture().view, sampler(sampler_words, border, false), false,
                             compare_byte(s, slot, sampler_words, nullptr)};
                continue;"""),
    (r"""            out[slot] = {t->view, sampler(sampler_words, border, (s->info.shadow_mask >> slot) & 1), t->scale > 1};""",
     r"""            out[slot] = {t->view, sampler(sampler_words, border, false), t->scale > 1,
                         compare_byte(s, slot, sampler_words, words)};"""),
    (r"""        if (ps_textures[slot].scaled) dc.ps_scaled_textures |= 1u << slot;
""",
     r"""        if (ps_textures[slot].scaled) dc.ps_scaled_textures |= 1u << slot;
        dc.vs_compare[slot >> 2] |= uint32_t{vs_textures[slot].compare} << ((slot & 3) * 8); // port/patch_shadow_compare.py
        dc.ps_compare[slot >> 2] |= uint32_t{ps_textures[slot].compare} << ((slot & 3) * 8);
"""),
])
