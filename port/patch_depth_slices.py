#!/usr/bin/env python3
"""patch_depth_slices.py RUNTIME_SRC_DIR : slice z of an array DEPTH buffer is its own render target, and a depth
array read as a texture gets every layer.

port/patch_slice_targets.py / patch_slice_clear.py gave the slices of array COLOUR buffers their own targets. Depth
buffers still ignored DB_DEPTH_VIEW (draws) and DepthBuffer::view_first_slice (GX2ClearDepthStencil): every slice of
a depth array was drawn into, and cleared in, the one target at the surface's base address, and a depth array bound
as a texture only ever got its layer 0 filled from that target (the other layers stayed empty).

Mario Kart 8 renders its dynamic shadows (karts, drivers, items) as a cascaded shadow map: a 16-bit depth 2D array
with two layers (1024x1024, smaller when its quality scaler steps down), clear + draw per layer, sampled with a
compare sampler as a 2D array. Here both cascades landed on top of each other in layer 0 (the far cascade cleared the
near one and was then looked up with the near cascade's matrix), layer 1 was empty: no shadow under the karts, torn
blocky dark scraps beside them.

Now, as for colour buffers: key of slice z = base + z * slice size; draw and clear pick the slice target, and the
depth-as-texture copy fills layer z from the slice target z. TTT2_SLICE_TARGETS=0 turns all slice targets off (old
behaviour); TTT2_LOG_TARGETS=1 prints the depth slice draws."""
import sys

root = sys.argv[1] + "/gpu/vulkan/"


def edit(name, pairs):
    path = root + name
    s = open(path, encoding="utf-8").read()
    if "patch_depth_slices" in s:
        print("already applied:", name)
        return
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


# ---- renderer.h: helper + layer argument
edit("renderer.h", [
    ("""    void copy_depth_to_texture(const Target& src, Texture& t, uint32_t width, uint32_t height);
""",
     """    // port/patch_depth_slices.py: the base register (address >> 8) of slice z of an array depth buffer.
    static uint32_t depth_slice_base(uint32_t base_reg, uint32_t size_reg, uint32_t info_reg, uint32_t slice) {
        if (slice == 0 || !slice_targets_enabled()) return base_reg;
        const uint32_t pitch = ((size_reg & 0x3FF) + 1) * 8;
        const uint32_t height = (((size_reg >> 10) & 0xFFFFF) + 1) * 64 / pitch;
        const uint32_t hw = info_reg & 7; // DB_DEPTH_INFO format: 1 = 16-bit, 7 = 32-bit float + 8-bit stencil (8 bytes)
        const uint32_t bytes = hw == 1 ? 2 : hw == 7 ? 8 : 4;
        return base_reg + (slice * slice_key_bytes(pitch, height, bytes, (info_reg >> 15) & 0xF) >> 8);
    }
    void copy_depth_to_texture(const Target& src, Texture& t, uint32_t width, uint32_t height, uint32_t layer = 0);
"""),
])

# ---- draw.cpp: the draw's depth target follows DB_DEPTH_VIEW
edit("draw.cpp", [
    ("""        depth = depth_target(r(reg::DB_DEPTH_BASE), r(reg::DB_DEPTH_SIZE), r(reg::DB_DEPTH_INFO));
""",
     """        // port/patch_depth_slices.py: slice z of an array depth buffer is its own target (as for colour buffers).
        const uint32_t depth_slice = r(reg::DB_DEPTH_VIEW) & 0x7FF;
        if (depth_slice != 0) must_draw = true;
        depth = depth_target(depth_slice_base(r(reg::DB_DEPTH_BASE), r(reg::DB_DEPTH_SIZE), r(reg::DB_DEPTH_INFO), depth_slice),
                             r(reg::DB_DEPTH_SIZE), r(reg::DB_DEPTH_INFO));
        if (static const bool log = std::getenv("TTT2_LOG_TARGETS") != nullptr; log && depth_slice != 0) {
            std::fprintf(stderr, "ttt2: slice draw: depth base 0x%08X slice %u (frame %llu, draw %llu)\\n",
                         r(reg::DB_DEPTH_BASE) << 8, depth_slice, static_cast<unsigned long long>(frame_number_),
                         static_cast<unsigned long long>(draws_));
        }
"""),
])

# ---- targets.cpp: GX2ClearDepthStencil (and every other DepthBuffer lookup) follows view_first_slice
edit("targets.cpp", [
    ("""Target* Renderer::depth_target(const gx2::DepthBuffer& buffer) {
    return depth_target(view_address(buffer.surface, buffer.view_mip) >> 8, buffer.db_depth_size,
                        buffer.db_depth_info);
}
""",
     """Target* Renderer::depth_target(const gx2::DepthBuffer& buffer) {
    // port/patch_depth_slices.py: slice z of an array depth buffer is its own target (as in draw()).
    const uint32_t slice = uint32_t{buffer.view_first_slice} & 0x7FF;
    return depth_target(depth_slice_base(view_address(buffer.surface, buffer.view_mip) >> 8, buffer.db_depth_size,
                                         buffer.db_depth_info, slice),
                        buffer.db_depth_size, buffer.db_depth_info);
}
"""),
])

# ---- textures.cpp: a depth array read as a texture takes layer z from slice target z
edit("textures.cpp", [
    ("""void Renderer::copy_depth_to_texture(const Target& src, Texture& t, uint32_t width, uint32_t height) {
    note_target_read(&src);
    const uint32_t bytes = src.image.format == VK_FORMAT_D16_UNORM ? 2 : 4;
    if (t.scale != src.scale) create_texture_image(t, src.scale);
""",
     """void Renderer::copy_depth_to_texture(const Target& src, Texture& t, uint32_t width, uint32_t height, uint32_t layer) {
    note_target_read(&src);
    const uint32_t bytes = src.image.format == VK_FORMAT_D16_UNORM ? 2 : 4;
    if (t.scale != src.scale) {
        if (layer != 0) return; // port/patch_depth_slices.py: layer 0 decides the texture's scale
        create_texture_image(t, src.scale);
    }
"""),
    ("""    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    vkCmdCopyBufferToImage(cmd(), depth_staging_.buffer, t.image.image, VK_IMAGE_LAYOUT_GENERAL, 1, &region);
""",
     """    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.baseArrayLayer = layer; // port/patch_depth_slices.py
    vkCmdCopyBufferToImage(cmd(), depth_staging_.buffer, t.image.image, VK_IMAGE_LAYOUT_GENERAL, 1, &region);
"""),
    ("""            if (t.source != src || t.loaded < src->written) {
                copy_depth_to_texture(*src, t, r.width, r.height);
                t.source = src;
                t.loaded = stamp();
                t.dirty = false;
            }
            return;
""",
     """            // port/patch_depth_slices.py: the other layers of a depth array come from their slice targets
            // (key = base + z * slice size, as depth_slice_base() makes it for draws and clears).
            const Target* slices[64] = {};
            uint64_t newest = src->written;
            const bool is_array = r.dim == gx2::kDim2DArray || r.dim == gx2::kDim2DMsaaArray;
            const uint32_t slice_count = is_array && r.depth > 1 && slice_targets_enabled() ? std::min(r.depth, 64u) : 0;
            const uint32_t step = slice_key_bytes(src->pitch, src->height, std::max(1u, depth_format(src->format).bytes),
                                                  src->tile_mode);
            for (uint32_t z = 1; z < slice_count; ++z) {
                // the slice target of layer 0's size: titles that resize their shadow maps (MK8's quality scaler)
                // leave targets of other sizes at the same key
                const Target* other = nullptr;
                if (const auto it = targets_by_address_.find(src->address + z * step); it != targets_by_address_.end()) {
                    for (const Target* c : it->second) {
                        if (c->depth && c->format == src->format && c->pitch == src->pitch && c->height == src->height &&
                            c->scale == src->scale && c->written > c->overwritten) {
                            other = c;
                        }
                    }
                }
                if (other == nullptr) continue;
                slices[z] = other;
                newest = std::max(newest, other->written);
            }
            if (t.source != src || t.loaded < newest) {
                copy_depth_to_texture(*src, t, r.width, r.height);
                for (uint32_t z = 1; z < slice_count; ++z) {
                    if (slices[z] && z < t.image.layers) copy_depth_to_texture(*slices[z], t, r.width, r.height, z);
                }
                t.source = src;
                t.loaded = stamp();
                t.dirty = false;
            }
            return;
"""),
])
