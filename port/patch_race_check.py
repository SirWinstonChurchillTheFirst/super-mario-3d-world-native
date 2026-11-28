#!/usr/bin/env python3
"""patch_race_check.py RUNTIME_SRC_DIR (.../runtime/src) : TOOL - does the CPU rewrite a draw's guest data before the GPU
reads it?

TTT2_RACE_CHECK=<pixel shader hash hex>: for each draw with that pixel shader, the vertex buffers 0-3 (up to 16 KiB each,
the bytes the draw can read) and the constant blocks its two shaders use (up to 4 KiB each) are copied twice: by the CPU
when the draw is recorded, and by the GPU right before the draw runs (a buffer copy from guest memory, into a readback
buffer). When that submission has finished the two are compared; every draw where they differ gets a line
"race: frame F <what> 0xADDR: N of M bytes changed (first at byte B)", and every 600 checked draws a summary
"race: N of M draws read guest data the CPU had changed since the draw was recorded".
The GPU reads vertex and constant data from guest memory when it runs the draw, not when the title issued it; if the
title already wrote the next frame's data there, the draw uses that. Costs one end of the rendering pass per checked
draw. Nothing happens when the switch is not set."""
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

BLOCK = r'''    { // port/patch_race_check.py: TTT2_RACE_CHECK=<ps hash>
        static const char* spec = std::getenv("TTT2_RACE_CHECK");
        if (spec != nullptr) {
            struct Part { const char* what; uint32_t address, size, offset; };
            struct Pending { uint64_t value = 0, frame = 0; std::vector<Part> parts; std::vector<uint8_t> cpu; bool used = false; };
            static constexpr uint32_t kSlots = 8, kSlotBytes = 128u << 10;
            static Buffer readback{};
            static Pending pending[kSlots];
            static uint32_t next = 0;
            static uint64_t checked = 0, raced = 0;
            static const uint64_t want = std::strtoull(spec, nullptr, 16);
            if (readback.buffer == VK_NULL_HANDLE) {
                readback = ctx_.create_buffer(VkDeviceSize{kSlots} * kSlotBytes, VK_BUFFER_USAGE_TRANSFER_DST_BIT,
                                              VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT |
                                                  VK_MEMORY_PROPERTY_HOST_CACHED_BIT);
            }
            uint64_t done = 0;
            vkGetSemaphoreCounterValue(ctx_.device, timeline_, &done);
            for (uint32_t s = 0; s < kSlots; ++s) { // finished checks
                Pending& p = pending[s];
                if (!p.used || p.value > done) continue;
                p.used = false;
                ++checked;
                bool any = false;
                for (const Part& part : p.parts) {
                    const uint8_t* gpu = readback.mapped + VkDeviceSize{s} * kSlotBytes + part.offset;
                    const uint8_t* cpu = p.cpu.data() + part.offset;
                    uint32_t n = 0, first = UINT32_MAX;
                    for (uint32_t i = 0; i < part.size; ++i) {
                        if (gpu[i] != cpu[i]) { ++n; first = std::min(first, i); }
                    }
                    if (n == 0) continue;
                    any = true;
                    std::fprintf(stderr, "race: frame %llu %s 0x%08X: %u of %u bytes changed (first at byte %u)\n",
                                 static_cast<unsigned long long>(p.frame), part.what, part.address, n, part.size, first);
                }
                if (any) ++raced;
                if (checked % 600 == 0) {
                    std::fprintf(stderr, "race: %llu of %llu draws read guest data the CPU had changed since the draw was recorded\n",
                                 static_cast<unsigned long long>(raced), static_cast<unsigned long long>(checked));
                }
            }
            uint64_t ph = 0;
            program(r(reg::SQ_PGM_START_PS) << 8, r(reg::SQ_PGM_START_PS + 4) << 3, ph);
            Pending& p = pending[next];
            if (ph == want && !p.used) {
                next = (next + 1) % kSlots;
                p.parts.clear();
                p.cpu.clear();
                static const char* const vb_names[4] = {"vb0", "vb1", "vb2", "vb3"};
                static const char* const cb_names[2][16] = {
                    {"vs kc0", "vs kc1", "vs kc2", "vs kc3", "vs kc4", "vs kc5", "vs kc6", "vs kc7", "vs kc8", "vs kc9", "vs kc10", "vs kc11", "vs kc12", "vs kc13", "vs kc14", "vs kc15"},
                    {"ps kc0", "ps kc1", "ps kc2", "ps kc3", "ps kc4", "ps kc5", "ps kc6", "ps kc7", "ps kc8", "ps kc9", "ps kc10", "ps kc11", "ps kc12", "ps kc13", "ps kc14", "ps kc15"}};
                uint32_t used = 0;
                const auto add = [&](const char* what, uint32_t address, uint32_t size) {
                    size = (std::min(size, kSlotBytes - used)) & ~3u;
                    if (address == 0 || size == 0 || !guest_memory_committed(address, size)) return;
                    p.parts.push_back({what, address, size, used});
                    p.cpu.resize(used + size);
                    std::memcpy(p.cpu.data() + used, guest_pointer(address), size);
                    used += (size + 15) & ~15u;
                };
                for (uint32_t i = 0; i < 4; ++i) {
                    const uint32_t base = kResourceBase + (resource::kVsAttrib + i) * resource::kWords * 4;
                    if ((r(base + 24) >> 30) != (resource::kTypeValidBuffer >> 30)) continue;
                    add(vb_names[i], r(base), std::min(r(base + 4) + 1, 16u << 10));
                }
                for (int stage = 0; stage < 2; ++stage) {
                    const ShaderModule* sm = stage == 0 ? vs : ps;
                    for (uint32_t bank = 0; bank < 16; ++bank) {
                        if (!((sm->info.constant_bank_mask >> bank) & 1)) continue;
                        const uint32_t a = r((stage == 0 ? reg::SQ_ALU_CONST_CACHE_VS_0 : reg::SQ_ALU_CONST_CACHE_PS_0) + bank * 4) << 8;
                        const uint32_t size = r((stage == 0 ? reg::SQ_ALU_CONST_BUFFER_SIZE_VS_0 : reg::SQ_ALU_CONST_BUFFER_SIZE_PS_0) + bank * 4) << 8;
                        add(cb_names[stage][bank], a, std::min(size, 4096u));
                    }
                }
                if (!p.parts.empty()) {
                    end_rendering();
                    for (const Part& part : p.parts) {
                        VkBuffer gb = VK_NULL_HANDLE;
                        VkDeviceSize go = 0;
                        if (!guest_.locate(part.address, part.size, gb, go)) continue;
                        VkBufferCopy bc{go, VkDeviceSize{next == 0 ? kSlots - 1 : next - 1} * kSlotBytes + part.offset, part.size};
                        vkCmdCopyBuffer(cmd(), gb, readback.buffer, 1, &bc);
                    }
                    barrier();
                    p.value = submitted_ + 1;
                    p.frame = frame_number_;
                    p.used = true;
                }
            }
        }
    }
'''

edit(d + "draw.cpp", "patch_race_check", [
    ("    // The rendering pass." + NL, BLOCK + "    // The rendering pass." + NL),
])
