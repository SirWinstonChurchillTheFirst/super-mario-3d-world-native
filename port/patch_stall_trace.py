#!/usr/bin/env python3
"""patch_stall_trace.py RUNTIME_SRC_DIR (.../runtime/src) : what the draw thread did in a frame that took long.

TTT2_TRACE_STALLS=1 printed only the gaps between presents ("stall: <time> <ms>"). Now the draw thread also prints,
for every frame (swap to swap) over 60 ms:
  stall-cp: <steady time> frame <n> <ms>: images <count> made in <ms> (<MB>), textures new <n>, targets new <n>,
            submits <n> in <ms>, GPU waits <ms>, translate <ms>, compile <ms>, pipelines <ms>, texture binds <ms>,
            uploads <ms>
so a hitch can be told apart: image/memory creation, waiting for the GPU, shader work, texture work, or none of these
(then the time went to the title / elsewhere). Off without the variable (one flag test per image / submit)."""
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

edit(d + "renderer.h", "patch_stall_trace", [
    ("    double last_submit_ = 0;" + NL,
     "    double last_submit_ = 0;" + NL +
     "    // port/patch_stall_trace.py: per frame, for TTT2_TRACE_STALLS" + NL +
     "    static bool trace_stalls() {" + NL +
     "        static const bool on = std::getenv(\"TTT2_TRACE_STALLS\") != nullptr;" + NL +
     "        return on;" + NL +
     "    }" + NL +
     "    struct StallFrame {" + NL +
     "        double image_s = 0, image_mb = 0, submit_s = 0;" + NL +
     "        uint32_t images = 0, textures = 0, submits = 0;" + NL +
     "    } stall_{};" + NL +
     "    void trace_stall_frame();" + NL),
])

edit(d + "renderer.cpp", "patch_stall_trace", [
    # images
    ("    VK_CHECK(vkCreateImage(ctx_.device, &ici, nullptr, &img.image));" + NL,
     "    const auto image_t0 = std::chrono::steady_clock::now(); // port/patch_stall_trace.py" + NL +
     "    VK_CHECK(vkCreateImage(ctx_.device, &ici, nullptr, &img.image));" + NL),
    ("    VkImageViewCreateInfo vci{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};" + NL +
     "    vci.image = img.image;" + NL +
     "    vci.viewType = view_type;" + NL,
     "    if (trace_stalls()) { // port/patch_stall_trace.py: creation + memory" + NL +
     "        stall_.image_s += std::chrono::duration<double>(std::chrono::steady_clock::now() - image_t0).count();" + NL +
     "        ++stall_.images;" + NL +
     "        VkMemoryRequirements req;" + NL +
     "        vkGetImageMemoryRequirements(ctx_.device, img.image, &req);" + NL +
     "        stall_.image_mb += req.size / 1048576.0;" + NL +
     "    }" + NL +
     "    VkImageViewCreateInfo vci{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};" + NL +
     "    vci.image = img.image;" + NL +
     "    vci.viewType = view_type;" + NL),
    # submits
    ("        {" + NL +
     "            std::lock_guard lock(queue_mutex_);" + NL +
     "            VK_CHECK(vkQueueSubmit(ctx_.queue, 1, &si, VK_NULL_HANDLE));" + NL +
     "        }" + NL,
     "        const auto submit_t0 = std::chrono::steady_clock::now(); // port/patch_stall_trace.py" + NL +
     "        {" + NL +
     "            std::lock_guard lock(queue_mutex_);" + NL +
     "            VK_CHECK(vkQueueSubmit(ctx_.queue, 1, &si, VK_NULL_HANDLE));" + NL +
     "        }" + NL +
     "        if (trace_stalls()) {" + NL +
     "            stall_.submit_s += std::chrono::duration<double>(std::chrono::steady_clock::now() - submit_t0).count();" + NL +
     "            ++stall_.submits;" + NL +
     "        }" + NL),
    # report at the end of a frame
    ("void Renderer::swap() {" + NL,
     "// port/patch_stall_trace.py: a frame of the draw thread over 60 ms, and what took the time in it." + NL +
     "void Renderer::trace_stall_frame() {" + NL +
     "    static double last = 0, wait0 = 0;" + NL +
     "    static Spent tr0{}, co0{}, pi0{}, te0{}, up0{};" + NL +
     "    static uint64_t targets0 = 0;" + NL +
     "    const double now = now_seconds();" + NL +
     "    // the Spent counters restart every 10 s (statistics line): a smaller value is a new window" + NL +
     "    const auto delta = [](const Spent& now_s, const Spent& then) {" + NL +
     "        return (now_s.seconds >= then.seconds ? now_s.seconds - then.seconds : now_s.seconds) * 1000.0;" + NL +
     "    };" + NL +
     "    const double waited = wait_seconds_ >= wait0 ? wait_seconds_ - wait0 : wait_seconds_;" + NL +
     "    if (last != 0 && now - last > 0.06) {" + NL +
     "        std::fprintf(stderr," + NL +
     "                     \"stall-cp: %.3f frame %llu %.0f ms: images %u made in %.1f ms (%.1f MB), textures new %u, targets new %llu, \"" + NL +
     "                     \"submits %u in %.1f ms, GPU waits %.1f ms, translate %.1f ms, compile %.1f ms, pipelines %.1f ms, \"" + NL +
     "                     \"texture binds %.1f ms, uploads %.1f ms\\n\"," + NL +
     "                     now, static_cast<unsigned long long>(frame_number_), (now - last) * 1000.0, stall_.images," + NL +
     "                     stall_.image_s * 1000.0, stall_.image_mb, stall_.textures," + NL +
     "                     static_cast<unsigned long long>(target_generation_ - targets0), stall_.submits, stall_.submit_s * 1000.0," + NL +
     "                     waited * 1000.0, delta(spent_translate_, tr0), delta(spent_compile_, co0), delta(spent_pipeline_, pi0)," + NL +
     "                     delta(spent_texture_, te0), delta(spent_upload_, up0));" + NL +
     "    }" + NL +
     "    last = now;" + NL +
     "    wait0 = wait_seconds_;" + NL +
     "    tr0 = spent_translate_;" + NL +
     "    co0 = spent_compile_;" + NL +
     "    pi0 = spent_pipeline_;" + NL +
     "    te0 = spent_texture_;" + NL +
     "    up0 = spent_upload_;" + NL +
     "    targets0 = target_generation_;" + NL +
     "    stall_ = {};" + NL +
     "}" + NL + NL +
     "void Renderer::swap() {" + NL +
     "    if (trace_stalls()) trace_stall_frame(); // port/patch_stall_trace.py" + NL),
])

edit(d + "textures.cpp", "patch_stall_trace", [
    ("        auto t = std::make_unique<Texture>();" + NL,
     "        auto t = std::make_unique<Texture>();" + NL +
     "        if (trace_stalls()) ++stall_.textures; // port/patch_stall_trace.py" + NL),
])
