#!/usr/bin/env python3
"""patch_image_pool.py RUNTIME_SRC_DIR (.../runtime/src) : image memory from shared 64 MB blocks.

Every image (render target, texture, copy) had its own vkAllocateMemory, so its own kernel buffer object: Mario Kart 8
makes ~4800 targets and keeps ~500-1000 textures (made again after 10 s unused), several new ones a second in a race.
Each allocation is a kernel call that maps and clears memory, and with buffer device addresses every submission
carries every buffer object.

Images up to 8 MB take their memory from 64 MB blocks of the same memory type (first fit,
neighbouring free ranges joined when an image is destroyed); larger images, and any allocation when a new block
cannot be made, keep their own memory. Blocks stay allocated. TTT2_IMAGE_POOL=0: old behaviour."""
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

edit(d + "context.h", "patch_image_pool", [
    ("    VkDeviceMemory allocate_image_memory(VkImage image);" + NL,
     "    VkDeviceMemory allocate_image_memory(VkImage image);" + NL +
     "    // port/patch_image_pool.py: from a shared block (block >= 0, at offset) or its own memory (block -1)" + NL +
     "    VkDeviceMemory allocate_image_memory(VkImage image, VkDeviceSize& offset, VkDeviceSize& size, int32_t& block);" + NL +
     "    void free_image_memory(VkDeviceMemory memory, VkDeviceSize offset, VkDeviceSize size, int32_t block);" + NL),
])

IMPL = r'''
// port/patch_image_pool.py: image memory from shared blocks (TTT2_IMAGE_POOL=0: each its own).
namespace {
struct ImageBlock {
    VkDeviceMemory memory = VK_NULL_HANDLE;
    uint32_t type = 0;
    std::map<VkDeviceSize, VkDeviceSize> free; // offset -> size
};
std::vector<ImageBlock> g_image_blocks;
std::mutex g_image_pool_mutex;
constexpr VkDeviceSize kImageBlockBytes = 64ull << 20;
constexpr VkDeviceSize kImagePooledMax = 8ull << 20;
bool image_pool_enabled() {
    static const bool on = [] {
        const char* v = std::getenv("TTT2_IMAGE_POOL");
        const bool yes = v == nullptr || *v != '0';
        if (yes) std::fprintf(stderr, "ttt2: GPU: image memory from 64 MB blocks (TTT2_IMAGE_POOL)\n");
        return yes;
    }();
    return on;
}
// First fit in the blocks of `type`; -1 when none has room.
int32_t take_image_range(uint32_t type, VkDeviceSize size, VkDeviceSize align, VkDeviceSize& offset) {
    for (size_t b = 0; b < g_image_blocks.size(); ++b) {
        ImageBlock& ib = g_image_blocks[b];
        if (ib.type != type) continue;
        for (auto it = ib.free.begin(); it != ib.free.end(); ++it) {
            const VkDeviceSize start = it->first, end = it->first + it->second;
            const VkDeviceSize at = (start + align - 1) / align * align;
            if (at + size > end) continue;
            ib.free.erase(it);
            if (at > start) ib.free[start] = at - start;
            if (at + size < end) ib.free[at + size] = end - (at + size);
            offset = at;
            return static_cast<int32_t>(b);
        }
    }
    return -1;
}
} // namespace

VkDeviceMemory Context::allocate_image_memory(VkImage image, VkDeviceSize& offset, VkDeviceSize& size, int32_t& block) {
    offset = 0;
    size = 0;
    block = -1;
    if (!image_pool_enabled()) return allocate_image_memory(image);
    VkMemoryRequirements req;
    vkGetImageMemoryRequirements(device, image, &req);
    if (req.size > kImagePooledMax) return allocate_image_memory(image);
    const uint32_t type = memory_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    const VkDeviceSize align = std::max<VkDeviceSize>(req.alignment, 1);
    std::lock_guard lock(g_image_pool_mutex);
    int32_t b = take_image_range(type, req.size, align, offset);
    if (b < 0) {
        ImageBlock nb;
        nb.type = type;
        VkMemoryAllocateInfo mai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        mai.allocationSize = kImageBlockBytes;
        mai.memoryTypeIndex = type;
        if (vkAllocateMemory(device, &mai, nullptr, &nb.memory) != VK_SUCCESS) return allocate_image_memory(image);
        nb.free[0] = kImageBlockBytes;
        g_image_blocks.push_back(std::move(nb));
        static uint32_t said = 0;
        if (said++ < 64) {
            std::fprintf(stderr, "ttt2: GPU: image memory block %zu (memory type %u)\n", g_image_blocks.size(), type);
        }
        b = take_image_range(type, req.size, align, offset);
        if (b < 0) return allocate_image_memory(image);
    }
    VK_CHECK(vkBindImageMemory(device, image, g_image_blocks[b].memory, offset));
    size = req.size;
    block = b;
    return g_image_blocks[b].memory;
}

void Context::free_image_memory(VkDeviceMemory memory, VkDeviceSize offset, VkDeviceSize size, int32_t block) {
    if (block < 0) {
        vkFreeMemory(device, memory, nullptr);
        return;
    }
    std::lock_guard lock(g_image_pool_mutex);
    auto& f = g_image_blocks[static_cast<size_t>(block)].free;
    auto it = f.emplace(offset, size).first;
    if (auto next = std::next(it); next != f.end() && it->first + it->second == next->first) {
        it->second += next->second;
        f.erase(next);
    }
    if (it != f.begin()) {
        auto prev = std::prev(it);
        if (prev->first + prev->second == it->first) {
            prev->second += it->second;
            f.erase(it);
        }
    }
}
'''

edit(d + "context.cpp", "patch_image_pool", [
    ("#include <string>" + NL,
     "#include <string>" + NL + "#include <iterator>" + NL + "#include <map>" + NL + "#include <mutex> // port/patch_image_pool.py" + NL),
    ("// ---------------------------------------------------------- guest memory" + NL,
     IMPL.lstrip("\n") + NL + "// ---------------------------------------------------------- guest memory" + NL),
])

edit(d + "renderer.h", "patch_image_pool", [
    ("struct Image {" + NL +
     "    VkImage image = VK_NULL_HANDLE;" + NL +
     "    VkDeviceMemory memory = VK_NULL_HANDLE;" + NL,
     "struct Image {" + NL +
     "    VkImage image = VK_NULL_HANDLE;" + NL +
     "    VkDeviceMemory memory = VK_NULL_HANDLE;" + NL +
     "    VkDeviceSize memory_offset = 0, memory_size = 0; // port/patch_image_pool.py" + NL +
     "    int32_t memory_block = -1;                       // -1: its own memory" + NL),
])

edit(d + "renderer.cpp", "patch_image_pool", [
    ("    img.memory = ctx_.allocate_image_memory(img.image);" + NL,
     "    img.memory = ctx_.allocate_image_memory(img.image, img.memory_offset, img.memory_size, img.memory_block); // port/patch_image_pool.py" + NL),
    ("    if (img.memory) vkFreeMemory(ctx_.device, img.memory, nullptr);" + NL,
     "    if (img.memory) ctx_.free_image_memory(img.memory, img.memory_offset, img.memory_size, img.memory_block); // port/patch_image_pool.py" + NL),
])
