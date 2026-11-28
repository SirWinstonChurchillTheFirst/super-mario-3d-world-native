#!/usr/bin/env python3
r"""patch_texture_stores.py RUNTIME_SRC_DIR : the OS memory routines tell the renderer when they write into a texture.

The renderer keeps a GPU copy of every texture and reloads it only after a notice that the CPU wrote its memory
(GX2Invalidate, DCFlushRange / DCStoreRange, dcbf, the DMA engine). On the console there is no copy: the GPU samples
guest memory, so a title that writes texels and sends no notice still shows them.

Mario Kart 8 does exactly that for text in the system font (CafeStd): its font library keeps a 2048x1024 R8 glyph
texture, flushes it once when it is created (DCZeroRange + DCFlushRange) and afterwards a worker thread
("UIScalableFont") rasterises every glyph a text needs for the first time and copies it in with coreinit's memset /
memcpy - no flush, no GX2Invalidate, ever (measured: no notice over the texture after frame 0; the game has no dcbf
and its library has no other flush call). The copy on the GPU stayed what it was at the first draw: every letter
that no earlier text had used was missing ("er  e e  r ller  eler  er" for "Verbinde den Controller von Spieler 2 mit
der ...").

coreinit's memcpy / memmove / memset / OSBlockMove / OSBlockSet / DCZeroRange run in the runtime, so the runtime
knows about these writes: they now report them (gpu::cpu_stored) when the destination touches a 4 KiB page that a
loaded texture uses - a table of counters the renderer keeps, one relaxed atomic load per call otherwise. The report
is a notice for textures only (Backend::texture_stored): a texture over the range is hashed at its next use and
reloaded if it changed. It is NOT the full notice of a flush (gpu::cpu_wrote), which also searches the render targets
and the shader programs. Measured in a Mario Kart 8 race: 250-900 such notices per 600 submissions, under 0.1 ms
in total.

OSBlockMove with its flush argument set gives the full notice (as DCFlushRange).

Left alone on purpose: DCFlushRangeNoSync stays a no-op. Making it a full notice like DCFlushRange did not bring the
letters back (the font code does not call it) and cost Mario Kart 8 8 frames/s in a race (58 -> 50 on the PC: the
game sends over 100 000 more notices per 600 submissions, each searching textures, targets and programs).

Not covered: texels a title stores with its own inline code and never flushes. TTT2_RECHECK_TEXTURES=1 finds those:
every whole-cache GX2Invalidate (titles send one or more per frame) then re-hashes all textures, and each one that
changed without notice prints "recheck: texture ... reloads" (slow; for diagnosis)."""
import sys

root = sys.argv[1] + "/"
MARK = "patch_texture_stores"


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


edit("gpu/gpu.h", [
    ("#include <cstdint>\n", "#include <atomic>\n#include <cstdint>\n"),
    ("""void cpu_wrote(uint32_t address, uint32_t size);
""", """void cpu_wrote(uint32_t address, uint32_t size);

// port/patch_texture_stores.py: how many loaded textures use each 4 KiB page of guest memory (kept by the renderer),
// so that the OS memory routines (memcpy, memset, OSBlockMove, ...) can tell cheaply whether they wrote into one.
// A title may fill a texture with them and send no flush: on the console the GPU reads the memory itself.
inline constexpr uint32_t kTexturePageShift = 12;
extern std::atomic<uint32_t> g_texture_page_users[1u << (32 - kTexturePageShift)];
void texture_pages_changed(uint32_t address, uint64_t end, int delta);
// Textures over [address, address + size) are checked (hashed) at their next use; nothing else. Any thread.
void texture_stored(uint32_t address, uint32_t size);
// An OS memory routine wrote [address, address + size): a notice for the textures if one may lie there.
inline void cpu_stored(uint32_t address, uint32_t size) {
    if (size == 0) return;
    const uint64_t last = (uint64_t{address} + size - 1) >> kTexturePageShift;
    for (uint64_t page = address >> kTexturePageShift; page <= last && page < (1u << (32 - kTexturePageShift)); ++page) {
        if (g_texture_page_users[page].load(std::memory_order_relaxed) != 0) {
            texture_stored(address, size);
            return;
        }
    }
}
"""),
])

edit("gpu/backend.h", [
    ("""    virtual void cpu_wrote(uint32_t, uint32_t) {}
""", """    virtual void cpu_wrote(uint32_t, uint32_t) {}
    // port/patch_texture_stores.py: an OS memory routine wrote there; only textures need to look.
    virtual void texture_stored(uint32_t, uint32_t) {}
"""),
])

edit("gpu/vulkan/renderer.h", [
    ("""    void cpu_wrote(uint32_t address, uint32_t size) override;
""", """    void cpu_wrote(uint32_t address, uint32_t size) override;
    void texture_stored(uint32_t address, uint32_t size) override; // port/patch_texture_stores.py
"""),
])

edit("gpu/command_processor.cpp", [
    ("""void cpu_wrote(uint32_t address, uint32_t size) {
    if (size == 0) return;
""", """// port/patch_texture_stores.py
std::atomic<uint32_t> g_texture_page_users[1u << (32 - kTexturePageShift)];

void texture_pages_changed(uint32_t address, uint64_t end, int delta) {
    if (end <= address) return;
    for (uint64_t page = address >> kTexturePageShift; page <= (end - 1) >> kTexturePageShift; ++page) {
        if (page >= (1u << (32 - kTexturePageShift))) break;
        if (delta > 0) {
            g_texture_page_users[page].fetch_add(1, std::memory_order_relaxed);
        } else {
            g_texture_page_users[page].fetch_sub(1, std::memory_order_relaxed);
        }
    }
}

void texture_stored(uint32_t address, uint32_t size) {
    if (size == 0) return;
    std::lock_guard lock(g_written_mutex);
    // row after row of a copy = one range
    if (!g_stored.empty() && uint64_t{g_stored.back().first} + g_stored.back().second == address &&
        g_stored.back().second < (1u << 20)) {
        g_stored.back().second += size;
        return;
    }
    g_stored.emplace_back(address, size);
}

void cpu_wrote(uint32_t address, uint32_t size) {
    if (size == 0) return;
"""),
    ("""std::vector<std::pair<uint32_t, uint32_t>> g_written; // CPU writes not yet seen by the backend
""", """std::vector<std::pair<uint32_t, uint32_t>> g_written; // CPU writes not yet seen by the backend
std::vector<std::pair<uint32_t, uint32_t>> g_stored;  // port/patch_texture_stores.py: OS memory routine writes, likewise
"""),
    ("""            std::vector<std::pair<uint32_t, uint32_t>> written;
            {
                std::lock_guard lock(g_written_mutex);
                written.swap(g_written);
            }
            for (const auto& [address, size] : written) g_backend->cpu_wrote(address, size);
""", """            std::vector<std::pair<uint32_t, uint32_t>> written, stored;
            {
                std::lock_guard lock(g_written_mutex);
                written.swap(g_written);
                stored.swap(g_stored); // port/patch_texture_stores.py
            }
            for (const auto& [address, size] : written) g_backend->cpu_wrote(address, size);
            for (const auto& [address, size] : stored) g_backend->texture_stored(address, size);
"""),
])

edit("gpu/vulkan/textures.cpp", [
    ("""void Renderer::cpu_wrote(uint32_t address, uint32_t size) {
""", """// port/patch_texture_stores.py
void Renderer::texture_stored(uint32_t address, uint32_t size) {
    if (size != 0) mark_textures_dirty(address, uint64_t{address} + size);
}

void Renderer::cpu_wrote(uint32_t address, uint32_t size) {
"""),
    # a texture's memory enters / leaves the page counters with the texture
    ("""            if (range[1] > range[0]) for_pages(range[0], range[1], [&](uint32_t page) { texture_pages_[page].push_back(t.get()); });
""", """            if (range[1] > range[0]) for_pages(range[0], range[1], [&](uint32_t page) { texture_pages_[page].push_back(t.get()); });
            gpu::texture_pages_changed(range[0], range[1], +1); // port/patch_texture_stores.py
"""),
    ("""        for (const auto& range : t->memory) {
            if (range[1] <= range[0]) continue;
            for_pages(range[0], range[1], [&](uint32_t page) {
""", """        for (const auto& range : t->memory) {
            if (range[1] <= range[0]) continue;
            gpu::texture_pages_changed(range[0], range[1], -1); // port/patch_texture_stores.py
            for_pages(range[0], range[1], [&](uint32_t page) {
"""),
    # diagnosis: TTT2_RECHECK_TEXTURES=1
    ("""    if (size >= 0x80000000u) return;
    mark_textures_dirty(address, uint64_t{address} + size);
""", """    if (size >= 0x80000000u) {
        // port/patch_texture_stores.py: TTT2_RECHECK_TEXTURES=1 = every texture is re-hashed (finds writes without notice)
        static const bool recheck = std::getenv("TTT2_RECHECK_TEXTURES") != nullptr;
        if (recheck) {
            for (auto& [key, t] : textures_) t->dirty = true;
        }
        return;
    }
    mark_textures_dirty(address, uint64_t{address} + size);
"""),
    ("""    if (t.scale != 1) create_texture_image(t, 1);
    t.hash = h;
""", r"""    if (static const bool recheck = std::getenv("TTT2_RECHECK_TEXTURES") != nullptr; recheck && t.loaded != 0) {
        std::fprintf(stderr, "recheck: texture 0x%08X+0x%X %ux%u format 0x%03X reloads (frame %llu)\n", uint32_t{s.image},
                     uint32_t{s.image_size}, r.width, r.height, r.format, static_cast<unsigned long long>(frame_number_));
    }
    if (t.scale != 1) create_texture_image(t, 1);
    t.hash = h;
"""),
])

edit("os/coreinit_misc.cpp", [
    ("""GuestAddress OSBlockMove(GuestAddress dst, GuestAddress src, uint32_t size, bool) {
    std::memmove(dst.as<uint8_t>(), src.as<uint8_t>(), size);
    return dst;
}

GuestAddress OSBlockSet(GuestAddress dst, uint32_t value, uint32_t size) {
    std::memset(dst.as<uint8_t>(), static_cast<int>(value), size);
    return dst;
}

GuestAddress guest_memcpy(GuestAddress dst, GuestAddress src, uint32_t size) {
    std::memcpy(dst.as<uint8_t>(), src.as<uint8_t>(), size);
    return dst;
}
GuestAddress guest_memmove(GuestAddress dst, GuestAddress src, uint32_t size) {
    std::memmove(dst.as<uint8_t>(), src.as<uint8_t>(), size);
    return dst;
}
GuestAddress guest_memset(GuestAddress dst, int32_t value, uint32_t size) {
    std::memset(dst.as<uint8_t>(), value, size);
    return dst;
}
""", """// port/patch_texture_stores.py: these run here, not in guest code, so the renderer hears of what they write into
// a texture (gpu::cpu_stored): titles fill textures with them and send no flush (Mario Kart 8's glyph texture).
GuestAddress OSBlockMove(GuestAddress dst, GuestAddress src, uint32_t size, bool flush) {
    std::memmove(dst.as<uint8_t>(), src.as<uint8_t>(), size);
    if (flush) {
        gpu::cpu_wrote(dst.value, size);
    } else {
        gpu::cpu_stored(dst.value, size);
    }
    return dst;
}

GuestAddress OSBlockSet(GuestAddress dst, uint32_t value, uint32_t size) {
    std::memset(dst.as<uint8_t>(), static_cast<int>(value), size);
    gpu::cpu_stored(dst.value, size);
    return dst;
}

GuestAddress guest_memcpy(GuestAddress dst, GuestAddress src, uint32_t size) {
    std::memcpy(dst.as<uint8_t>(), src.as<uint8_t>(), size);
    gpu::cpu_stored(dst.value, size);
    return dst;
}
GuestAddress guest_memmove(GuestAddress dst, GuestAddress src, uint32_t size) {
    std::memmove(dst.as<uint8_t>(), src.as<uint8_t>(), size);
    gpu::cpu_stored(dst.value, size);
    return dst;
}
GuestAddress guest_memset(GuestAddress dst, int32_t value, uint32_t size) {
    std::memset(dst.as<uint8_t>(), value, size);
    gpu::cpu_stored(dst.value, size);
    return dst;
}
"""),
    ("""    std::memset(guest_pointer(begin), 0, end - begin);
""", """    std::memset(guest_pointer(begin), 0, end - begin);
    gpu::cpu_stored(begin, end - begin); // port/patch_texture_stores.py
"""),
])
