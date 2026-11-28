#!/usr/bin/env python3
"""patch_slice_clear.py RUNTIME_SRC_DIR : GX2ClearColor / resolve on slice z of an array or 3D colour buffer use that
slice's render target.

port/patch_slice_targets.py gave every slice of an array/3D surface its own render target for DRAWS (key = base +
z * slice size) and for texture reads, but a ColorBuffer handed to GX2ClearColor (or used as a resolve source) was
still looked up by the surface's base address alone. A clear of slice 1 therefore cleared slice 0 a second time and
slice 1 was never cleared.

Mario Kart 8 accumulates its dynamic lights additively into a two-layer R11G11B10F array (diffuse in layer 0, specular
in layer 1; 1280x720, or 640x368 when the game switches to half-resolution lighting) and clears both layers every
frame. Layer 1 kept adding up frame after frame until the float format saturated (measured mean 37 at full and 138 at
half resolution, peaks 1000-3600): karts and drivers bleached gold-white, a blotchy glare on the road around every
kart, and a brightness jump whenever the game changed the light-buffer resolution (which it does from frame to frame).

Now the ColorBuffer's first slice selects the slice target, exactly as the draw path does."""
import sys

p = sys.argv[1] + "/gpu/vulkan/targets.cpp"
s = open(p, encoding="utf-8").read()
if "patch_slice_clear" in s:
    print("already applied"); sys.exit(0)
old = """Target* Renderer::color_target(const gx2::ColorBuffer& buffer) {
    return color_target(view_address(buffer.surface, buffer.view_mip) >> 8, buffer.cb_color_size, buffer.cb_color_info);
}
"""
new = """Target* Renderer::color_target(const gx2::ColorBuffer& buffer) {
    uint32_t base = view_address(buffer.surface, buffer.view_mip) >> 8;
    // port/patch_slice_clear.py: slice z of an array/3D surface is its own target (as in draw()).
    const uint32_t slice = uint32_t{buffer.view_first_slice} & 0x7FF;
    const bool sliced = slice != 0 && slice_targets_enabled();
    if (sliced) {
        const uint32_t size_reg = buffer.cb_color_size, info = buffer.cb_color_info;
        const uint32_t pitch = ((size_reg & 0x3FF) + 1) * 8;
        const uint32_t height = (((size_reg >> 10) & 0xFFFFF) + 1) * 64 / pitch;
        const uint32_t bytes = std::max(1u, color_format(color_buffer_surface_format(info)).bytes);
        base += slice * slice_key_bytes(pitch, height, bytes, (info >> 8) & 0xF) >> 8;
    }
    Target* t = color_target(base, buffer.cb_color_size, buffer.cb_color_info);
    if (sliced && t != nullptr) t->write_back = false; // its key is not its place in guest memory
    return t;
}
"""
assert old in s, "color_target(ColorBuffer) pattern"
open(p, "w", encoding="utf-8", newline="\n").write(s.replace(old, new))
print("patched", p)
