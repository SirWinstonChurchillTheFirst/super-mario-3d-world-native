#!/usr/bin/env python3
"""patch_texture_retention.py RUNTIME_SRC_DIR (.../runtime/src) : unused textures are kept while memory allows.

evict_textures (every 10 s) destroyed every texture not bound for 600 frames (10 s). Mario Kart 8 binds a set of
~450 course textures only every so often: the texture count went 900 -> 413 -> 900 from one 10 s window to the next,
and each time they came back the draw thread made their images again, hashed and uploaded them: a 206-texture burst
took 135 ms in one frame on the console (images 66 ms, uploads 19 ms, binds 31 ms) - the hitches in the races.

Now a texture unused for 10 s is only destroyed while the textures' memory is over a budget (oldest unused first,
TTT2_TEXTURE_BUDGET_MB, default 768), or when it has been unused for 5 minutes."""
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

edit(d + "renderer.h", "patch_texture_retention", [
    ("    uint64_t used_frame = 0; // frame_number_ of the last draw that bound it (evict_textures)" + NL,
     "    uint64_t used_frame = 0; // frame_number_ of the last draw that bound it (evict_textures)" + NL +
     "    uint64_t bytes = 0;      // its image's memory (port/patch_texture_retention.py)" + NL),
])

edit(d + "textures.cpp", "patch_texture_retention", [
    ("    VkImageViewCreateInfo vci{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};" + NL +
     "    vci.image = t.image.image;" + NL,
     "    { // port/patch_texture_retention.py" + NL +
     "        VkMemoryRequirements req;" + NL +
     "        vkGetImageMemoryRequirements(ctx_.device, t.image.image, &req);" + NL +
     "        t.bytes = req.size;" + NL +
     "    }" + NL +
     "    VkImageViewCreateInfo vci{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};" + NL +
     "    vci.image = t.image.image;" + NL),
    ("    constexpr uint64_t kUnusedFrames = 600;" + NL +
     "    const uint64_t value = submitted_ + 1; // the batch being recorded may still bind them" + NL +
     "    for (auto it = textures_.begin(); it != textures_.end();) {" + NL +
     "        Texture* t = it->second.get();" + NL +
     "        if (frame_number_ - t->used_frame < kUnusedFrames) {" + NL +
     "            ++it;" + NL +
     "            continue;" + NL +
     "        }" + NL,
     "    constexpr uint64_t kUnusedFrames = 600;" + NL +
     "    // port/patch_texture_retention.py: unused ones go only over the budget (oldest first) or after 5 minutes." + NL +
     "    constexpr uint64_t kForgottenFrames = 60 * 300;" + NL +
     "    static const uint64_t budget = [] {" + NL +
     "        const char* v = std::getenv(\"TTT2_TEXTURE_BUDGET_MB\");" + NL +
     "        return uint64_t(v ? std::max(0, std::atoi(v)) : 768) << 20;" + NL +
     "    }();" + NL +
     "    uint64_t total = 0;" + NL +
     "    std::vector<std::pair<uint64_t, uint64_t>> unused; // used_frame, bytes" + NL +
     "    for (const auto& [key, t] : textures_) {" + NL +
     "        total += t->bytes;" + NL +
     "        if (frame_number_ - t->used_frame >= kUnusedFrames) unused.push_back({t->used_frame, t->bytes});" + NL +
     "    }" + NL +
     "    std::sort(unused.begin(), unused.end());" + NL +
     "    uint64_t evict_before = frame_number_ >= kForgottenFrames ? frame_number_ - kForgottenFrames : 0; // used_frame below: goes" + NL +
     "    for (const auto& [used, bytes] : unused) {" + NL +
     "        if (total <= budget) break;" + NL +
     "        total -= bytes;" + NL +
     "        evict_before = std::max(evict_before, used + 1);" + NL +
     "    }" + NL +
     "    const uint64_t value = submitted_ + 1; // the batch being recorded may still bind them" + NL +
     "    for (auto it = textures_.begin(); it != textures_.end();) {" + NL +
     "        Texture* t = it->second.get();" + NL +
     "        if (frame_number_ - t->used_frame < kUnusedFrames || t->used_frame >= evict_before) {" + NL +
     "            ++it;" + NL +
     "            continue;" + NL +
     "        }" + NL),
])
