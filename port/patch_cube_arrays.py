#!/usr/bin/env python3
r"""patch_cube_arrays.py RUNTIME_SRC_DIR : cube-map ARRAYS are sampled as arrays (SET_CUBEMAP_INDEX selects the cube).

A GX2 cube texture with more than six faces is an array of cubes (SQ_TEX_RESOURCE_WORD1.TEX_DEPTH = cubes - 1). The
title picks the cube with the texture instruction SET_CUBEMAP_INDEX before the SAMPLE of that resource. The runtime
bound every cube texture as ONE cube (faces 0-5) and dropped SET_CUBEMAP_INDEX (port/patch_cubemap_index.py), so
every surface that reflects its surroundings showed cube 0: Mario Kart 8 keeps its reflection probes in one array
(8 cubes, 128x128, BC3) and gives each object the index of the probe near it.

Now:
- latte/environment.cpp: a cube resource with TEX_DEPTH != 0 has the internal dimension 8 (latte::kDimCubeArray);
- latte/translate.cpp: dimension 8 is a samplerCubeArray; SET_CUBEMAP_INDEX stores its x source in a per-slot
  variable and the samples of that slot take it as the layer (0 before the first SET_CUBEMAP_INDEX);
- gpu/vulkan/textures.cpp: such a texture's view is a VK_IMAGE_VIEW_TYPE_CUBE_ARRAY over all its cubes.
Shaders of plain cubes, and every other shader, keep their GLSL (and their SPIR-V cache entries).
Without the device feature imageCubeArray, or with TTT2_CUBE_ARRAYS=0, everything is as before (cube 0).

Debugging: TTT2_TRACE_TEX (the traced draw's textures as PNGs) now also saves every layer of every level of
layered textures, and images in formats save_image cannot read (block-compressed), through a blit to RGBA8:
tex_<stage><slot>_L<layer>_M<level>.png."""
import sys

root = sys.argv[1] + "/"


def edit(name, pairs):
    path = root + name
    s = open(path, encoding="utf-8").read()
    if "patch_cube_arrays" in s:
        print("already applied:", name)
        return
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


edit("latte/translate.h", [
    ("enum class TextureKind : uint8_t { kFloat, kUint, kSint };\n",
     "enum class TextureKind : uint8_t { kFloat, kUint, kSint };\n"
     "\n"
     "// port/patch_cube_arrays.py: ShaderEnvironment::Texture::dim of a cube resource with more than one cube\n"
     "// (SQ_TEX_DIM has no value for it: it is DIM_CUBEMAP with TEX_DEPTH != 0).\n"
     "constexpr uint8_t kDimCubeArray = 8;\n"
     "// Whether cube arrays are bound as arrays (the device can, and TTT2_CUBE_ARRAYS is not 0).\n"
     "bool cube_arrays();\n"
     "void set_cube_arrays(bool on);\n"),
])

edit("latte/environment.cpp", [
    ("namespace cafe::latte {\n\nvoid build_environment(",
     "namespace cafe::latte {\n\n"
     "namespace {\nbool g_cube_arrays = true; // port/patch_cube_arrays.py\n}\n"
     "bool cube_arrays() { return g_cube_arrays; }\n"
     "void set_cube_arrays(bool on) { g_cube_arrays = on; }\n\n"
     "void build_environment("),
    ("        t.dim = static_cast<uint8_t>(r(base) & 7);\n",
     "        t.dim = static_cast<uint8_t>(r(base) & 7);\n"
     "        // port/patch_cube_arrays.py: a cube with TEX_DEPTH != 0 is an array of cubes\n"
     "        if (t.dim == 3 && ((r(base + 4) >> 13) & 0x1FFF) != 0 && g_cube_arrays) t.dim = kDimCubeArray;\n"),
])

edit("latte/translate.cpp", [
    ("    uint32_t shadow_mask_ = 0;\n    bool uses_registers_ = false;\n",
     "    uint32_t shadow_mask_ = 0;\n"
     "    uint32_t cube_index_mask_ = 0; // port/patch_cube_arrays.py: cube-array slots (their cube_index variable)\n"
     "    bool uses_registers_ = false;\n"),
    ("    case kSetCubemapIndex: // port/patch_cubemap_index.py: cube maps are bound as single cubes, layer 0\n"
     "        return;\n",
     "    case kSetCubemapIndex: // port/patch_cubemap_index.py: a single cube has nothing to select\n"
     "        // port/patch_cube_arrays.py: the cube the next samples of this resource read\n"
     "        if (tx.dim == kDimCubeArray) {\n"
     "            cube_index_mask_ |= 1u << slot;\n"
     "            line(format(\"cube_index%u = %s;\", slot, tex_coord(t, 0).c_str()));\n"
     "        }\n"
     "        return;\n"),
    ("    case 3: coords = 3; cube = true; break;   // cube\n",
     "    case 3: coords = 3; cube = true; break;   // cube\n"
     "    case kDimCubeArray: coords = 3; cube = true; cube_index_mask_ |= 1u << slot; break; // port/patch_cube_arrays.py\n"),
    ("        coord = \"cube_dir(vec2(\" + c[0] + \", \" + c[1] + \"), \" + c[2] + \")\";\n",
     "        coord = \"cube_dir(vec2(\" + c[0] + \", \" + c[1] + \"), \" + c[2] + \")\";\n"
     "        if (dim == kDimCubeArray) coord = format(\"vec4(%s, cube_index%u)\", coord.c_str(), slot); // port/patch_cube_arrays.py\n"),
    ("        case 3: type = \"samplerCube\"; break;\n",
     "        case 3: type = \"samplerCube\"; break;\n"
     "        case kDimCubeArray: type = \"samplerCubeArray\"; break; // port/patch_cube_arrays.py\n"),
    ("    // Interface between the stages.\n",
     "    for (uint32_t slot = 0; slot < abi::kTextureSlots; ++slot) { // port/patch_cube_arrays.py\n"
     "        if (cube_index_mask_ & (1u << slot)) h += format(\"float cube_index%u = 0.0;\\n\", slot);\n"
     "    }\n"
     "    // Interface between the stages.\n"),
])

edit("gpu/vulkan/textures.cpp", [
    ("#include \"gpu/tiling.h\"\n",
     "#include \"gpu/tiling.h\"\n#include \"latte/translate.h\" // port/patch_cube_arrays.py\n"),
    ("    t.image = create_image(f.format, VK_IMAGE_ASPECT_COLOR_BIT, scaled(r.width, scale), scaled(r.height, scale),\n"
     "                           layers, r.last_level + 1,\n"
     "                           VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,\n"
     "                           view_type_of(r.dim));\n",
     "    // port/patch_cube_arrays.py: more than six faces = an array of cubes (the shader's sampler is one then,\n"
     "    // see latte/environment.cpp)\n"
     "    VkImageViewType view_type = view_type_of(r.dim);\n"
     "    if (r.dim == gx2::kDimCube && layers > 6 && cafe::latte::cube_arrays()) view_type = VK_IMAGE_VIEW_TYPE_CUBE_ARRAY;\n"
     "    t.image = create_image(f.format, VK_IMAGE_ASPECT_COLOR_BIT, scaled(r.width, scale), scaled(r.height, scale),\n"
     "                           layers, r.last_level + 1,\n"
     "                           VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,\n"
     "                           view_type);\n"),
    ("    vci.viewType = view_type_of(r.dim);\n", "    vci.viewType = view_type;\n"),
    ("    if (vci.viewType == VK_IMAGE_VIEW_TYPE_CUBE) {\n        first = 0;\n        count = 6;\n    } else if",
     "    if (vci.viewType == VK_IMAGE_VIEW_TYPE_CUBE) {\n        first = 0;\n        count = 6;\n"
     "    } else if (vci.viewType == VK_IMAGE_VIEW_TYPE_CUBE_ARRAY) { // whole cubes\n"
     "        first = 0;\n        count = layers / 6 * 6;\n"
     "    } else if"),
])

edit("gpu/vulkan/context.cpp", [
    ("#include \"cafe/runtime.h\"\n",
     "#include \"cafe/runtime.h\"\n#include \"latte/translate.h\" // port/patch_cube_arrays.py\n"),
    ("    ef.imageCubeArray = af.imageCubeArray;\n",
     "    ef.imageCubeArray = af.imageCubeArray;\n"
     "    { // port/patch_cube_arrays.py\n"
     "        const char* v = std::getenv(\"TTT2_CUBE_ARRAYS\");\n"
     "        cafe::latte::set_cube_arrays(af.imageCubeArray && !(v != nullptr && v[0] == '0'));\n"
     "        if (!cafe::latte::cube_arrays()) std::fprintf(stderr, \"ttt2: GPU: cube-map arrays show their first cube (%s)\\n\",\n"
     "                                                af.imageCubeArray ? \"TTT2_CUBE_ARRAYS=0\" : \"no imageCubeArray\");\n"
     "    }\n"),
])

edit("gpu/vulkan/renderer.h", [
    ("    void save_image(const Image& image, const std::string& path, bool keep_alpha = false);\n",
     "    void save_image(const Image& image, const std::string& path, bool keep_alpha = false);\n"
     "    // port/patch_cube_arrays.py: one layer and level of any colour image, through a blit to RGBA8\n"
     "    void save_image_layer(const Image& image, uint32_t layer, uint32_t level, const std::string& path);\n"),
])

edit("gpu/vulkan/renderer.cpp", [
    ("void Renderer::save_image(const Image& img, const std::string& path, bool keep_alpha) {\n",
     "// port/patch_cube_arrays.py (debugging)\n"
     "void Renderer::save_image_layer(const Image& img, uint32_t layer, uint32_t level, const std::string& path) {\n"
     "    if (img.aspect != VK_IMAGE_ASPECT_COLOR_BIT || layer >= img.layers || level >= img.levels) return;\n"
     "    if (!(ctx_.format_features(img.format) & VK_FORMAT_FEATURE_BLIT_SRC_BIT)) return;\n"
     "    const uint32_t w = std::max(1u, img.width >> level), h = std::max(1u, img.height >> level);\n"
     "    Image tmp = create_image(VK_FORMAT_R8G8B8A8_UNORM, VK_IMAGE_ASPECT_COLOR_BIT, w, h, 1, 1,\n"
     "                             VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,\n"
     "                             VK_IMAGE_VIEW_TYPE_2D);\n"
     "    end_rendering();\n"
     "    barrier();\n"
     "    VkImageBlit blit{};\n"
     "    blit.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, level, layer, 1};\n"
     "    blit.srcOffsets[1] = {static_cast<int32_t>(w), static_cast<int32_t>(h), 1};\n"
     "    blit.dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1};\n"
     "    blit.dstOffsets[1] = {static_cast<int32_t>(w), static_cast<int32_t>(h), 1};\n"
     "    vkCmdBlitImage(cmd(), img.image, VK_IMAGE_LAYOUT_GENERAL, tmp.image, VK_IMAGE_LAYOUT_GENERAL, 1, &blit, VK_FILTER_NEAREST);\n"
     "    barrier();\n"
     "    save_image(tmp, path, true);\n"
     "    submit(true);\n"
     "    destroy_image(tmp);\n"
     "}\n\n"
     "void Renderer::save_image(const Image& img, const std::string& path, bool keep_alpha) {\n"),
])

edit("gpu/vulkan/draw.cpp", [
    ("                    save_image(t->image, std::string(tex_dir) + name);\n",
     "                    save_image(t->image, std::string(tex_dir) + name);\n"
     "                    // port/patch_cube_arrays.py: every layer of every level (layered or compressed images)\n"
     "                    if (t->image.layers > 1 || t->image.format >= VK_FORMAT_BC1_RGB_UNORM_BLOCK) {\n"
     "                        for (uint32_t level = 0; level < t->image.levels; ++level) {\n"
     "                            for (uint32_t layer = 0; layer < t->image.layers; ++layer) {\n"
     "                                char ln[64];\n"
     "                                std::snprintf(ln, sizeof(ln), \"/tex_%s%u_L%02u_M%u.png\", stage, slot, layer, level);\n"
     "                                save_image_layer(t->image, layer, level, std::string(tex_dir) + ln);\n"
     "                            }\n"
     "                        }\n"
     "                    }\n"),
])
