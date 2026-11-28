#!/usr/bin/env python3
"""patch_target_evict_safe.py RUNTIME_SRC_DIR (.../runtime/src) : the target eviction no longer frees a "written back"
render target whose contents are in fact NOT (all) in guest memory. Apply after patch_target_evict_layers.py and
patch_trace_loss.py.

Found with Mario Kart 8 (26/27 Nov, TTT2_TRACE_LOSS=1, Grand Prix): target_dispensable() let a small colour target go
after 30 unused seconds because "every GPU write of it was tiled into guest memory". Two cases where that is not true:
  1. Layer 0 of a cube / array texture that no texture has bound yet. The title renders its light probes (32x32x6 and
     16x16x6 R11G11B10F cubes, the compressed copies of them) while a course loads and binds some of them much later
     (when the kart reaches that part of the course). Only a bind marked the layer-0 target `layered`
     (patch_target_evict_layers.py); until then it was a plain written-back 2D target and went after 30 s. The texture then
     found no level-0 target and loaded ALL its faces from guest memory: face 0 right, faces 1-5 whatever lay there
     (zeros in a fresh session = dark coins; old heap contents later in a session = coloured garbage).
     Now: a target with a slice target of its own size one slice further (address + slice size) is layer 0 of a layered
     surface and is treated like one from the start.
  2. The write-back guard (patch_writeback_guard.py / patch_writeback_early.py) skipped its last write-back ("guest memory
     changed since the draw") or its memory was not committed: the picture exists only in the target. Now such a target
     is not "written back" for the eviction until a later write-back of that place lands.
Both kinds can still be freed when the CPU wrote their memory or a newer target lies over it.
TTT2_EVICT_SAFE=0 = behaviour before this patch (for A/B). The reason printed by TTT2_TRACE_TARGETS / TTT2_TRACE_LOSS now
comes from the same function that decides."""
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

edit(d + "renderer.h", "patch_target_evict_safe", [
    ("#include <unordered_map>" + NL,
     "#include <unordered_map>" + NL +
     "#include <unordered_set> // port/patch_target_evict_safe.py" + NL),
    ("    bool target_dispensable(const Target& t) const;" + NL,
     "    bool target_dispensable(const Target& t) const;" + NL +
     "    // port/patch_target_evict_safe.py: why a target may go (\"cpu\", \"writeback\", \"overlap\") or nullptr; layer 0 of a" + NL +
     "    // surface with slice targets; places whose last write-back did not reach guest memory (under write_back_mutex_)." + NL +
     "    const char* target_free_reason(const Target& t) const;" + NL +
     "    bool layer_zero_of_slices(const Target& t) const;" + NL +
     "    std::unordered_set<uint32_t> write_back_lost_;" + NL),
])

edit(d + "targets.cpp", "patch_target_evict_safe", [
    # write-backs that did not reach guest memory
    ("        if (!guest_memory_committed(t->address, t->pitch * t->height * bytes)) continue;" + NL +
     "        if (write_back_free_.empty()) {" + NL,
     "        if (!guest_memory_committed(t->address, t->pitch * t->height * bytes)) {" + NL +
     "            write_back_lost_.insert(t->address); // port/patch_target_evict_safe.py" + NL +
     "            continue;" + NL +
     "        }" + NL +
     "        if (write_back_free_.empty()) {" + NL),
    ("            write_back_free_.push_back(w.staging);" + NL +
     "            if (trace_loss()) ++write_back_skips_[w.address]; // port/patch_trace_loss.py" + NL +
     "            continue;" + NL,
     "            write_back_free_.push_back(w.staging);" + NL +
     "            if (trace_loss()) ++write_back_skips_[w.address]; // port/patch_trace_loss.py" + NL +
     "            write_back_lost_.insert(w.address); // port/patch_target_evict_safe.py" + NL +
     "            continue;" + NL),
    ("        write_back_free_.push_back(w.staging);" + NL +
     "        if (trace_loss()) write_back_skips_.erase(w.address); // port/patch_trace_loss.py" + NL,
     "        write_back_free_.push_back(w.staging);" + NL +
     "        if (trace_loss()) write_back_skips_.erase(w.address); // port/patch_trace_loss.py" + NL +
     "        if (!write_back_lost_.empty()) write_back_lost_.erase(w.address); // port/patch_target_evict_safe.py" + NL),
    # the decision
    ("bool Renderer::target_dispensable(const Target& t) const {" + NL +
     "    if (t.overwritten > t.written) return true; // the CPU wrote its memory since: textures read that memory anyway" + NL +
     "    // port/patch_target_evict_layers.py: not a layer of a layered texture (its other layers are not in guest memory)" + NL +
     "    if (t.write_back && !t.layered && std::getenv(\"TTT2_NO_WRITEBACK\") == nullptr && std::getenv(\"TTT2_WRITEBACK_RANGE\") == nullptr) {" + NL +
     "        return true; // every GPU write of it was tiled into guest memory" + NL +
     "    }" + NL,
     "// port/patch_target_evict_safe.py: a slice target of its size one slice further = it is layer 0 of a layered surface," + NL +
     "// also before any texture has bound that surface." + NL +
     "bool Renderer::layer_zero_of_slices(const Target& t) const {" + NL +
     "    if (t.depth) return false;" + NL +
     "    const uint32_t bytes = std::max(1u, color_format(t.format).bytes);" + NL +
     "    const auto it = targets_by_address_.find(t.address + slice_key_bytes(t.pitch, t.height, bytes, t.tile_mode));" + NL +
     "    if (it == targets_by_address_.end()) return false;" + NL +
     "    for (const Target* u : it->second) {" + NL +
     "        if (u != &t && !u->depth && u->layered && u->pitch == t.pitch && u->height == t.height &&" + NL +
     "            std::max(1u, color_format(u->format).bytes) == bytes) {" + NL +
     "            return true;" + NL +
     "        }" + NL +
     "    }" + NL +
     "    return false;" + NL +
     "}" + NL +
     NL +
     "bool Renderer::target_dispensable(const Target& t) const { return target_free_reason(t) != nullptr; }" + NL +
     NL +
     "const char* Renderer::target_free_reason(const Target& t) const {" + NL +
     "    if (t.overwritten > t.written) return \"cpu\"; // the CPU wrote its memory since: textures read that memory anyway" + NL +
     "    // port/patch_target_evict_layers.py: not a layer of a layered texture (its other layers are not in guest memory)" + NL +
     "    if (t.write_back && !t.layered && std::getenv(\"TTT2_NO_WRITEBACK\") == nullptr && std::getenv(\"TTT2_WRITEBACK_RANGE\") == nullptr) {" + NL +
     "        static const bool safe = [] {" + NL +
     "            const char* v = std::getenv(\"TTT2_EVICT_SAFE\");" + NL +
     "            return v == nullptr || *v != '0';" + NL +
     "        }();" + NL +
     "        if (!safe) return \"writeback\";" + NL +
     "        bool lost;" + NL +
     "        {" + NL +
     "            std::lock_guard lock(const_cast<std::mutex&>(write_back_mutex_));" + NL +
     "            lost = write_back_lost_.count(t.address) != 0;" + NL +
     "        }" + NL +
     "        if (!lost && !layer_zero_of_slices(t)) return \"writeback\"; // every GPU write of it was tiled into guest memory" + NL +
     "    }" + NL),
    ("        for (const Target* u : it->second) {" + NL +
     "            if (u != &t && u->end > t.address && u->address < t.end && u->written > t.written) return true;" + NL +
     "        }" + NL +
     "    }" + NL +
     "    return false;" + NL +
     "}" + NL,
     "        for (const Target* u : it->second) {" + NL +
     "            if (u != &t && u->end > t.address && u->address < t.end && u->written > t.written) return \"overlap\";" + NL +
     "        }" + NL +
     "    }" + NL +
     "    return nullptr;" + NL +
     "}" + NL),
    # the printed reason = the deciding one
    ("            const char* why = t->overwritten > t->written ? \"cpu\" : t->write_back && !t->layered ? \"writeback\" : \"overlap\";" + NL,
     "            const char* why = target_free_reason(*t); // port/patch_target_evict_safe.py" + NL +
     "            if (why == nullptr) why = \"?\";" + NL, 2),
])
