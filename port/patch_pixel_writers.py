#!/usr/bin/env python3
"""patch_pixel_writers.py RUNTIME_SRC_DIR (.../runtime/src) : TOOL - which draws of one frame change one screen spot.

TTT2_PIXEL_WRITERS=<seconds>,<fx>,<fy>: in the first frame after <seconds> (renderer clock), after every draw one texel
of its colour target 0 and of its depth target (at fx,fy = fractions of the target's size) is copied on the GPU into a
readback buffer (no waiting per draw, only the rendering pass is ended). At the start of the next frame the results are
read and every draw that changed the texel of its target is printed:
  "pixel: draw N vs <hash> ps <hash> color 0xADDR fmt 0xF WxH: before -> after" (raw bytes as hex)
  "pixel: draw N ... depth 0xADDR: before -> after" (float).
A light way (one frame, a few KB, no pictures) to find the draw that paints a wrong spot, e.g. on the console where full
frame traces are not wanted. Nothing happens when the switch is not set."""
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

BLOCK = r'''    { // port/patch_pixel_writers.py: TTT2_PIXEL_WRITERS=<seconds>,<fx>,<fy>
        static const char* spec = std::getenv("TTT2_PIXEL_WRITERS");
        if (spec != nullptr) {
            struct Rec { uint32_t draw; uint64_t vs, ps; uint32_t address, format, w, h; bool depth; uint32_t clip, zctl, alpha, tmask, count; };
            static constexpr uint32_t kMax = 4096;
            static Buffer rb{};
            static std::vector<Rec> recs;
            static uint64_t frame = UINT64_MAX;
            static int state = 0; // 0 waiting, 1 recording, 2 done
            static uint32_t n = 0;
            static const double at = std::atof(spec);
            static float fx = 0.5f, fy = 0.5f;
            static const auto start = std::chrono::steady_clock::now();
            if (state == 0 && std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() >= at) {
                const char* c = std::strchr(spec, ',');
                if (c) { fx = std::strtof(c + 1, nullptr); c = std::strchr(c + 1, ','); }
                if (c) fy = std::strtof(c + 1, nullptr);
                rb = ctx_.create_buffer(VkDeviceSize{kMax} * 16, VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                                        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT |
                                            VK_MEMORY_PROPERTY_HOST_CACHED_BIT);
                std::memset(rb.mapped, 0, kMax * 16);
                state = 1;
                frame = frame_number_ + 1; // a whole frame: from the next one
            }
            if (state == 1 && frame_number_ > frame) { // the frame is over: read and print
                submit(true);
                state = 2;
                std::map<std::pair<uint32_t, bool>, std::array<uint8_t, 16>> last;
                std::fprintf(stderr, "pixel: frame %llu, %u draws, spot %.3f,%.3f\n", static_cast<unsigned long long>(frame), n,
                             static_cast<double>(fx), static_cast<double>(fy));
                for (uint32_t i = 0; i < recs.size(); ++i) {
                    const Rec& rc = recs[i];
                    std::array<uint8_t, 16> v{};
                    std::memcpy(v.data(), rb.mapped + VkDeviceSize{i} * 16, 16);
                    const auto key = std::make_pair(rc.address, rc.depth);
                    const auto it = last.find(key);
                    if (it != last.end() && it->second == v) continue;
                    char before[40] = "?", after[40];
                    if (rc.depth) {
                        float f;
                        std::memcpy(&f, v.data(), 4);
                        std::snprintf(after, sizeof(after), "%.7f", static_cast<double>(f));
                        if (it != last.end()) { std::memcpy(&f, it->second.data(), 4); std::snprintf(before, sizeof(before), "%.7f", static_cast<double>(f)); }
                    } else {
                        std::snprintf(after, sizeof(after), "%02x%02x%02x%02x %02x%02x%02x%02x", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
                        if (it != last.end()) {
                            const auto& b = it->second;
                            std::snprintf(before, sizeof(before), "%02x%02x%02x%02x %02x%02x%02x%02x", b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]);
                        }
                    }
                    std::fprintf(stderr, "pixel: draw %u vs %016llx ps %016llx %s 0x%08X fmt 0x%03X %ux%u: %s -> %s (count %u clip 0x%08X zctl 0x%08X alpha 0x%X tmask 0x%X)\n", rc.draw,
                                 static_cast<unsigned long long>(rc.vs), static_cast<unsigned long long>(rc.ps),
                                 rc.depth ? "depth" : "color", rc.address, rc.format, rc.w, rc.h, before, after, rc.count, rc.clip, rc.zctl, rc.alpha, rc.tmask);
                    last[key] = v;
                }
            }
            if (state == 1 && frame_number_ == frame && recs.size() + 9 <= kMax) {
                ++n;
                uint64_t vh = 0, ph = 0;
                program(r(reg::SQ_PGM_START_VS) << 8, r(reg::SQ_PGM_START_VS + 4) << 3, vh);
                program(r(reg::SQ_PGM_START_PS) << 8, r(reg::SQ_PGM_START_PS + 4) << 3, ph);
                end_rendering();
                const auto copy = [&](const Target* t, bool is_depth) {
                    if (t == nullptr || t->image.image == VK_NULL_HANDLE) return;
                    const Image& img = t->image;
                    VkBufferImageCopy rg{};
                    rg.bufferOffset = VkDeviceSize{recs.size()} * 16;
                    rg.imageSubresource = {is_depth ? VkImageAspectFlags{VK_IMAGE_ASPECT_DEPTH_BIT} : VkImageAspectFlags{VK_IMAGE_ASPECT_COLOR_BIT}, 0, 0, 1};
                    rg.imageOffset = {static_cast<int32_t>(fx * img.width), static_cast<int32_t>(fy * img.height), 0};
                    rg.imageExtent = {1, 1, 1};
                    if (is_depth && img.format != VK_FORMAT_D32_SFLOAT && img.format != VK_FORMAT_D32_SFLOAT_S8_UINT) return;
                    vkCmdCopyImageToBuffer(cmd(), img.image, VK_IMAGE_LAYOUT_GENERAL, rb.buffer, 1, &rg);
                    recs.push_back({n, vh, ph, t->address, t->format, img.width, img.height, is_depth, r(reg::PA_CL_CLIP_CNTL),
                                     r(reg::DB_DEPTH_CONTROL), r(reg::SX_ALPHA_TEST_CONTROL), r(reg::CB_TARGET_MASK), d.count});
                };
                for (uint32_t ci = 0; ci < 8; ++ci) copy(colors[ci], false); // every render target of the draw
                copy(depth, true);
                barrier();
            }
        }
    }
'''

edit(d + "draw.cpp", "patch_pixel_writers", [
    ("    if (writes_stream_out) stream_out_pending_ = true;" + NL,
     "    if (writes_stream_out) stream_out_pending_ = true;" + NL + BLOCK),
])
