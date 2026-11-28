#!/usr/bin/env python3
"""patch_texture_surface_cache.py RUNTIME_SRC_DIR (.../runtime/src) : a texture's GX2 surface layout, computed once.

Every texture bind (load_texture, load_texture_from_targets) ran surface_of() = gx2::calc_surface_size_and_alignment
(AddrLib: ComputeSurfaceInfo, mip level tile modes) again for the texture's resource words. The words are the
texture's key and never change, so the layout does not either: it is now kept in the texture after the first
computation. Same result, less CPU on the draw thread (Mario Kart 8: ~3700 binds a frame in a race)."""
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

edit(d + "renderer.h", "patch_texture_surface_cache", [
    ("    uint64_t replacement_generation = 0;" + NL +
     "    bool rgba = false;" + NL,
     "    uint64_t replacement_generation = 0;" + NL +
     "    bool rgba = false;" + NL +
     "    bool surface_known = false; // port/patch_texture_surface_cache.py: `surface` = surface_of(words)" + NL +
     "    gx2::Surface surface{};" + NL),
])

edit(d + "textures.cpp", "patch_texture_surface_cache", [
    ("VkComponentSwizzle component(const FormatInfo& f, uint32_t sel) {" + NL,
     "// port/patch_texture_surface_cache.py: the words (the texture's key) never change, nor does their layout." + NL +
     "const gx2::Surface& surface_cached(Texture& t, const Resource& r) {" + NL +
     "    if (!t.surface_known) {" + NL +
     "        t.surface = surface_of(r);" + NL +
     "        t.surface_known = true;" + NL +
     "    }" + NL +
     "    return t.surface;" + NL +
     "}" + NL + NL +
     "VkComponentSwizzle component(const FormatInfo& f, uint32_t sel) {" + NL),
    ("    const FormatInfo f = color_format(r.format);" + NL +
     "    const gx2::Surface s = surface_of(r);" + NL +
     "    const uint32_t levels = std::min(r.last_level + 1, 14u);" + NL,
     "    const FormatInfo f = color_format(r.format);" + NL +
     "    const gx2::Surface& s = surface_cached(t, r); // port/patch_texture_surface_cache.py" + NL +
     "    const uint32_t levels = std::min(r.last_level + 1, 14u);" + NL),
    ("    if (replaying_ && t.loaded != 0) return;" + NL + NL +
     "    const gx2::Surface s = surface_of(r);" + NL,
     "    if (replaying_ && t.loaded != 0) return;" + NL + NL +
     "    const gx2::Surface& s = surface_cached(t, r); // port/patch_texture_surface_cache.py" + NL),
])
