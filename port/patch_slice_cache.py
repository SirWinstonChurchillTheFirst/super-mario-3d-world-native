#!/usr/bin/env python3
"""patch_slice_cache.py RUNTIME_SRC_DIR (.../runtime/src) : the slice-target lookup of a texture read from render targets,
cached per texture.

load_texture_from_targets (patch_slice_targets.py, patch_slice_levels.py, patch_compressed_slices.py) looked up the slice
target of every slice z of every level with find_target (a hash lookup) on EVERY bind of a 3D / array / cube texture whose
level 0 comes from a target, and zeroed a 7 KB table (slice_sources[14][64]) on every bind of any texture from targets.
Mario Kart 8's reflection cube array (48 layers) bound ~500 times a frame made that ~94 lookups per bind: texture binds
cost 1.5-1.8 us instead of 1.0-1.1 us on the console, 37 instead of 40 fps in the heaviest race scenes.

Now each texture keeps, per level, which target lists sit at its slice keys (pointers into targets_by_address_, whose
entries are never removed, so they stay valid) and looks them up again only when a target was created since
(target_generation_) or the level's own source target changed. A bind then only walks the cached lists, picking the
newest target at each key as find_target does (same result). The per-slice table lives in the texture and exists only
for textures with slices."""
import sys

NL = "\n"


def edit(path, marker, pairs):
    s = open(path, encoding="utf-8").read()
    if marker in s:
        print("already applied:", path)
        return
    for old, new in pairs:
        assert s.count(old) == 1, "pattern not found (or not unique) in %s: %r" % (path, old[:70])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


d = sys.argv[1] + "/gpu/vulkan/"

edit(d + "renderer.h", "patch_slice_cache", [
    ("    uint64_t replacement_generation = 0;" + NL +
     "    bool rgba = false;" + NL +
     "};" + NL,
     "    uint64_t replacement_generation = 0;" + NL +
     "    bool rgba = false;" + NL +
     "    // port/patch_slice_cache.py: per (level, slice) the targets at the slice's key (null: none), looked up for" + NL +
     "    // slice_generation and the level's source target slice_level_source; slice_found = this load's picks." + NL +
     "    uint64_t slice_generation = 0;" + NL +
     "    uint32_t slice_stride = 0;" + NL +
     "    std::array<const Target*, 14> slice_level_source{};" + NL +
     "    std::vector<const std::vector<Target*>*> slice_keys;" + NL +
     "    std::vector<const Target*> slice_found;" + NL +
     "};" + NL),
    ("    uint32_t max_target_span_ = 0;" + NL,
     "    uint32_t max_target_span_ = 0;" + NL +
     "    uint64_t target_generation_ = 1; // port/patch_slice_cache.py: +1 for every target made" + NL),
])

edit(d + "targets.cpp", "patch_slice_cache", [
    ("    targets_by_address_[t->address].push_back(t.get()); // port/patch_target_index.py" + NL +
     "    targets_sorted_[t->address].push_back(t.get());" + NL +
     "    max_target_span_ = std::max(max_target_span_, t->end - t->address);" + NL +
     "    if (static const bool reload",
     "    targets_by_address_[t->address].push_back(t.get()); // port/patch_target_index.py" + NL +
     "    targets_sorted_[t->address].push_back(t.get());" + NL +
     "    ++target_generation_; // port/patch_slice_cache.py" + NL +
     "    max_target_span_ = std::max(max_target_span_, t->end - t->address);" + NL +
     "    if (static const bool reload"),
    ("    targets_by_address_[t->address].push_back(t.get()); // port/patch_target_index.py" + NL +
     "    targets_sorted_[t->address].push_back(t.get());" + NL +
     "    max_target_span_ = std::max(max_target_span_, t->end - t->address);" + NL +
     "    targets_.push_back(std::move(t));" + NL,
     "    targets_by_address_[t->address].push_back(t.get()); // port/patch_target_index.py" + NL +
     "    targets_sorted_[t->address].push_back(t.get());" + NL +
     "    ++target_generation_; // port/patch_slice_cache.py" + NL +
     "    max_target_span_ = std::max(max_target_span_, t->end - t->address);" + NL +
     "    targets_.push_back(std::move(t));" + NL),
])

OLD_SCAN = (
    "    const Target* slice_sources[14][64] = {}; // port/patch_slice_levels.py: per level" + NL +
    "    // port/patch_compressed_slices.py: compressed textures too (the slice targets hold their blocks as texels)" + NL +
    "    const uint32_t slice_count = r.depth > 1 && slice_targets_enabled() ? std::min(r.depth, 64u) : 0;" + NL +
    "    for (uint32_t level = 0; slice_count > 1 && level < levels; ++level) {" + NL +
    "        const Target* s0 = sources[level];" + NL +
    "        if (s0 == nullptr) continue;" + NL +
    "        const uint32_t step = slice_key_bytes(s0->pitch, s0->height, std::max(1u, f.bytes), s0->tile_mode);" + NL +
    "        for (uint32_t z = 1; z < slice_count; ++z) {" + NL +
    "            const Target* src = find_target(s0->address + z * step, 0, false);" + NL +
    "            if (src == nullptr || src->written <= src->overwritten || src->pitch != s0->pitch ||" + NL +
    "                src->height != s0->height || src->scale != s0->scale || color_format(src->format).bytes != f.bytes) {" + NL +
    "                continue;" + NL +
    "            }" + NL +
    "            slice_sources[level][z] = src;" + NL +
    "            note_target_read(src);" + NL +
    "            newest = std::max(newest, src->written);" + NL +
    "        }" + NL +
    "    }" + NL)
NEW_SCAN = (
    "    // port/patch_slice_levels.py: per level; port/patch_slice_cache.py: in the texture, only for textures with slices" + NL +
    "    // port/patch_compressed_slices.py: compressed textures too (the slice targets hold their blocks as texels)" + NL +
    "    const uint32_t slice_count = r.depth > 1 && slice_targets_enabled() ? std::min(r.depth, 64u) : 0;" + NL +
    "    if (slice_count > 1) {" + NL +
    "        const size_t cells = size_t{levels} * slice_count;" + NL +
    "        if (t.slice_stride != slice_count || t.slice_keys.size() != cells) {" + NL +
    "            t.slice_stride = slice_count;" + NL +
    "            t.slice_keys.assign(cells, nullptr);" + NL +
    "            t.slice_level_source.fill(nullptr);" + NL +
    "            t.slice_generation = 0;" + NL +
    "        }" + NL +
    "        t.slice_found.assign(cells, nullptr);" + NL +
    "        const bool fresh = t.slice_generation == target_generation_;" + NL +
    "        for (uint32_t level = 0; level < levels; ++level) {" + NL +
    "            const Target* s0 = sources[level];" + NL +
    "            if (s0 == nullptr) continue;" + NL +
    "            const std::vector<Target*>** keys = t.slice_keys.data() + size_t{level} * slice_count;" + NL +
    "            if (!fresh || t.slice_level_source[level] != s0) { // look the keys up again" + NL +
    "                const uint32_t step = slice_key_bytes(s0->pitch, s0->height, std::max(1u, f.bytes), s0->tile_mode);" + NL +
    "                for (uint32_t z = 1; z < slice_count; ++z) {" + NL +
    "                    const auto it = targets_by_address_.find(s0->address + z * step);" + NL +
    "                    keys[z] = it == targets_by_address_.end() ? nullptr : &it->second;" + NL +
    "                }" + NL +
    "                t.slice_level_source[level] = s0;" + NL +
    "            }" + NL +
    "            const uint32_t step = slice_key_bytes(s0->pitch, s0->height, std::max(1u, f.bytes), s0->tile_mode);" + NL +
    "            for (uint32_t z = 1; z < slice_count; ++z) {" + NL +
    "                if (keys[z] == nullptr) continue;" + NL +
    "                // as find_target(key, 0, false): the newest colour target at the key" + NL +
    "                const uint32_t key = s0->address + z * step;" + NL +
    "                const Target* src = nullptr;" + NL +
    "                for (const Target* c : *keys[z]) {" + NL +
    "                    if (c->address != key || c->depth) continue;" + NL +
    "                    if (src == nullptr || c->written > src->written) src = c;" + NL +
    "                }" + NL +
    "                if (src == nullptr || src->written <= src->overwritten || src->pitch != s0->pitch ||" + NL +
    "                    src->height != s0->height || src->scale != s0->scale || color_format(src->format).bytes != f.bytes) {" + NL +
    "                    continue;" + NL +
    "                }" + NL +
    "                t.slice_found[size_t{level} * slice_count + z] = src;" + NL +
    "                note_target_read(src);" + NL +
    "                newest = std::max(newest, src->written);" + NL +
    "            }" + NL +
    "        }" + NL +
    "        t.slice_generation = target_generation_;" + NL +
    "    }" + NL)

edit(d + "textures.cpp", "patch_slice_cache", [
    (OLD_SCAN, NEW_SCAN),
    ("            const Target* src = slice_sources[level][z];" + NL,
     "            const Target* src = t.slice_found[size_t{level} * slice_count + z]; // port/patch_slice_cache.py" + NL),
])
