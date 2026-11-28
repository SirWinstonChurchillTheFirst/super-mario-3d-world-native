#!/usr/bin/env python3
"""The shader cache key holds only what the translation reads: no more re-translating the same shader.

usage: patch_shader_key_canon.py RUNTIME_DIR   (e.g. ~/wiiu/smash4/runtime)

Before: Renderer::shaders_ was keyed by program + fetch shader + a hash of the whole ShaderEnvironment: the
dimension/kind of all 18 texture slots (also the ones the program never samples), the raw 32 SPI_VS_OUT_ID
bytes and the raw pixel-input semantics. Titles leave stale values in the slots and semantic registers a
shader does not use, so the same program met "new" environments all the time: every one a translation on the
draw thread whose GLSL text was already known (Super Mario 3D World, PC, title demo: 611 translations in the
first 10 s, 396 of them with text seen before; console session 26 Nov: 8774 cache entries after 6 minutes).

After: the key hashes
  * the texture slots the program (or its fetch shader) has a texture instruction for (Program::sampled_slots,
    filled by decode()) - the translator reads env.textures[] for those only;
  * the LINK between the stages the way the translator uses it: for a vertex shader, per parameter export the
    set of pixel-shader inputs with the same semantic (param_locations_) plus flat/linear/centroid of the linked
    inputs; for a pixel shader, per input "a vertex output feeds it" plus flat/linear/centroid (linked) or the
    default value (not linked), and point_sprite;
  * everything else as before.
Two environments with the same new key give the same GLSL text. TTT2_SHADER_KEY_CHECK=1 proves it at run time:
every cache hit is translated again and compared ("ttt2: shader key check: MISMATCH" if a text differs, a count
line every 10 s). TTT2_SHADER_KEY_FULL=1 = old key. Geometry shaders keep the old key.
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


sub("src/latte/program.h",
    """    std::vector<std::vector<VtxInstruction>> vtx_clauses;

    const CfInstruction* at(uint32_t index) const; // null if not decoded
""",
    """    std::vector<std::vector<VtxInstruction>> vtx_clauses;
    // port/patch_shader_key_canon.py: texture resources named by a texture instruction (not vertex fetches)
    uint32_t sampled_slots = 0;

    const CfInstruction* at(uint32_t index) const; // null if not decoded
""")

sub("src/latte/decode.cpp",
    """    std::sort(program.subroutines.begin(), program.subroutines.end());
    return true;
}
""",
    """    std::sort(program.subroutines.begin(), program.subroutines.end());
    for (const auto& clause : program.tex_clauses) { // port/patch_shader_key_canon.py
        for (const TexInstruction& t : clause) {
            if (!t.vfetch && t.resource_id < 32) program.sampled_slots |= 1u << t.resource_id;
        }
    }
    return true;
}
""")

sub("src/latte/translate.h",
    """uint64_t environment_key(const ShaderEnvironment& env);
""",
    """uint64_t environment_key(const ShaderEnvironment& env);
// port/patch_shader_key_canon.py: the same for a program that names only the texture slots in `sampled_slots`,
// with the link between the stages reduced to what the translation reads.
uint64_t environment_key(const ShaderEnvironment& env, uint32_t sampled_slots);
""")

sub("src/latte/environment.cpp",
    """} // namespace cafe::latte
""",
    """// port/patch_shader_key_canon.py. Must list everything Translator reads from the environment (translate.cpp:
// env_.textures[slot] only in emit_texture/the sampler declarations of sampled slots; env_.vs_out_semantic and
// env_.ps_inputs[].semantic only compared with each other).
uint64_t environment_key(const ShaderEnvironment& env, uint32_t sampled_slots) {
    Hasher h;
    h.add(static_cast<uint64_t>(env.stage));
    h.add(env.uniform_registers);
    for (uint32_t slot = 0; slot < 18; ++slot) {
        if (!(sampled_slots & (1u << slot))) continue;
        h.add(slot | (uint32_t{env.textures[slot].dim} << 8) | (static_cast<uint32_t>(env.textures[slot].kind) << 16));
    }
    h.add(env.ps_input_count);
    h.add(static_cast<uint8_t>(env.ps_position_input));
    // Which pixel-shader inputs each vertex parameter export feeds.
    uint32_t feeds[32] = {};
    uint32_t linked = 0;
    for (int p = 0; p < 32; ++p) {
        const uint8_t s = env.vs_out_semantic[p];
        if (s == 0xFF) continue;
        for (int k = 0; k < env.ps_input_count; ++k) {
            if (env.ps_inputs[k].semantic != s) continue;
            linked |= 1u << k; // the pixel shader's "exported" does not skip the position input
            if (k != env.ps_position_input) feeds[p] |= 1u << k;
        }
    }
    if (env.stage == Stage::kVertex) {
        for (uint32_t f : feeds) h.add(f);
        h.add(linked);
        for (int k = 0; k < env.ps_input_count; ++k) {
            const auto& in = env.ps_inputs[k];
            if (linked & (1u << k)) h.add(k | (in.flat << 8) | (in.linear << 9) | (in.centroid << 10));
        }
        for (uint8_t s : env.vtx_semantic) h.add(s);
        h.add(env.clip_space_dx | (env.point_size_export << 1) | (env.stream_out_mask << 2) | (env.rects << 6));
        for (uint16_t s : env.stream_out_stride) h.add(s);
        for (uint32_t w : env.vtx_const_word2) h.add(w);
        h.add(env.gs_part | (env.esgs_slots << 8) | (env.gs_in_vertices << 16) | (env.gs_out_prim << 24));
        h.add(env.gsvs_vertex_slots);
    } else {
        h.add(linked);
        for (int k = 0; k < env.ps_input_count; ++k) {
            const auto& in = env.ps_inputs[k];
            if (linked & (1u << k)) {
                h.add(k | (in.flat << 8) | (in.linear << 9) | (in.centroid << 10) | (in.point_sprite << 11));
            } else {
                h.add(k | (in.default_value << 12) | (in.point_sprite << 11) | 0x10000u);
            }
        }
        h.add(env.ps_front_face | (env.ps_front_face_all_bits << 1) | (env.ps_front_face_gpr << 2) |
              (env.ps_front_face_chan << 10));
        h.add(static_cast<uint8_t>(env.ps_param_gen_gpr) | (env.point_sprite_top_1 << 8) |
              (env.point_sprite_override[0] << 9) | (env.point_sprite_override[1] << 12) |
              (env.point_sprite_override[2] << 15) | (env.point_sprite_override[3] << 18));
        h.add(env.cb_shader_mask);
        h.add(env.multiwrite);
        for (TextureKind k : env.color_kind) h.add(static_cast<uint8_t>(k));
        h.add(env.alpha_func);
        // The header declares the stream-out buffer type for every stage while stream-out is on (the old key
        // left this out for pixel shaders: same module either way, but then the texts are not equal).
        h.add(env.stream_out_mask != 0);
    }
    return h.h;
}

} // namespace cafe::latte
""")

sub("src/gpu/vulkan/draw.cpp",
    """    const uint64_t keys[3] = {program_hash, fetch_hash, environment_key(env)};
    const uint64_t key = fnv(keys, sizeof(keys));
    auto& entry = shaders_[key];
    if (entry) {
        if (entry->module == VK_NULL_HANDLE && !entry->failed) resolve_module(*entry);
        return entry->failed ? nullptr : entry.get();
    }
""",
    """    // port/patch_shader_key_canon.py: the key holds only what the translation reads
    static const bool full_key = std::getenv("TTT2_SHADER_KEY_FULL") != nullptr;
    static const bool check_key = std::getenv("TTT2_SHADER_KEY_CHECK") != nullptr;
    const uint32_t sampled_slots = p->sampled_slots | (fetch ? fetch->sampled_slots : 0u);
    const uint64_t keys[3] = {program_hash, fetch_hash,
                              full_key ? environment_key(env) : environment_key(env, sampled_slots)};
    const uint64_t key = fnv(keys, sizeof(keys));
    auto& entry = shaders_[key];
    if (entry) {
        if (check_key && !entry->failed) {
            static uint64_t checked = 0, wrong = 0;
            static auto next_print = std::chrono::steady_clock::now() + std::chrono::seconds(10);
            latte::TranslatedShader again;
            std::string check_error;
            if (translate(*p, fetch, env, again, check_error)) {
                ++checked;
                if (fnv(again.glsl.data(), again.glsl.size()) != entry->glsl_hash) {
                    if (++wrong <= 20) {
                        std::fprintf(stderr, "ttt2: shader key check: MISMATCH %s %016llx key %016llx\\n",
                                     stage == Stage::kVertex ? "vs" : "ps", static_cast<unsigned long long>(program_hash),
                                     static_cast<unsigned long long>(key));
                        if (const char* dir = dump_directory()) { // beside the first text ps_<hash>_<key>.glsl
                            char name[160];
                            std::snprintf(name, sizeof(name), "mismatch_%s_%016llx_%016llx.glsl", stage == Stage::kVertex ? "vs" : "ps",
                                          static_cast<unsigned long long>(program_hash), static_cast<unsigned long long>(key));
                            std::ofstream(std::filesystem::path(dir) / name) << again.glsl;
                        }
                    }
                }
            }
            if (std::chrono::steady_clock::now() >= next_print) {
                std::fprintf(stderr, "ttt2: shader key check: %llu hits translated again, %llu with another text\\n",
                             static_cast<unsigned long long>(checked), static_cast<unsigned long long>(wrong));
                next_print = std::chrono::steady_clock::now() + std::chrono::seconds(10);
            }
        }
        if (entry->module == VK_NULL_HANDLE && !entry->failed) resolve_module(*entry);
        return entry->failed ? nullptr : entry.get();
    }
""")
