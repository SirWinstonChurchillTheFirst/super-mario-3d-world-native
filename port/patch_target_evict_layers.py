#!/usr/bin/env python3
"""patch_target_evict_layers.py RUNTIME_SRC_DIR (.../runtime/src) : render targets that are one layer of an array, cube or
3D texture are no longer freed because they are "written back" (after patch_target_eviction.py).

Found with Mario Kart 8 on the console (25 Nov): after 30 s the eviction freed targets whose contents were still needed.
target_dispensable() let a write-back target go because "its contents are in guest memory". That holds for a plain 2D
surface, not for layer 0 of a layered texture: the other layers (faces of a cube, slices of an array or 3D texture) live in
their own slice targets that are never written back (their key is not their place in memory), and a thick-tiled 3D
surface is not tiled like a 2D one. When the layer-0 target went, the texture loaded ALL its layers from guest memory
again = garbage. Seen (TTT2_TRACE_TARGETS=1 now prints why a target went):
  - menu colour-grading LUT 0x3A808C00 (8x8x8 R11G11B10F, 1D tiled thick, drawn once) freed as "writeback" during a race
    -> the preview videos in the menus nearly black after a race/cup;
  - the menu lighting cube (32x32 R11G11B10F cube, base target written back) freed while the title screen ran
    -> Mario black on the character turntable;
  - in races the same for layered textures drawn once per course (dark coins / items, dark blob-shadow areas).
Now a target is marked `layered` when a texture takes it as one of several layers (layer 0 included), when it is drawn as
a slice, or when its tile mode is thick; a layered target is freed only when the CPU wrote its memory since, or a newer
target lies over its memory (both mean its contents are stale on the console too) - never for being written back.
TTT2_TRACE_TARGETS=1: each freed target with the reason (cpu / writeback / overlap) and the newer target over it."""
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

edit(d + "renderer.h", "patch_target_evict_layers", [
    ("    bool carried = false;       // read before written in this frame" + NL,
     "    bool carried = false;       // read before written in this frame" + NL +
     "    // port/patch_target_evict_layers.py: one layer of an array/cube/3D texture (or thick-tiled): its write-back alone" + NL +
     "    // does not give the texture back, so it is not freed for being written back." + NL +
     "    bool layered = false;" + NL),
])

edit(d + "targets.cpp", "patch_target_evict_layers", [
    # thick tile modes (1D/2D/2B/3D thick) hold several slices interleaved
    ("    t->write_back = !f.widened && t->scale == 1 && uint64_t{pitch} * height * f.bytes <= kWriteBackBytes && same(f.swizzle.r) &&" + NL +
     "                    same(f.swizzle.g) && same(f.swizzle.b) && same(f.swizzle.a);" + NL,
     "    t->write_back = !f.widened && t->scale == 1 && uint64_t{pitch} * height * f.bytes <= kWriteBackBytes && same(f.swizzle.r) &&" + NL +
     "                    same(f.swizzle.g) && same(f.swizzle.b) && same(f.swizzle.a);" + NL +
     "    t->layered = tile_mode == 3 || tile_mode == 7 || tile_mode == 11 || tile_mode == 13 || tile_mode == 15; // port/patch_target_evict_layers.py" + NL),
    ("    if (sliced && t != nullptr) t->write_back = false; // its key is not its place in guest memory" + NL,
     "    if (sliced && t != nullptr) t->write_back = false; // its key is not its place in guest memory" + NL +
     "    if (sliced && t != nullptr) t->layered = true; // port/patch_target_evict_layers.py" + NL),
    ("    if (t.write_back && std::getenv(\"TTT2_NO_WRITEBACK\") == nullptr && std::getenv(\"TTT2_WRITEBACK_RANGE\") == nullptr) {" + NL,
     "    // port/patch_target_evict_layers.py: not a layer of a layered texture (its other layers are not in guest memory)" + NL +
     "    if (t.write_back && !t.layered && std::getenv(\"TTT2_NO_WRITEBACK\") == nullptr && std::getenv(\"TTT2_WRITEBACK_RANGE\") == nullptr) {" + NL),
    ("            std::fprintf(stderr, \"ttt2: gpu: freed %s target 0x%08X fmt 0x%03X %ux%u (unused for %llu frames)\\n\"," + NL +
     "                         t->depth ? \"depth\" : \"color\", t->address, t->format, t->pitch, t->height," + NL +
     "                         static_cast<unsigned long long>(frame_number_ - t->used_frame));" + NL,
     "            // port/patch_target_evict_layers.py: why it may go, and the newer target over it" + NL +
     "            const char* why = t->overwritten > t->written ? \"cpu\" : t->write_back && !t->layered ? \"writeback\" : \"overlap\";" + NL +
     "            const Target* over = nullptr;" + NL +
     "            if (*why == 'o') {" + NL +
     "                const uint32_t from = t->address > max_target_span_ ? t->address - max_target_span_ : 0;" + NL +
     "                for (auto it = targets_sorted_.lower_bound(from); it != targets_sorted_.end() && it->first < t->end; ++it) {" + NL +
     "                    for (const Target* u : it->second) {" + NL +
     "                        if (u != t && u->end > t->address && u->address < t->end && u->written > t->written) over = u;" + NL +
     "                    }" + NL +
     "                }" + NL +
     "            }" + NL +
     "            std::fprintf(stderr, \"ttt2: gpu: freed %s target 0x%08X fmt 0x%03X %ux%u tile %u%s (unused for %llu frames): %s\"," + NL +
     "                         t->depth ? \"depth\" : \"color\", t->address, t->format, t->pitch, t->height, t->tile_mode," + NL +
     "                         t->layered ? \" layered\" : \"\", static_cast<unsigned long long>(frame_number_ - t->used_frame), why);" + NL +
     "            if (over) std::fprintf(stderr, \" under 0x%08X fmt 0x%03X %ux%u\", over->address, over->format, over->pitch, over->height);" + NL +
     "            std::fprintf(stderr, \"\\n\");" + NL),
])

edit(d + "textures.cpp", "patch_target_evict_layers", [
    # colour: every level's layer-0 target and every slice target of a texture with several layers
    ("    if (slice_count > 1) {" + NL +
     "        const size_t cells = size_t{levels} * slice_count;" + NL,
     "    if (slice_count > 1) {" + NL +
     "        for (uint32_t level = 0; level < levels; ++level) { // port/patch_target_evict_layers.py" + NL +
     "            if (sources[level]) const_cast<Target*>(sources[level])->layered = true;" + NL +
     "        }" + NL +
     "        const size_t cells = size_t{levels} * slice_count;" + NL),
    ("                t.slice_found[size_t{level} * slice_count + z] = src;" + NL,
     "                t.slice_found[size_t{level} * slice_count + z] = src;" + NL +
     "                const_cast<Target*>(src)->layered = true; // port/patch_target_evict_layers.py" + NL),
    # depth arrays (shadow cascades)
    ("                slices[z] = other;" + NL,
     "                slices[z] = other;" + NL +
     "                const_cast<Target*>(other)->layered = true; // port/patch_target_evict_layers.py" + NL +
     "                const_cast<Target*>(src)->layered = true;" + NL),
])

edit(d + "draw.cpp", "patch_target_evict_layers", [
    ("        if (slice != 0 && colors[t] && slice_targets_enabled()) const_cast<Target*>(colors[t])->write_back = false;" + NL,
     "        if (slice != 0 && colors[t] && slice_targets_enabled()) const_cast<Target*>(colors[t])->write_back = false;" + NL +
     "        if (slice != 0 && colors[t] && slice_targets_enabled()) const_cast<Target*>(colors[t])->layered = true; // port/patch_target_evict_layers.py" + NL),
])
