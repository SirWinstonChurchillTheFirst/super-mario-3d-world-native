#!/usr/bin/env python3
r"""patch_writeback_early.py RUNTIME_SRC_DIR : the write-back guard remembers guest memory when the GPU thread DRAWS
into a target, not when the batch is submitted.

A small render target is copied back to guest memory once the host GPU has finished the batch that wrote it
(Renderer::retired). On the console the GPU writes that memory at the moment it executes the draw; whatever the CPU
stores there afterwards stays. The guard of port/patch_writeback_guard.py imitates that: it keeps a copy of the
target's guest bytes ("before") and drops the write-back if the memory no longer matches. But the copy was taken at
the END of the batch (copy_write_backs, at the Vulkan submission). Everything the title's other threads stored into
that memory between the draw and the end of the batch was part of "before", so the late write-back erased it. The
batch can be long: every first use of a shader compiles inside it, and under CPU load the GPU thread is slow.

Measured in Mario Kart 8 (win/run/gfxfix7): during start-up the title twice renders a chain of temporary targets
(256x256 at 0x36F70000, then 128x128 at 0x36FB0000, 64x64 at 0x36FC0000, 32x32 at 0x36FC4000, ...) and gives their
memory back to its heap right after issuing the commands; other threads allocate there while the main thread waits in
GX2DrawDone (trace: up to 1080 changed bytes, heap pointers, inside "0x36FB0000 128x128" between the batch and its
retirement). One of those blocks is the draw list of a 2D layer (0x36FB7C78). When the write-back of the second chain
landed after that list had been written, its colour pointer became 0 and the main thread died in
GX2SetPixelUniformReg(offset, 4, NULL): "host fault (signal 11) at 0x0", guest LR 0x029D23F8 - the start-up crash
seen 2x by the testers and 1x in 54 starts under CPU load here, always with r31 = 0x36FB7CB4.

Fix: the bytes are remembered when the target is first written in a batch (queue_write_back, i.e. when the GPU thread
executes the draw - the closest point to the console's GPU write). The retirement thread refreshes those copies too
after it tiled an earlier write-back of the same place, as it already did for the queued ones.
TTT2_WRITEBACK_LOG=1 additionally reports targets whose memory the CPU changed between the draw and the submission
(the cases the old guard missed)."""
import sys

root = sys.argv[1] + "/"
MARK = "patch_writeback_early"


def edit(name, pairs):
    path = root + name
    s = open(path, encoding="utf-8").read()
    if MARK in s:
        print("already applied:", name)
        return
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"{MARK}: {name}: expected once: {old[:70]!r} (found {s.count(old)})")
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched:", name)


edit("gpu/vulkan/renderer.h", [
    ("""    std::deque<WriteBack> write_backs_;
""", """    std::deque<WriteBack> write_backs_;
    // port/patch_writeback_early.py: guest bytes of the targets written in the batch being recorded, taken at
    // their first draw; they become WriteBack::before at the submission.
    struct EarlyBefore {
        Target* target;
        std::vector<uint8_t> bytes;
    };
    std::vector<EarlyBefore> write_back_early_;
"""),
])

edit("gpu/vulkan/targets.cpp", [
    ("""    if (!t->write_back || replaying_ || t->write_back_queued) return;
    t->write_back_queued = true;
    write_back_targets_.push_back(t);
}
""", """    if (!t->write_back || replaying_ || t->write_back_queued) return;
    t->write_back_queued = true;
    write_back_targets_.push_back(t);
    // port/patch_writeback_early.py: what guest memory holds NOW, when the draw is executed - on the console the GPU
    // writes it at this point, and what the CPU stores there from now on must survive the late write-back.
    static const bool guard = [] {
        const char* v = std::getenv("TTT2_WRITEBACK_GUARD");
        return v == nullptr || *v != '0';
    }();
    if (!guard) return;
    const uint32_t n = t->pitch * t->height * color_format(t->format).bytes;
    if (!guest_memory_committed(t->address, n)) return;
    // Under the lock: the retirement thread may be tiling an earlier write-back of this place (see retired()).
    std::lock_guard lock(write_back_mutex_);
    write_back_early_.push_back({t, std::vector<uint8_t>(guest_pointer(t->address), guest_pointer(t->address) + n)});
}
"""),
    ("""        if (!guest_memory_committed(t->address, t->pitch * t->height * bytes)) continue;
        if (write_back_free_.empty()) {
""", """        // port/patch_writeback_early.py: the bytes remembered at the target's first draw of this batch.
        std::vector<uint8_t> early;
        for (EarlyBefore& e : write_back_early_) {
            if (e.target == t) early = std::move(e.bytes);
        }
        if (!guest_memory_committed(t->address, t->pitch * t->height * bytes)) continue;
        if (write_back_free_.empty()) {
"""),
    ("""            static const bool guard = [] {
                const char* v = std::getenv("TTT2_WRITEBACK_GUARD");
                return v == nullptr || *v != '0';
            }();
            static const bool log = std::getenv("TTT2_WRITEBACK_LOG") != nullptr;
            const uint32_t n = t->pitch * t->height * bytes;
            if (guard) write_backs_.back().before.assign(guest_pointer(t->address), guest_pointer(t->address) + n);
""", """            static const bool log = std::getenv("TTT2_WRITEBACK_LOG") != nullptr;
            const uint32_t n = t->pitch * t->height * bytes;
            if (log && early.size() == n && std::memcmp(early.data(), guest_pointer(t->address), n) != 0) {
                // The CPU stored here after the draw and before the submission: the old guard missed these.
                const uint8_t* now = guest_pointer(t->address);
                uint32_t first = n, last = 0, count = 0;
                for (uint32_t i = 0; i < n; ++i) {
                    if (now[i] == early[i]) continue;
                    if (first == n) first = i;
                    last = i;
                    ++count;
                }
                static uint32_t said = 0;
                if (++said <= 40) {
                    std::fprintf(stderr, "ttt2: write-back: 0x%08X %ux%u: the CPU changed %u bytes (+0x%X..+0x%X) between the draw and the submission\\n",
                                 t->address, t->pitch, t->height, count, first, last);
                }
            }
            write_backs_.back().before = std::move(early);
"""),
    ("""    write_back_targets_.clear();
    // For the host, and before the next submission's commands: its first
""", """    write_back_targets_.clear();
    write_back_early_.clear(); // port/patch_writeback_early.py (still under write_back_mutex_)
    // For the host, and before the next submission's commands: its first
"""),
    ("""        for (WriteBack& later : write_backs_) {
            if (later.address == w.address && !later.before.empty() && later.before.size() == n) {
                std::memcpy(later.before.data(), guest_pointer(w.address), n);
            }
        }
""", """        for (WriteBack& later : write_backs_) {
            if (later.address == w.address && !later.before.empty() && later.before.size() == n) {
                std::memcpy(later.before.data(), guest_pointer(w.address), n);
            }
        }
        // port/patch_writeback_early.py: and so do the ones remembered for the batch being recorded.
        for (EarlyBefore& e : write_back_early_) {
            if (e.target->address == w.address && e.bytes.size() == n) std::memcpy(e.bytes.data(), guest_pointer(w.address), n);
        }
"""),
])
