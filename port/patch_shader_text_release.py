#!/usr/bin/env python3
"""patch_shader_text_release.py RUNTIME_SRC_DIR (.../runtime/src) : the shader cache does not keep the GLSL text.

Renderer::shaders_ has one entry per (program, fetch shader, environment key) and kept each entry's translated GLSL
(entry->info.glsl) for good. The environment key covers state the shader may not use (all 18 texture slots, the
formats of all 16 attribute buffers, ...), so a title keeps making new entries whose GLSL is one it had already:
Mario Kart 8 on the console went from 3700 to 57000 entries in 35 minutes (pipelines stayed at 2300-2700), and the
process's own memory (RssAnon) grew with it, 340 -> 2120 MB, about 37 KB per entry: 50 MB a minute.

The text is only needed to hash it (glsl_hash, which names the module, the pipelines and the SPIR-V cache) and to
compile it once: now it is moved out of the entry right after hashing, into the worker's compile job (or the
compile on the draw thread), and freed after. The entry keeps the rest (masks, extents: a few hundred bytes)."""
import sys

NL = "\n"


def edit(path, marker, pairs):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        print("already applied:", path)
        return
    for old, new in pairs:
        assert s.count(old) == 1, "pattern not found (or not unique) in %s: %r" % (path, old[:80])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


d = sys.argv[1] + "/gpu/vulkan/"

edit(d + "draw.cpp", "patch_shader_text_release", [
    ("    entry->glsl_hash = glsl_hash;" + NL + "    if (auto it = modules_.find(glsl_hash); it != modules_.end()) {" + NL,
     "    entry->glsl_hash = glsl_hash;" + NL +
     "    // port/patch_shader_text_release.py: the text goes to the compile (once per glsl_hash), not into the cache entry." + NL +
     "    std::string glsl_text = std::move(entry->info.glsl);" + NL +
     "    entry->info.glsl = std::string();" + NL +
     "    if (auto it = modules_.find(glsl_hash); it != modules_.end()) {" + NL),
    ("            compile_async([this, pending, glsl = entry->info.glsl, glsl_hash,",
     "            compile_async([this, pending, glsl = std::move(glsl_text), glsl_hash,"),
    ("            compiler_, entry->info.glsl.data(), entry->info.glsl.size()," + NL +
     "            stage == Stage::kVertex ? shaderc_vertex_shader : shaderc_fragment_shader, kind, \"main\", options);" + NL,
     "            compiler_, glsl_text.data(), glsl_text.size(), // port/patch_shader_text_release.py" + NL +
     "            stage == Stage::kVertex ? shaderc_vertex_shader : shaderc_fragment_shader, kind, \"main\", options);" + NL),
    ("    entry->module = cached_module(glsl_hash, &spirv);" + NL + "    return entry.get();" + NL + "}" + NL + NL +
     "// Takes `entry`'s module from a finished worker compile, if any." + NL,
     "    entry->module = cached_module(glsl_hash, &spirv);" + NL +
     "    entry->info.glsl = std::string(); // port/patch_shader_text_release.py" + NL +
     "    return entry.get();" + NL + "}" + NL + NL +
     "// Takes `entry`'s module from a finished worker compile, if any." + NL),
])
