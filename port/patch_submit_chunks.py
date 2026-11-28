#!/usr/bin/env python3
"""patch_submit_chunks.py RUNTIME_SRC_DIR (.../runtime/src) : the frame goes to the GPU in parts while it is recorded.

The draw thread submitted only when the title flushed (Mario Kart 8: 3 times a frame) and the title then waited for
the frame's last timestamp: the GPU started on most of the frame only after the draw thread had recorded all of it,
so a frame took recording time + GPU time (console, heavy race scenes: ~10 ms + ~10 ms, title waiting 14-20 ms
a frame for its timestamp).

TTT2_SUBMIT_MS=<ms> (default 2, 0 = old behaviour): before a draw, a batch that has been recorded for that long and
holds at least 32 draws is submitted, so the GPU renders the frame's first parts while the rest is recorded.
Submitting between two draws is what a title's own flush there does (Renderer::submit ends the rendering and the
next draw begins it again; barriers order work across submissions on the one queue). Not during replays /
interpolated frames."""
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

edit(d + "renderer.h", "patch_submit_chunks", [
    ("    double last_submit_ = 0;" + NL,
     "    double last_submit_ = 0;" + NL +
     "    // port/patch_submit_chunks.py: when the batch being recorded began, its draws" + NL +
     "    std::chrono::steady_clock::time_point record_start_{};" + NL +
     "    uint32_t batch_draws_ = 0;" + NL +
     "    static double submit_chunk_seconds() {" + NL +
     "        static const double s = [] {" + NL +
     "            const char* v = std::getenv(\"TTT2_SUBMIT_MS\");" + NL +
     "            return (v ? std::atof(v) : 2.0) / 1000.0;" + NL +
     "        }();" + NL +
     "        return s;" + NL +
     "    }" + NL),
])

edit(d + "renderer.cpp", "patch_submit_chunks", [
    ("        recording_ = true;" + NL,
     "        recording_ = true;" + NL +
     "        record_start_ = std::chrono::steady_clock::now(); // port/patch_submit_chunks.py" + NL +
     "        batch_draws_ = 0;" + NL),
])

edit(d + "draw.cpp", "patch_submit_chunks", [
    ("void Renderer::draw(const Registers& regs, const Draw& d) {" + NL +
     "    if (!replaying_) ++draws_;" + NL,
     "void Renderer::draw(const Registers& regs, const Draw& d) {" + NL +
     "    if (!replaying_) ++draws_;" + NL +
     "    // port/patch_submit_chunks.py: a batch recorded for TTT2_SUBMIT_MS goes to the GPU before this draw." + NL +
     "    if (const double chunk = submit_chunk_seconds();" + NL +
     "        chunk > 0 && recording_ && !replaying_ && frames_per_frame_ == 1 && ++batch_draws_ > 32 &&" + NL +
     "        std::chrono::duration<double>(std::chrono::steady_clock::now() - record_start_).count() >= chunk) {" + NL +
     "        submit(false);" + NL +
     "    }" + NL),
])
