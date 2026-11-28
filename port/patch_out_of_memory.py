#!/usr/bin/env python3
r"""patch_out_of_memory.py RUNTIME_SRC_DIR : running out of memory ends with a clear message, and no empty picture is left.

Seen by the testers of Mario Kart 8 (win/run/mk8-pilz-blumen-r2/wpa.log, wpb.log, mk8-stern-spezial-r2/li3.log) while
4-5 instances of the game (about 3 GB each) ran at once on one PC:
  "libc++abi: terminating due to uncaught exception of type std::bad_alloc: std::bad_alloc"
  "ttt2: Vulkan: vkAllocateMemory(device, &mai, nullptr, &mem) failed with -2 (.../context.cpp:366)"
and a capture picture tv_0042.png of 0 bytes (write_png had opened the file, then its buffer could not be allocated).
Neither line says what happened or what to do, and the first one comes from the C++ runtime without any state.

Now (nothing title specific):
- diagnostics.cpp: install_fault_handler() also installs a new-handler and a terminate handler. A failed operator new
  ends through fatal() with "out of memory", the memory this process holds and what the system has left, and the hint
  that other programs / other running copies take the memory. Any other uncaught C++ exception is named with its
  what() text and the guest state instead of a bare abort. report_host_memory() prints the figures (Windows:
  private bytes, working set, free physical memory, free commit; Linux: VmRSS/VmSize, MemAvailable).
- gpu/vulkan/context.cpp: VK_ERROR_OUT_OF_HOST_MEMORY (-1) and VK_ERROR_OUT_OF_DEVICE_MEMORY (-2) are named as what
  they are (main memory / graphics memory used up) with the same figures, plus the call and place as before.
- gpu/vulkan/png.cpp: the picture is built in memory first and the file is opened only then; a file that could not
  be written completely is removed. So a failed capture leaves no 0-byte or cut-off PNG.
Exit code stays 70 (fatal). RUNTIME_SRC_DIR = <tree>/runtime/src."""
import sys

root = sys.argv[1].rstrip("/") + "/"
MARK = "patch_out_of_memory"


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


edit("../include/cafe/runtime.h", [
    ("""void install_fault_handler();
""", """void install_fault_handler();
// port/patch_out_of_memory.py: one or two stderr lines with the memory this process holds and what the host has left.
void report_host_memory();
"""),
])

edit("diagnostics.cpp", [
    ("""#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
""", """#ifdef _WIN32
#include <windows.h>
#include <psapi.h> // port/patch_out_of_memory.py
#else
#include <dlfcn.h>
"""),
    ("""#include <cstdlib>
#include <vector>

namespace cafe {
""", """#include <cstdlib>
#include <atomic> // port/patch_out_of_memory.py
#include <cstring>
#include <exception>
#include <new>
#include <thread>
#include <vector>

#ifdef _WIN32
// port/patch_out_of_memory.py: the kernel32 entry (psapi.h maps GetProcessMemoryInfo to it only for PSAPI_VERSION 2).
extern "C" BOOL WINAPI K32GetProcessMemoryInfo(HANDLE, PPROCESS_MEMORY_COUNTERS, DWORD);
#endif

namespace cafe {
"""),
    ("""void install_fault_handler() {
#ifdef _WIN32
""", r"""// port/patch_out_of_memory.py: what the process holds and what the host has left. Uses no heap on Windows; on Linux
// only what fopen needs (if even that fails the lines are simply missing).
void report_host_memory() {
    const double mb = 1024.0 * 1024.0;
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS_EX pmc{};
    pmc.cb = sizeof pmc;
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PPROCESS_MEMORY_COUNTERS>(&pmc), sizeof pmc)) {
        std::fprintf(stderr, "ttt2: memory: this process holds %.0f MB (working set %.0f MB, peak %.0f MB)\n",
                     pmc.PrivateUsage / mb, pmc.WorkingSetSize / mb, pmc.PeakWorkingSetSize / mb);
    }
    MEMORYSTATUSEX ms{};
    ms.dwLength = sizeof ms;
    if (GlobalMemoryStatusEx(&ms)) {
        std::fprintf(stderr, "ttt2: memory: the PC has %.0f of %.0f MB main memory free, %.0f of %.0f MB still to hand out "
                             "(with the page file)\n",
                     ms.ullAvailPhys / mb, ms.ullTotalPhys / mb, ms.ullAvailPageFile / mb, ms.ullTotalPageFile / mb);
    }
#else
    const auto show = [](const char* path, const char* const* keys, const char* what) {
        std::FILE* f = std::fopen(path, "r");
        if (!f) return;
        char line[160];
        while (std::fgets(line, sizeof line, f)) {
            for (const char* const* k = keys; *k; ++k) {
                if (std::strncmp(line, *k, std::strlen(*k)) != 0) continue;
                line[std::strcspn(line, "\n")] = 0;
                std::fprintf(stderr, "ttt2: memory: %s %s\n", what, line);
            }
        }
        std::fclose(f);
    };
    static const char* const kSelf[] = {"VmRSS:", "VmSize:", nullptr};
    static const char* const kHost[] = {"MemAvailable:", "SwapFree:", nullptr};
    show("/proc/self/status", kSelf, "this process");
    show("/proc/meminfo", kHost, "the system");
    (void)mb;
#endif
}

namespace {
// port/patch_out_of_memory.py: operator new found no memory. Without this the C++ runtime ends the program with
// "terminating due to uncaught exception of type std::bad_alloc" and nothing else.
[[noreturn]] void out_of_host_memory() {
    static std::atomic_flag once = ATOMIC_FLAG_INIT;
    if (once.test_and_set()) { // a second thread failing while the first one reports
        for (;;) std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    std::fflush(stdout);
    std::fprintf(stderr, "\nttt2: OUT OF MEMORY: the system gave this program no more main memory.\n");
    report_host_memory();
    fatal("out of memory - close other programs (or other running copies of this game) and start again");
}

// Any other C++ exception nobody caught: name it and show the guest state.
[[noreturn]] void uncaught_exception() {
    const char* what = "unknown";
    static char text[256];
    if (std::exception_ptr e = std::current_exception()) {
        try {
            std::rethrow_exception(e);
        } catch (const std::bad_alloc&) {
            out_of_host_memory();
        } catch (const std::exception& ex) {
            std::snprintf(text, sizeof text, "%s", ex.what());
            what = text;
        } catch (...) {
        }
    } else {
        what = "std::terminate called without an exception";
    }
    fatal("uncaught C++ exception: %s", what);
}
} // namespace

void install_fault_handler() {
    std::set_new_handler(out_of_host_memory); // port/patch_out_of_memory.py
    std::set_terminate(uncaught_exception);
#ifdef _WIN32
"""),
])

edit("gpu/vulkan/context.cpp", [
    ("""    if (result == VK_ERROR_DEVICE_LOST) report_device_fault();
""", r"""    if (result == VK_ERROR_DEVICE_LOST) report_device_fault();
    // port/patch_out_of_memory.py: say what -1 / -2 mean instead of a bare number.
    if (result == VK_ERROR_OUT_OF_DEVICE_MEMORY || result == VK_ERROR_OUT_OF_HOST_MEMORY) {
        const bool device = result == VK_ERROR_OUT_OF_DEVICE_MEMORY;
        std::fflush(stdout);
        std::fprintf(stderr, "\nttt2: OUT OF %s MEMORY: the graphics driver could not get more %s memory.\n",
                     device ? "GRAPHICS" : "MAIN", device ? "graphics (video)" : "main");
        report_host_memory();
        // Drivers answer "device memory" too when the process gets no more main memory (seen on NVIDIA under a commit
        // limit), so the text names both and the figures above show which one it was.
        fatal("out of %s memory - close other programs (or other running copies of this game) and start again; "
              "Vulkan: %s failed with %d (%s:%d)",
              device ? "graphics (or main)" : "main", expression, static_cast<int>(result), file, line);
    }
"""),
])

edit("gpu/vulkan/png.cpp", [
    ("""#include <cstdio>
#include <vector>
""", """#include <algorithm>
#include <cstdio>
#include <vector>
"""),
    ("""void chunk(FILE* f, const char* type, const std::vector<uint8_t>& data) {
    std::vector<uint8_t> c;
    put32(c, static_cast<uint32_t>(data.size()));
    c.insert(c.end(), type, type + 4);
    c.insert(c.end(), data.begin(), data.end());
    put32(c, crc32(c.data() + 4, c.size() - 4));
    std::fwrite(c.data(), 1, c.size(), f);
}
""", """// port/patch_out_of_memory.py: chunks are appended to one buffer; the file is opened only when all of it exists.
void chunk(std::vector<uint8_t>& out, const char* type, const std::vector<uint8_t>& data) {
    const size_t at = out.size();
    put32(out, static_cast<uint32_t>(data.size()));
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    put32(out, crc32(out.data() + at + 4, out.size() - at - 4));
}
"""),
    (r"""    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    static const uint8_t kSignature[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    std::fwrite(kSignature, 1, 8, f);
""", r"""    static const uint8_t kSignature[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    std::vector<uint8_t> f(kSignature, kSignature + 8);
"""),
    ("""    const bool written = !std::ferror(f);
    return std::fclose(f) == 0 && written;
""", r"""    // port/patch_out_of_memory.py: everything above only used memory. Write it in one go; a file that did not take
    // all of it (disk full, ...) is removed, so no empty or cut-off picture stays behind.
    FILE* file = std::fopen(path.c_str(), "wb");
    if (!file) return false;
    const bool written = std::fwrite(f.data(), 1, f.size(), file) == f.size();
    const bool closed = std::fclose(file) == 0;
    if (!written || !closed) {
        std::remove(path.c_str());
        std::fprintf(stderr, "ttt2: could not write %s completely (disk full?), removed it\n", path.c_str());
        return false;
    }
    return true;
"""),
])
