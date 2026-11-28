#!/usr/bin/env python3
"""TTT2_TRACE_SHADER_KEYS=1: why does the shader cache keep growing? (measuring tool, off by default)

usage: patch_trace_shader_keys.py RUNTIME_DIR   (e.g. ~/wiiu/smash4/runtime)

Renderer::shaders_ is keyed by program + fetch shader + the WHOLE shader environment. A draw with the same
program but another environment (other texture kinds in slots the program never samples, other attribute
buffer formats ...) is a new entry = one more translation on the draw thread. With the switch, every 10
seconds one line says: how many translations, how many of them gave GLSL text that was already known
("same text" = a wasted translation), and which environment field groups differed from the last environment
seen for that program. Costs nothing without the switch.
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


sub("src/gpu/vulkan/draw.cpp",
    """    const uint64_t glsl_hash = fnv(entry->info.glsl.data(), entry->info.glsl.size());
    entry->glsl_hash = glsl_hash;
    // port/patch_shader_text_release.py""",
    """    const uint64_t glsl_hash = fnv(entry->info.glsl.data(), entry->info.glsl.size());
    entry->glsl_hash = glsl_hash;
    { // port/patch_trace_shader_keys.py
        static const bool trace_keys = std::getenv("TTT2_TRACE_SHADER_KEYS") != nullptr;
        if (trace_keys) {
            static std::unordered_map<uint64_t, ShaderEnvironment> last_env;
            static std::unordered_map<uint64_t, uint32_t> seen_text;
            static auto next_print = std::chrono::steady_clock::now() + std::chrono::seconds(10);
            static uint32_t n = 0, same = 0, first = 0, d_tex = 0, d_vsem = 0, d_out = 0, d_psin = 0, d_w2 = 0, d_cb = 0,
                            d_alpha = 0, d_misc = 0, d_none = 0;
            ++n;
            if (seen_text[glsl_hash]++) ++same;
            const uint64_t pk[3] = {program_hash, fetch_hash, static_cast<uint64_t>(stage)};
            const uint64_t pkey = fnv(pk, sizeof pk);
            auto found = last_env.find(pkey);
            if (found == last_env.end()) {
                ++first;
            } else {
                const ShaderEnvironment& o = found->second;
                bool any = false;
                const auto differs = [&](bool d, uint32_t& counter) {
                    if (d) { ++counter; any = true; }
                };
                bool tex = false;
                for (int i = 0; i < 18; ++i) tex |= o.textures[i].dim != env.textures[i].dim || o.textures[i].kind != env.textures[i].kind;
                differs(tex, d_tex);
                differs(std::memcmp(o.vtx_semantic, env.vtx_semantic, sizeof o.vtx_semantic) != 0, d_vsem);
                differs(std::memcmp(o.vs_out_semantic, env.vs_out_semantic, sizeof o.vs_out_semantic) != 0, d_out);
                bool psin = o.ps_input_count != env.ps_input_count || o.ps_position_input != env.ps_position_input;
                for (int k = 0; k < 32 && !psin; ++k) {
                    psin = o.ps_inputs[k].semantic != env.ps_inputs[k].semantic || o.ps_inputs[k].flat != env.ps_inputs[k].flat ||
                           o.ps_inputs[k].linear != env.ps_inputs[k].linear || o.ps_inputs[k].centroid != env.ps_inputs[k].centroid ||
                           o.ps_inputs[k].default_value != env.ps_inputs[k].default_value ||
                           o.ps_inputs[k].point_sprite != env.ps_inputs[k].point_sprite;
                }
                differs(psin, d_psin);
                differs(std::memcmp(o.vtx_const_word2, env.vtx_const_word2, sizeof o.vtx_const_word2) != 0, d_w2);
                differs(o.cb_shader_mask != env.cb_shader_mask || o.multiwrite != env.multiwrite ||
                            std::memcmp(o.color_kind, env.color_kind, sizeof o.color_kind) != 0, d_cb);
                differs(o.alpha_func != env.alpha_func, d_alpha);
                differs(o.clip_space_dx != env.clip_space_dx || o.rects != env.rects || o.point_size_export != env.point_size_export ||
                            o.stream_out_mask != env.stream_out_mask || o.uniform_registers != env.uniform_registers ||
                            o.ps_front_face != env.ps_front_face || o.ps_param_gen_gpr != env.ps_param_gen_gpr || o.gs_part != env.gs_part, d_misc);
                if (!any) ++d_none;
            }
            last_env[pkey] = env;
            if (std::chrono::steady_clock::now() >= next_print) {
                std::fprintf(stderr,
                             "ttt2: shader keys: %u translations (%u same text as an earlier one, %u first of their program); "
                             "differed from the program's last environment in: textures %u, vtx semantics %u, vs outputs %u, "
                             "ps inputs %u, attribute formats %u, colour targets/mask %u, alpha test %u, other %u, nothing listed %u; "
                             "%zu programs, %zu texts\\n",
                             n, same, first, d_tex, d_vsem, d_out, d_psin, d_w2, d_cb, d_alpha, d_misc, d_none, last_env.size(),
                             seen_text.size());
                n = same = first = d_tex = d_vsem = d_out = d_psin = d_w2 = d_cb = d_alpha = d_misc = d_none = 0;
                next_print = std::chrono::steady_clock::now() + std::chrono::seconds(10);
            }
        }
    }
    // port/patch_shader_text_release.py""")
