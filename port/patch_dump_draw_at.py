#!/usr/bin/env python3
"""patch_dump_draw_at.py RUNTIME_SRC_DIR (.../runtime/src) : TOOL - one draw's inputs and result, without a frame trace.

TTT2_DUMP_DRAW_AT=<seconds>,<pixel shader hash hex>[,<count>[,<every>]]: from <seconds> on (renderer clock) the first
<count> (default 1) draws with that pixel shader, then (if <every> is given) every <every>-th one, are written to TTT2_CAPTURE:
  - "dumpdraw:" lines in the log: draw, viewport, targets, index list, the vertex buffers 0/1 (big-endian floats) and the
    constant blocks the two shaders use;
  - after the draw, raw images (no PNG): the colour target 0, the depth target and every pixel shader texture that comes
    from a render target, and every layered one with all its layers (dumpdraw_<n>_<what>_<w>x<h>_f<vk format>.raw, rows of texels as the GPU has them).
Made for the console (no frame trace there): Mario Kart 8 blob shadows on Thwomp Ruins (25/26 Nov). Costs nothing when
the switch is not set."""
import sys

NL = "\n"


def edit(path, marker, pairs):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        print("already applied:", path)
        return
    for old, new in pairs:
        assert s.count(old) == 1, "pattern not found once in %s: %r" % (path, old[:80])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


d = sys.argv[1] + "/gpu/vulkan/"

BLOCK = r'''
    { // port/patch_dump_draw_at.py: TTT2_DUMP_DRAW_AT=<seconds>,<ps hash>[,<count>[,<every>]]
        static const char* spec = std::getenv("TTT2_DUMP_DRAW_AT");
        static const char* dir = std::getenv("TTT2_CAPTURE");
        if (spec && dir) {
            static const double at = std::atof(spec);
            static uint64_t want = 0;
            static int left = 1, every = 0, seen = 0, n = 0;
            static const bool parsed = [] {
                const char* c = std::strchr(spec, ',');
                if (c) want = std::strtoull(c + 1, nullptr, 16);
                c = c ? std::strchr(c + 1, ',') : nullptr;
                if (c) left = std::atoi(c + 1);
                c = c ? std::strchr(c + 1, ',') : nullptr;
                if (c) every = std::max(1, std::atoi(c + 1));
                return true;
            }();
            (void)parsed;
            static const auto start = std::chrono::steady_clock::now();
            static bool armed = false; // the clock first, the shader hash only once it is time
            if (!armed) armed = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() >= at;
            uint64_t ph = 0;
            if (armed && (left > 0 || every > 0)) program(r(reg::SQ_PGM_START_PS) << 8, r(reg::SQ_PGM_START_PS + 4) << 3, ph);
            if (armed && ph == want && (left > 0 || (every > 0 && (++seen % every) == 0))) {
                if (left > 0) --left;
                const int k = n++;
                std::fprintf(stderr, "dumpdraw: %d frame %llu prim 0x%X count %u%s inst %u index_count %u base_vertex %u start_instance %u\n",
                             k, static_cast<unsigned long long>(frame_number_), r(reg::VGT_PRIMITIVE_TYPE), d.count,
                             indexed ? " indexed" : "", instances, index_count, dc.base_vertex, dc.start_instance);
                std::fprintf(stderr, "dumpdraw: %d viewport %g,%g %gx%g depth %g-%g scissor %d,%d %ux%u cull 0x%X depth_control 0x%08X clip 0x%08X vte 0x%08X\n",
                             k, viewport.x, viewport.y, viewport.width, viewport.height, viewport.minDepth,
                             viewport.maxDepth, scissor.offset.x, scissor.offset.y, scissor.extent.width,
                             scissor.extent.height, mode & 7, depth_control, r(reg::PA_CL_CLIP_CNTL), r(reg::PA_CL_VTE_CNTL));
                if (indexed && index_count <= 4096) {
                    const uint32_t* ix = reinterpret_cast<const uint32_t*>(ring_.mapped() + index_offset);
                    std::string line;
                    for (uint32_t i = 0; i < index_count; ++i) line += std::to_string(ix[i]) + " ";
                    std::fprintf(stderr, "dumpdraw: %d indices %s\n", k, line.c_str());
                }
                const auto be_float = [&](uint32_t address) {
                    uint32_t w = 0;
                    if (guest_memory_committed(address, 4)) std::memcpy(&w, guest_pointer(address), 4);
                    return std::bit_cast<float>(__builtin_bswap32(w));
                };
                for (uint32_t i = 0; i < 2; ++i) {
                    const uint32_t base = kResourceBase + (resource::kVsAttrib + i) * resource::kWords * 4;
                    const uint32_t va = r(base), size = r(base + 4) + 1, stride = (r(base + 8) >> 8) & 0x7FF;
                    std::fprintf(stderr, "dumpdraw: %d vb%u 0x%08X size %u stride %u\n", k, i, va, size, stride);
                    if (va == 0 || stride == 0) continue;
                    const uint32_t rows = std::min<uint32_t>(size / stride, 64);
                    for (uint32_t v = 0; v < rows; ++v) {
                        std::string line;
                        char num[32];
                        for (uint32_t o = 0; o + 4 <= stride && o < 128; o += 4) {
                            std::snprintf(num, sizeof(num), "%.9g ", static_cast<double>(be_float(va + v * stride + o)));
                            line += num;
                        }
                        std::fprintf(stderr, "dumpdraw: %d vb%u[%u] %s\n", k, i, v, line.c_str());
                    }
                }
                for (int stage = 0; stage < 2; ++stage) {
                    const ShaderModule* sm = stage == 0 ? vs : ps;
                    for (uint32_t bank = 0; bank < 16; ++bank) {
                        if (!((sm->info.constant_bank_mask >> bank) & 1)) continue;
                        const uint32_t a = r((stage == 0 ? reg::SQ_ALU_CONST_CACHE_VS_0 : reg::SQ_ALU_CONST_CACHE_PS_0) + bank * 4) << 8;
                        if (a == 0 || !guest_memory_committed(a, 16 * 16)) continue;
                        for (uint32_t i = 0; i < 16; ++i) {
                            float f[4];
                            for (int q = 0; q < 4; ++q) f[q] = std::bit_cast<float>(*reinterpret_cast<const uint32_t*>(guest_pointer(a + i * 16 + q * 4)));
                            std::fprintf(stderr, "dumpdraw: %d %s kc(%u,%u) %.9g %.9g %.9g %.9g\n", k, stage == 0 ? "vs" : "ps",
                                         bank, i, static_cast<double>(f[0]), static_cast<double>(f[1]),
                                         static_cast<double>(f[2]), static_cast<double>(f[3]));
                        }
                    }
                }
                const auto raw = [&](const Image& img, const char* what, uint32_t address) {
                    uint32_t texel = 0;
                    VkImageAspectFlags aspect = VK_IMAGE_ASPECT_COLOR_BIT;
                    switch (img.format) {
                    case VK_FORMAT_R8_UNORM: texel = 1; break;
                    case VK_FORMAT_R16_SFLOAT: case VK_FORMAT_R16_UNORM: case VK_FORMAT_R8G8_UNORM: texel = 2; break;
                    case VK_FORMAT_R32_SFLOAT: case VK_FORMAT_R8G8B8A8_UNORM: case VK_FORMAT_R8G8B8A8_SRGB:
                    case VK_FORMAT_B8G8R8A8_UNORM: case VK_FORMAT_A2B10G10R10_UNORM_PACK32:
                    case VK_FORMAT_B10G11R11_UFLOAT_PACK32: case VK_FORMAT_R16G16_SFLOAT: texel = 4; break;
                    case VK_FORMAT_R16G16B16A16_SFLOAT: texel = 8; break;
                    case VK_FORMAT_D32_SFLOAT: case VK_FORMAT_D32_SFLOAT_S8_UINT: texel = 4; aspect = VK_IMAGE_ASPECT_DEPTH_BIT; break;
                    case VK_FORMAT_D16_UNORM: texel = 2; aspect = VK_IMAGE_ASPECT_DEPTH_BIT; break;
                    default: break;
                    }
                    std::fprintf(stderr, "dumpdraw: %d %s 0x%08X %ux%u layers %u vk format %d%s\n", k, what, address, img.width,
                                 img.height, img.layers, static_cast<int>(img.format), texel ? "" : " (not saved)");
                    if (texel == 0 || img.image == VK_NULL_HANDLE) return;
                    const VkDeviceSize bytes = VkDeviceSize{img.width} * img.height * texel * img.layers;
                    VkDeviceSize off = 0;
                    upload(bytes, 16, off);
                    end_rendering();
                    barrier();
                    VkBufferImageCopy rg{};
                    rg.bufferOffset = off;
                    rg.imageSubresource = {aspect, 0, 0, img.layers};
                    rg.imageExtent = {img.width, img.height, 1};
                    vkCmdCopyImageToBuffer(cmd(), img.image, VK_IMAGE_LAYOUT_GENERAL, ring_.buffer(), 1, &rg);
                    submit(true);
                    char name[160];
                    std::snprintf(name, sizeof(name), "/dumpdraw_%d_%s_%ux%u_f%d.raw", k, what, img.width, img.height,
                                  static_cast<int>(img.format));
                    if (FILE* f = std::fopen((std::string(dir) + name).c_str(), "wb")) {
                        std::fwrite(ring_.mapped() + off, 1, static_cast<size_t>(bytes), f);
                        std::fclose(f);
                    }
                };
                if (colors[0]) raw(colors[0]->image, "color0", colors[0]->address);
                if (depth) raw(depth->image, "depth", depth->address);
                for (uint32_t slot = 0; slot < abi::kTextureSlots; ++slot) {
                    if (!(ps->info.texture_mask & (1u << slot))) continue;
                    uint32_t w[7];
                    for (int i = 0; i < 7; ++i) w[i] = r(kResourceBase + ((resource::kPsTexture + slot) * resource::kWords + i) * 4);
                    const Texture* t = texture(w);
                    if (t == nullptr || (t->source == nullptr && t->image.layers == 1)) continue; // layered: all layers
                    char what[16];
                    std::snprintf(what, sizeof(what), "tex%u", slot);
                    raw(t->image, what, w[2] << 8);
                }
            }
        }
    }
'''

edit(d + "draw.cpp", "patch_dump_draw_at", [
    ("    if (writes_stream_out) stream_out_pending_ = true;" + NL,
     "    if (writes_stream_out) stream_out_pending_ = true;" + NL + BLOCK.lstrip(NL)),
])
