#!/usr/bin/env python3
"""patch_seq_ps.py RUNTIME_SRC_DIR : TTT2_SEQ_PS=<ps hash, hex> (tool, after patch_trace_frames.py / patch_depth_slices.py).

With TTT2_CAPTURE_SEQUENCE the targets that a draw with this pixel shader writes (colour 0) and reads (the sources of
its textures, and every slice target of a depth array) are saved with each sequence image, like TTT2_SEQ_TARGETS but
without knowing the addresses (MK8 moves its shadow maps and scene buffers whenever its quality scaler changes size).
The hash is the "ps" of a "trace: draw" line. Costs one program hash per draw while set.
TTT2_SAVE_ALPHA=1: saved pictures keep their alpha channel (default: opaque).
TTT2_TRACE_KC=<rows>: a traced draw prints that many vectors of each uniform block (default 12).
TTT2_TRACE_PIXEL: the probe buffer is cleared first, so formats under 8 bytes per texel hash correctly.
TTT2_SAVE_RAW=1: every saved picture also as <name>.raw (texels as read back: 2 bytes D16, 4 bytes float depth/8-bit colour).
TTT2_SKIP_PS=<hash>[,<hash>]: draws with that pixel shader are skipped (to see what they draw)."""
import sys

root = sys.argv[1] + "/gpu/vulkan/"


def edit(name, pairs):
    path = root + name
    s = open(path, encoding="utf-8").read()
    if "patch_seq_ps" in s:
        print("already applied:", name)
        return
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70])
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("patched", path)


edit("renderer.h", [
    ("""    bool sequence_saving_ = false;
""",
     """    bool sequence_saving_ = false;
    std::vector<uint32_t> seq_watch_; // port/patch_seq_ps.py: addresses of the targets TTT2_SEQ_PS found
    void seq_watch(uint32_t address) {
        for (uint32_t a : seq_watch_) if (a == address) return;
        seq_watch_.push_back(address);
    }
"""),
])

edit("draw.cpp", [
    ("""                const uint32_t w = x1 - x0, h = y1 - y0, texel = 8, bytes = w * h * texel;
                VkDeviceSize offset = 0;
                upload(bytes, 16, offset);
                end_rendering();
""",
     """                const uint32_t w = x1 - x0, h = y1 - y0, texel = 8, bytes = w * h * texel;
                VkDeviceSize offset = 0;
                upload(bytes, 16, offset);
                std::memset(ring_.mapped() + offset, 0, bytes); // port/patch_seq_ps.py: formats under 8 bytes/texel left stale bytes in the hash
                end_rendering();
"""),
    ("""                    if (a == 0 || !guest_memory_committed(a, 12 * 16)) continue;
                    for (uint32_t i = 0; i < 12; ++i) {
""",
     """                    // port/patch_seq_ps.py: TTT2_TRACE_KC=<rows> prints more than the first 12 vectors of each block
                    static const uint32_t kc_rows = [] {
                        const char* v = std::getenv("TTT2_TRACE_KC");
                        return v ? std::max(12u, static_cast<uint32_t>(std::atoi(v))) : 12u;
                    }();
                    if (a == 0 || !guest_memory_committed(a, kc_rows * 16)) continue;
                    for (uint32_t i = 0; i < kc_rows; ++i) {
"""),
    ("""    // Render targets.
    std::array<const Target*, 8> colors{};
""",
     """    // port/patch_seq_ps.py: TTT2_SKIP_PS=<hash>[,<hash>..]: draws with that pixel shader are not drawn (as TTT2_SKIP_VS).
    if (static const char* skip = std::getenv("TTT2_SKIP_PS"); skip) {
        uint64_t sh = 0;
        program(r(reg::SQ_PGM_START_PS) << 8, r(reg::SQ_PGM_START_PS + 4) << 3, sh);
        char name[20];
        std::snprintf(name, sizeof(name), "%016llx", static_cast<unsigned long long>(sh));
        if (std::strstr(skip, name) != nullptr) return;
    }

    // Render targets.
    std::array<const Target*, 8> colors{};
"""),
    ("""    if (tracing()) {
        uint64_t vh = 0, ph = 0, fh = 0;
""",
     """    if (static const char* watch_ps = std::getenv("TTT2_SEQ_PS"); watch_ps != nullptr) { // port/patch_seq_ps.py
        uint64_t wh = 0;
        program(r(reg::SQ_PGM_START_PS) << 8, r(reg::SQ_PGM_START_PS + 4) << 3, wh);
        if (wh == std::strtoull(watch_ps, nullptr, 16)) {
            if (colors[0]) seq_watch(colors[0]->address);
            for (uint32_t slot = 0; slot < abi::kTextureSlots; ++slot) {
                if (!(ps->info.texture_mask & (1u << slot))) continue;
                uint32_t w[7];
                for (int i = 0; i < 7; ++i) w[i] = r(kResourceBase + ((resource::kPsTexture + slot) * resource::kWords + i) * 4);
                const Texture* t = texture(w);
                if (t && t->source) seq_watch(t->source->address);
            }
        }
    }
    if (tracing()) {
        uint64_t vh = 0, ph = 0, fh = 0;
"""),
])

edit("textures.cpp", [
    ("""                if (other == nullptr) continue;
                slices[z] = other;
""",
     """                if (other == nullptr) continue;
                if (static const bool watch = std::getenv("TTT2_SEQ_PS") != nullptr; watch) seq_watch(other->address); // port/patch_seq_ps.py
                slices[z] = other;
"""),
])

edit("renderer.cpp", [
    ("""    write_png(path, pixels.data(), img.width, img.height);
}
""",
     """    write_png(path, pixels.data(), img.width, img.height);
    // port/patch_seq_ps.py: TTT2_SAVE_RAW=1 also writes the texels as read back (<name>.raw: width x height x texel bytes)
    if (static const bool raw = std::getenv("TTT2_SAVE_RAW") != nullptr; raw) {
        if (std::FILE* f = std::fopen((path + ".raw").c_str(), "wb")) {
            std::fwrite(data, 1, static_cast<size_t>(bytes), f);
            std::fclose(f);
        }
    }
}
"""),
    ("""            if (t->written <= last || only == nullptr) continue;
            char a[16];
            std::snprintf(a, sizeof(a), "%08X", t->address);
            if (std::strstr(only, a) == nullptr) continue;
""",
     """            bool watched = false; // port/patch_seq_ps.py
            for (uint32_t w : seq_watch_) watched = watched || w == t->address;
            if (t->written <= last || (only == nullptr && !watched)) continue;
            char a[16];
            std::snprintf(a, sizeof(a), "%08X", t->address);
            if (!watched && std::strstr(only, a) == nullptr) continue;
"""),
    ("""        pixels[i * 4 + 3] = keep_alpha ? static_cast<uint8_t>(std::clamp(c[3], 0.0f, 1.0f) * 255.0f + 0.5f) : 255;
""",
     """        // port/patch_seq_ps.py: TTT2_SAVE_ALPHA=1 keeps alpha in every saved picture
        static const bool env_alpha = std::getenv("TTT2_SAVE_ALPHA") != nullptr;
        pixels[i * 4 + 3] = keep_alpha || env_alpha ? static_cast<uint8_t>(std::clamp(c[3], 0.0f, 1.0f) * 255.0f + 0.5f) : 255;
"""),
])
