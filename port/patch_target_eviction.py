#!/usr/bin/env python3
"""patch_target_eviction.py RUNTIME_SRC_DIR (.../runtime/src) : render targets nothing uses any more are freed.

Render targets were never freed. Mario Kart 8 on the console: 4250 -> 5020 targets in a 250 s race, GPU memory (GTT)
2.2 -> 3.1 of 3.7 GB, so a long session would run out of memory.

Every target now remembers the frame it was last used (looked up for a draw, clear or copy, read for a texture).
A few targets a frame are looked at in turn (256 at most, 16 checked closely); one unused for TTT2_TARGET_UNUSED_S
seconds of frames (default 30, 60 frames a second) is freed when its image holds nothing that is not elsewhere:
  - the CPU wrote its memory after the GPU last wrote it (textures read that memory then anyway), or
  - a newer target overlaps its memory (on the console the GPU wrote over it there), or
  - it is a write-back target: its contents are in guest memory (see Renderer::queue_write_back).
Never one with a write-back still queued, one carried by the interpolation, or one in the open rendering pass.
At most 4 a frame. A freed target leaves the indexes at once; its image is destroyed only once the GPU is past the
submission being recorded (8 a frame at most), as for textures. Textures whose contents came from it load again from
memory (or a newer target) at their next use, as a texture made new would. The slice caches look their keys up again.
Image memory goes back to the image pool (patch_image_pool.py), whose blocks the next targets reuse.
TTT2_TARGET_EVICT=0: never freed (old behaviour). The statistics line shows the targets' memory and how many went."""
import sys

NL = "\n"


def edit(path, marker, pairs):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        print("already applied:", path)
        return
    for item in pairs:
        old, new = item[0], item[1]
        count = item[2] if len(item) > 2 else 1
        assert s.count(old) == count, "pattern not found %d times in %s: %r" % (count, path, old[:80])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


d = sys.argv[1] + "/gpu/vulkan/"

edit(d + "renderer.h", "patch_target_eviction", [
    ("    Image start_copy, end_copy;" + NL + "};" + NL,
     "    Image start_copy, end_copy;" + NL +
     "    uint64_t used_frame = 0; // frame_number_ of its last use (port/patch_target_eviction.py)" + NL +
     "    uint64_t bytes = 0;      // its image's memory, 0: not measured yet" + NL +
     "};" + NL),
    ("    void evict_textures();" + NL,
     "    void evict_textures();" + NL +
     "    // port/patch_target_eviction.py: targets unused for a while whose contents are elsewhere, freed a few a frame;" + NL +
     "    // their images destroyed once the GPU passed the submission value beside them." + NL +
     "    void evict_targets();" + NL +
     "    bool target_dispensable(const Target& t) const;" + NL +
     "    std::deque<std::pair<uint64_t, std::unique_ptr<Target>>> retired_targets_;" + NL +
     "    size_t evict_cursor_ = 0;" + NL +
     "    uint64_t target_bytes_ = 0, sweep_bytes_ = 0, targets_freed_ = 0;" + NL),
])

IMPL = r'''
// ------------------------------------------------------------ eviction (port/patch_target_eviction.py)

// Nothing is lost when the target goes: its memory holds newer data, or its own (written back).
bool Renderer::target_dispensable(const Target& t) const {
    if (t.overwritten > t.written) return true; // the CPU wrote its memory since: textures read that memory anyway
    if (t.write_back && std::getenv("TTT2_NO_WRITEBACK") == nullptr && std::getenv("TTT2_WRITEBACK_RANGE") == nullptr) {
        return true; // every GPU write of it was tiled into guest memory
    }
    // A newer target over (part of) its memory: on the console the GPU wrote over it there.
    const uint32_t from = t.address > max_target_span_ ? t.address - max_target_span_ : 0;
    for (auto it = targets_sorted_.lower_bound(from); it != targets_sorted_.end() && it->first < t.end; ++it) {
        for (const Target* u : it->second) {
            if (u != &t && u->end > t.address && u->address < t.end && u->written > t.written) return true;
        }
    }
    return false;
}

void Renderer::evict_targets() {
    static const bool on = [] {
        const char* v = std::getenv("TTT2_TARGET_EVICT");
        return v == nullptr || *v != '0';
    }();
    static const uint64_t unused_frames = [] {
        const char* v = std::getenv("TTT2_TARGET_UNUSED_S");
        return uint64_t(v ? std::max(1, std::atoi(v)) : 30) * 60;
    }();
    // The images of freed targets, once the GPU is past every submission that may use them.
    if (!retired_targets_.empty()) {
        uint64_t done = 0;
        VK_CHECK(vkGetSemaphoreCounterValue(ctx_.device, timeline_, &done));
        for (uint32_t n = 0; n < 8 && !retired_targets_.empty() && retired_targets_.front().first <= done; ++n) {
            Target& t = *retired_targets_.front().second;
            destroy_image(t.image);
            destroy_image(t.start_copy);
            destroy_image(t.end_copy);
            retired_targets_.pop_front();
        }
    }
    if (!on || targets_.empty()) return;
    Target* gone[4];
    uint32_t freed = 0, looked = 0, checked = 0;
    while (looked < 256 && checked < 16 && freed < 4 && !targets_.empty()) {
        if (evict_cursor_ >= targets_.size()) { // a round through all of them: their memory
            evict_cursor_ = 0;
            target_bytes_ = sweep_bytes_;
            sweep_bytes_ = 0;
        }
        Target* t = targets_[evict_cursor_].get();
        ++looked;
        if (t->bytes == 0 && t->image.image != VK_NULL_HANDLE) {
            VkMemoryRequirements req;
            vkGetImageMemoryRequirements(ctx_.device, t->image.image, &req);
            t->bytes = req.size;
        }
        bool keep = frame_number_ - t->used_frame < unused_frames || t->write_back_queued || t->carried;
        if (!keep && rendering_) {
            keep = t == pass_depth_ || std::find(pass_colors_.begin(), pass_colors_.end(), t) != pass_colors_.end();
        }
        if (!keep) {
            ++checked;
            keep = !target_dispensable(*t);
        }
        if (keep) {
            sweep_bytes_ += t->bytes;
            ++evict_cursor_;
            continue;
        }
        if (std::getenv("TTT2_TRACE_TARGETS")) {
            std::fprintf(stderr, "ttt2: gpu: freed %s target 0x%08X fmt 0x%03X %ux%u (unused for %llu frames)\n",
                         t->depth ? "depth" : "color", t->address, t->format, t->pitch, t->height,
                         static_cast<unsigned long long>(frame_number_ - t->used_frame));
        }
        const auto drop = [&](auto& index) {
            const auto it = index.find(t->address);
            if (it == index.end()) return;
            std::erase(it->second, t);
            if (it->second.empty()) index.erase(it);
        };
        drop(targets_by_address_);
        drop(targets_sorted_);
        gone[freed++] = t;
        // The batch being recorded is the last that could use it.
        retired_targets_.emplace_back(submitted_ + 1, std::move(targets_[evict_cursor_]));
        targets_[evict_cursor_] = std::move(targets_.back());
        targets_.pop_back();
    }
    if (freed == 0) return;
    targets_freed_ += freed;
    ++target_generation_; // the slice caches look their keys up again (port/patch_slice_cache.py)
    for (auto& [key, tex] : textures_) {
        for (uint32_t i = 0; i < freed; ++i) {
            if (tex->source == gone[i]) { // loads again at its next use, as a new texture would
                tex->source = nullptr;
                tex->dirty = true;
                tex->hash = 0;
            }
            if (tex->slice_stride != 0) {
                for (const Target*& s : tex->slice_level_source) s = s == gone[i] ? nullptr : s;
                for (const Target*& s : tex->slice_found) s = s == gone[i] ? nullptr : s;
            }
        }
    }
}
'''

edit(d + "targets.cpp", "patch_target_eviction", [
    ("        if (best == nullptr || t->written > best->written) best = t;" + NL + "    }" + NL + "    return best;" + NL,
     "        if (best == nullptr || t->written > best->written) best = t;" + NL + "    }" + NL +
     "    if (best != nullptr) best->used_frame = frame_number_; // port/patch_target_eviction.py" + NL +
     "    return best;" + NL),
    ("                t->base_reg = base_reg;" + NL + "                return t;" + NL,
     "                t->base_reg = base_reg;" + NL +
     "                t->used_frame = frame_number_; // port/patch_target_eviction.py" + NL +
     "                return t;" + NL),
    ("            if (t->depth && t->address == address && t->format == format && t->pitch == pitch && t->height == height) {" + NL +
     "                return t;" + NL,
     "            if (t->depth && t->address == address && t->format == format && t->pitch == pitch && t->height == height) {" + NL +
     "                t->used_frame = frame_number_; // port/patch_target_eviction.py" + NL +
     "                return t;" + NL),
    ("    t->written = stamp();" + NL + "    t->written_frame = frame_number_;" + NL,
     "    t->written = stamp();" + NL + "    t->written_frame = frame_number_;" + NL +
     "    t->used_frame = frame_number_; // port/patch_target_eviction.py" + NL, 2),
    ("            ct->written = stamp();" + NL + "            note_target_written(ct);" + NL,
     "            ct->written = stamp();" + NL + "            ct->used_frame = frame_number_; // port/patch_target_eviction.py" + NL +
     "            note_target_written(ct);" + NL),
    ("    t.scale = scale;" + NL + "    t.written = stamp();" + NL + "}" + NL,
     "    t.scale = scale;" + NL + "    t.written = stamp();" + NL + "    t.bytes = 0; // port/patch_target_eviction.py: measured again" + NL + "}" + NL),
    (NL + "} // namespace cafe::gpu::vk" + NL,
     IMPL + NL + "} // namespace cafe::gpu::vk" + NL),
])

edit(d + "textures.cpp", "patch_target_eviction", [
    ("                t.slice_found[size_t{level} * slice_count + z] = src;" + NL,
     "                t.slice_found[size_t{level} * slice_count + z] = src;" + NL +
     "                const_cast<Target*>(src)->used_frame = frame_number_; // port/patch_target_eviction.py" + NL),
    ("                slices[z] = other;" + NL,
     "                slices[z] = other;" + NL +
     "                const_cast<Target*>(other)->used_frame = frame_number_; // port/patch_target_eviction.py" + NL),
])

edit(d + "renderer.cpp", "patch_target_eviction", [
    ("    ++frame_number_;" + NL + "    ++frames_;" + NL,
     "    ++frame_number_;" + NL + "    ++frames_;" + NL + "    evict_targets(); // port/patch_target_eviction.py" + NL),
    ("%zu targets, %zu textures, ",
     "%zu targets (%llu MB, %llu freed), %zu textures, "),
    ("double(skipped_draws_) / std::max<uint64_t>(frames_, 1), targets_.size(), textures_.size(),",
     "double(skipped_draws_) / std::max<uint64_t>(frames_, 1), targets_.size(),"
     " static_cast<unsigned long long>(target_bytes_ >> 20), static_cast<unsigned long long>(targets_freed_), textures_.size(),"),
])
