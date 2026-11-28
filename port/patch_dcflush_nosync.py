#!/usr/bin/env python3
"""patch_dcflush_nosync.py SMASH4_DIR (or its runtime folder) : DCFlushRangeNoSync tells the renderer that the CPU wrote that memory (as DCFlushRange).

Super Mario 3D World (title demo and levels) lights the scene through small cube maps (16x16, BC3, 0x37908000 and
0x3790F800 on the PC) that the CPU rewrites while the time of day changes (day -> sunset -> night -> dusk in the title
demo): it writes the new texels and flushes them with DCFlushRangeNoSync, then sends only the whole-memory
GX2Invalidate every frame (which the runtime ignores on purpose, it comes every frame). DCFlushRangeNoSync was a
no-op, so the renderer never re-read the cube maps: the scene kept the light of an earlier phase - night after sunset
glaring white-cyan, sunset after night dark navy walls and a dark glass pipe (Cemu: light walls). TTT2_RECHECK_TEXTURES=1
(every texture re-hashed) showed the right picture, i.e. the data in guest memory was right, only the notice was missing.
On the console "NoSync" only leaves out the final sync instruction - the lines are still written back for the GPU - so
it is taken like DCFlushRange (patch_dcflush.py): textures over the range are re-checked (by hash) when next used."""
import os
import sys
base = sys.argv[1]  # the smash4 tree or its runtime folder
p = base + ('/runtime/src/os/coreinit_misc.cpp' if os.path.isdir(base + '/runtime/src') else '/src/os/coreinit_misc.cpp')
s = open(p, encoding='utf-8').read()
if 'patch_dcflush_nosync' in s:
    print('patch_dcflush_nosync: already there'); sys.exit(0)
old = 'CAFE_EXPORT(coreinit, DCFlushRangeNoSync, no_op);\n'
new = ('// port/patch_dcflush_nosync.py: NoSync still writes the lines back for the GPU = the same notice as DCFlushRange.\n'
       'CAFE_EXPORT(coreinit, DCFlushRangeNoSync, DCFlushRange);\n')
if s.count(old) != 1 or 'void DCFlushRange(uint32_t address, uint32_t size) { gpu::cpu_wrote(address, size); }' not in s:
    sys.exit('patch_dcflush_nosync: text not found (needs patch_dcflush.py first)')
s = s.replace(old, new, 1)
open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patch_dcflush_nosync: done')
