#!/usr/bin/env python3
"""patch_cpu_profile_top.py RUNTIME_SRC_DIR (.../runtime/src) : TTT2_CPU_PROFILE_TOP=<n> addresses in the cpuprof list
(default 60 as before), so a run can print enough of them to add them up per function afterwards (addr2line -f)."""
import sys

p = sys.argv[1] + "/gpu/command_processor.cpp"
s = open(p, encoding="utf-8").read()
if "patch_cpu_profile_top" in s:
    print("already applied"); sys.exit(0)
old = "        for (size_t i = 0; i < top.size() && i < 60; ++i) {\n"
assert s.count(old) == 1
s = s.replace(old, "        const char* top_env = std::getenv(\"TTT2_CPU_PROFILE_TOP\"); // port/patch_cpu_profile_top.py\n"
                   "        const size_t top_n = top_env ? static_cast<size_t>(std::max(1, std::atoi(top_env))) : 60;\n"
                   "        for (size_t i = 0; i < top.size() && i < top_n; ++i) {\n")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched", p)
