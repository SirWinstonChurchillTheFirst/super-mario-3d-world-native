#!/usr/bin/env python3
"""patch_compressed_slices.py RUNTIME_SRC_DIR : the other faces / layers of a block-compressed cube or array texture
that the title compresses on the GPU.

Mario Kart 8 renders its reflection cube maps (BC3, RGBM-encoded HDR, 128x128, a cube ARRAY of 8 cubes = 48 layers,
4 cubes filled) by drawing every 4x4 block as one 128-bit texel into colour buffers over the texture's memory (slice
z of a 32x32 R32G32B32A32 array, 16x16 for level 1). A texture read from render targets took the slices of a
3D/array/cube texture from the slice targets only when it was NOT compressed, so every face but the first was never
filled from what the GPU rendered.

Now compressed textures take their other slices from the slice targets too (a target texel is a block), and the
slice copies are sized in blocks.

A cube image's layers beyond the first six were left in the undefined layout by patch_cube_view.py (the creation-time
transition used the view's range): the transition now covers every layer, as the copies into layers 6+ need it
(the validation layer reported VUID-vkCmdDraw-None-09600 otherwise).

The runtime still shows cube 0 of a cube array only (patch_cube_view.py / patch_cubemap_index.py)."""
import sys

NL = "\n"


def edit(path, marker, pairs):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        print("already applied:", path)
        return
    for old, new in pairs:
        assert s.count(old) == 1, "pattern not found (or not unique) in %s: %r" % (path, old[:60])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


d = sys.argv[1] + "/gpu/vulkan/"

edit(d + "textures.cpp", "patch_compressed_slices", [
    ("    const uint32_t slice_count = r.depth > 1 && !f.compressed && slice_targets_enabled() ? std::min(r.depth, 64u) : 0;" + NL,
     "    // port/patch_compressed_slices.py: compressed textures too (the slice targets hold their blocks as texels)" + NL +
     "    const uint32_t slice_count = r.depth > 1 && slice_targets_enabled() ? std::min(r.depth, 64u) : 0;" + NL),
    ("            region.extent = {std::min(width, src->image.width), std::min(height, src->image.height), 1};" + NL +
     "            vkCmdCopyImage(cmd(), src->image.image, VK_IMAGE_LAYOUT_GENERAL, t.image.image, VK_IMAGE_LAYOUT_GENERAL, 1," + NL +
     "                           &region);" + NL +
     "        }" + NL +
     "    }" + NL +
     "    barrier();" + NL,
     "            // in source texels, which are the destination's blocks (port/patch_compressed_slices.py)" + NL +
     "            region.extent = {std::min((width + block - 1) / block, src->image.width)," + NL +
     "                             std::min((height + block - 1) / block, src->image.height), 1};" + NL +
     "            vkCmdCopyImage(cmd(), src->image.image, VK_IMAGE_LAYOUT_GENERAL, t.image.image, VK_IMAGE_LAYOUT_GENERAL, 1," + NL +
     "                           &region);" + NL +
     "        }" + NL +
     "    }" + NL +
     "    barrier();" + NL),
])

TAIL = ("    VkDependencyInfo di{VK_STRUCTURE_TYPE_DEPENDENCY_INFO};" + NL +
        "    di.imageMemoryBarrierCount = 1;" + NL +
        "    di.pImageMemoryBarriers = &ib;" + NL)
edit(d + "renderer.cpp", "every layer (port/patch_compressed_slices.py)", [
    ("    ib.subresourceRange = vci.subresourceRange;" + NL + TAIL,
     "    ib.subresourceRange = {aspect, 0, img.levels, 0, ici.arrayLayers}; // every layer (port/patch_compressed_slices.py)" + NL + TAIL),
])
