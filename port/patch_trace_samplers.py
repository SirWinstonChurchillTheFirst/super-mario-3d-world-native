#!/usr/bin/env python3
"""patch_trace_samplers.py RUNTIME_SRC_DIR : a traced draw prints the sampler of every texture slot (tool, after patch_seq_ps.py).

A "trace:   ps tex3 ..." line is followed by "trace:   ps smp3 <w0> <w1> <w2> mag m min m mip m aniso a lod min..max
bias b base_level l": the three SQ_TEX_SAMPLER words and what the runtime decodes from them (filters, anisotropy,
LOD range and bias in levels) plus the resource's BASE_LEVEL. Made to check the suspicion "distant textures are sampled
without mip levels" in Mario Kart 8 (24 Nov 2026): the title itself asks for point mip filtering with a LOD bias of
-1 .. -2.5 and no anisotropy on most track materials; Cemu shows the same picture. No change of behaviour."""
import sys

path = sys.argv[1] + "/gpu/vulkan/draw.cpp"
s = open(path, encoding="utf-8").read()
if "patch_trace_samplers" in s:
    print("already applied: draw.cpp")
    sys.exit(0)

old = '''                             t && t->source ? "(render target)" : "(memory)");
'''
new = old + '''                { // port/patch_trace_samplers.py: the sampler of that slot
                    const uint32_t sb = base == resource::kVsTexture ? sampler::kVs : sampler::kPs;
                    uint32_t sw[3];
                    for (int i = 0; i < 3; ++i) sw[i] = r(kSamplerBase + ((sb + slot) * sampler::kWords + i) * 4);
                    std::fprintf(stderr, "trace:   %s smp%u %08X %08X %08X mag %u min %u mip %u aniso %u lod %.2f..%.2f bias %.2f base_level %u\\n",
                                 stage, slot, sw[0], sw[1], sw[2], (sw[0] >> 9) & 7, (sw[0] >> 12) & 7, (sw[0] >> 17) & 3,
                                 (sw[0] >> 19) & 7, (sw[1] & 0x3FF) / 64.0, ((sw[1] >> 10) & 0x3FF) / 64.0,
                                 (static_cast<int32_t>(sw[1]) >> 20) / 64.0, (w[4] >> 28) & 0xF);
                }
'''
assert s.count(old) == 1
s = s.replace(old, new)
open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched", path)
