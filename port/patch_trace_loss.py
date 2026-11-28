#!/usr/bin/env python3
"""patch_trace_loss.py RUNTIME_SRC_DIR (.../runtime/src) : measuring tool TTT2_TRACE_LOSS=1 (after patch_target_evict_layers.py).

Prints "loss:" lines when a texture has to take its contents from somewhere else than before because a render target
was freed by the target eviction (port/patch_target_eviction.py):
  loss: freed ...                     every freed target that some texture used as its source (with the reason)
  loss: texture ... from guest memory a texture whose level-0 target was freed now loads guest memory
  loss: texture ... slice z missing   a layer of an array/cube/3D texture has no slice target any more (was freed)
  loss: write-back skipped ...        a freed "written back" target whose last write-back was skipped by the guard
Costs nothing without the switch (one static bool)."""
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

edit(d + "renderer.h", "patch_trace_loss", [
    ("    uint64_t target_bytes_ = 0, sweep_bytes_ = 0, targets_freed_ = 0;" + NL,
     "    uint64_t target_bytes_ = 0, sweep_bytes_ = 0, targets_freed_ = 0;" + NL +
     "    // port/patch_trace_loss.py (TTT2_TRACE_LOSS=1): freed targets by address, and places whose last write-back was skipped" + NL +
     "    struct FreedTarget {" + NL +
     "        char why = 0;" + NL +
     "        bool layered = false;" + NL +
     "        uint32_t format = 0, pitch = 0, height = 0;" + NL +
     "        uint64_t frame = 0;" + NL +
     "    };" + NL +
     "    std::unordered_map<uint32_t, FreedTarget> freed_log_;" + NL +
     "    std::unordered_map<uint32_t, uint32_t> write_back_skips_; // under write_back_mutex_" + NL +
     "    static bool trace_loss() {" + NL +
     "        static const bool on = std::getenv(\"TTT2_TRACE_LOSS\") != nullptr;" + NL +
     "        return on;" + NL +
     "    }" + NL),
])

edit(d + "targets.cpp", "patch_trace_loss", [
    # a new target at a freed place: the old entry is history
    ("    targets_by_address_[t->address].push_back(t.get()); // port/patch_target_index.py" + NL +
     "    targets_sorted_[t->address].push_back(t.get());" + NL +
     "    ++target_generation_; // port/patch_slice_cache.py" + NL +
     "    max_target_span_ = std::max(max_target_span_, t->end - t->address);" + NL +
     "    if (static const bool reload",
     "    targets_by_address_[t->address].push_back(t.get()); // port/patch_target_index.py" + NL +
     "    targets_sorted_[t->address].push_back(t.get());" + NL +
     "    ++target_generation_; // port/patch_slice_cache.py" + NL +
     "    max_target_span_ = std::max(max_target_span_, t->end - t->address);" + NL +
     "    if (trace_loss()) freed_log_.erase(t->address); // port/patch_trace_loss.py" + NL +
     "    if (static const bool reload"),
    # skipped / done write-backs
    ("            std::lock_guard lock(write_back_mutex_);" + NL +
     "            write_back_free_.push_back(w.staging);" + NL +
     "            continue;" + NL,
     "            std::lock_guard lock(write_back_mutex_);" + NL +
     "            write_back_free_.push_back(w.staging);" + NL +
     "            if (trace_loss()) ++write_back_skips_[w.address]; // port/patch_trace_loss.py" + NL +
     "            continue;" + NL),
    ("        add_stat(kStatWriteBackBytes, uint64_t{w.pitch} * w.height * w.bpp / 8);" + NL +
     "        std::lock_guard lock(write_back_mutex_);" + NL +
     "        write_back_free_.push_back(w.staging);" + NL,
     "        add_stat(kStatWriteBackBytes, uint64_t{w.pitch} * w.height * w.bpp / 8);" + NL +
     "        std::lock_guard lock(write_back_mutex_);" + NL +
     "        write_back_free_.push_back(w.staging);" + NL +
     "        if (trace_loss()) write_back_skips_.erase(w.address); // port/patch_trace_loss.py" + NL),
    # the freed target
    ("        const auto drop = [&](auto& index) {" + NL +
     "            const auto it = index.find(t->address);" + NL,
     "        if (trace_loss()) { // port/patch_trace_loss.py" + NL +
     "            const char* why = t->overwritten > t->written ? \"cpu\" : t->write_back && !t->layered ? \"writeback\" : \"overlap\";" + NL +
     "            freed_log_[t->address] = {*why, t->layered, t->format, t->pitch, t->height, frame_number_};" + NL +
     "            uint32_t users = 0;" + NL +
     "            for (auto& [key, tex] : textures_) {" + NL +
     "                bool uses = tex->source == t;" + NL +
     "                for (const Target* s : tex->slice_found) uses = uses || s == t;" + NL +
     "                if (!uses) continue;" + NL +
     "                ++users;" + NL +
     "                std::fprintf(stderr, \"loss: freed %s target 0x%08X fmt 0x%03X %ux%u%s (%s, written %llu frames ago) was the source of texture 0x%08X \"" + NL +
     "                             \"(used %llu frames ago)\\n\"," + NL +
     "                             t->depth ? \"depth\" : \"color\", t->address, t->format, t->pitch, t->height, t->layered ? \" layered\" : \"\", why," + NL +
     "                             static_cast<unsigned long long>(frame_number_ - t->written_frame), tex->words[2] << 8," + NL +
     "                             static_cast<unsigned long long>(frame_number_ - tex->used_frame));" + NL +
     "            }" + NL +
     "            if (*why == 'w') {" + NL +
     "                std::lock_guard lock(write_back_mutex_);" + NL +
     "                if (const auto it = write_back_skips_.find(t->address); it != write_back_skips_.end()) {" + NL +
     "                    std::fprintf(stderr, \"loss: write-back skipped %u times for freed target 0x%08X fmt 0x%03X %ux%u (%u textures use it): \"" + NL +
     "                                 \"its contents are NOT in guest memory\\n\", it->second, t->address, t->format, t->pitch, t->height, users);" + NL +
     "                }" + NL +
     "            }" + NL +
     "        }" + NL +
     "        const auto drop = [&](auto& index) {" + NL +
     "            const auto it = index.find(t->address);" + NL),
])

edit(d + "textures.cpp", "patch_trace_loss", [
    # level 0 has no target (any more)
    ("        const Target* src = find_target(address, 0, false);" + NL +
     "        if (src == nullptr || src->written <= src->overwritten) {" + NL,
     "        const Target* src = find_target(address, 0, false);" + NL +
     "        if (trace_loss() && src == nullptr) { // port/patch_trace_loss.py" + NL +
     "            if (const auto fl = freed_log_.find(address); fl != freed_log_.end()) {" + NL +
     "                static std::set<uint64_t> said;" + NL +
     "                if (said.insert(uint64_t{address} << 32 | static_cast<uint32_t>(fl->second.frame)).second) {" + NL +
     "                    std::fprintf(stderr, \"loss: texture 0x%08X fmt 0x%03X %ux%ux%u dim %u level %u from guest memory: its target (fmt 0x%03X %ux%u%s) \"" + NL +
     "                                 \"was freed %llu frames ago (%c)%s\\n\"," + NL +
     "                                 uint32_t{s.image}, r.format, r.width, r.height, r.depth, r.dim, level, fl->second.format, fl->second.pitch," + NL +
     "                                 fl->second.height, fl->second.layered ? \" layered\" : \"\"," + NL +
     "                                 static_cast<unsigned long long>(frame_number_ - fl->second.frame), fl->second.why," + NL +
     "                                 t.loaded == 0 ? \" [new texture]\" : \"\");" + NL +
     "                }" + NL +
     "            }" + NL +
     "        }" + NL +
     "        if (src == nullptr || src->written <= src->overwritten) {" + NL),
    # a slice without its target
    ("                for (uint32_t z = 1; z < slice_count; ++z) {" + NL +
     "                    const auto it = targets_by_address_.find(s0->address + z * step);" + NL +
     "                    keys[z] = it == targets_by_address_.end() ? nullptr : &it->second;" + NL,
     "                for (uint32_t z = 1; z < slice_count; ++z) {" + NL +
     "                    const auto it = targets_by_address_.find(s0->address + z * step);" + NL +
     "                    keys[z] = it == targets_by_address_.end() ? nullptr : &it->second;" + NL +
     "                    if (trace_loss() && keys[z] == nullptr) { // port/patch_trace_loss.py" + NL +
     "                        if (const auto fl = freed_log_.find(s0->address + z * step); fl != freed_log_.end()) {" + NL +
     "                            static std::set<uint64_t> said;" + NL +
     "                            if (said.insert(uint64_t{s0->address + z * step} << 32 | static_cast<uint32_t>(fl->second.frame)).second) {" + NL +
     "                                std::fprintf(stderr, \"loss: texture 0x%08X fmt 0x%03X %ux%ux%u dim %u level %u slice %u missing: its slice target \"" + NL +
     "                                             \"0x%08X was freed %llu frames ago (%c)%s\\n\"," + NL +
     "                                             uint32_t{s.image}, r.format, r.width, r.height, r.depth, r.dim, level, z, s0->address + z * step," + NL +
     "                                             static_cast<unsigned long long>(frame_number_ - fl->second.frame), fl->second.why," + NL +
     "                                             t.loaded == 0 ? \" [new texture]\" : \"\");" + NL +
     "                            }" + NL +
     "                        }" + NL +
     "                    }" + NL),
])
