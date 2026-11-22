# Super Mario 3D World (Wii U): native build, work in progress

An attempt to run the Wii U game as a native PC program by static recompilation: the game's PowerPC code is
translated to C++ ahead of time and runs on a reimplementation of the Wii U's system libraries. No emulator.

> **No game files are included.** You need your own dump of the game (Europe, title `0005000010145D00`, v0),
> unpacked to `code/`, `content/`, `meta/`. The translated C++ and the program built from it contain the game's
> code: do not share them. Not affiliated with or endorsed by Nintendo.

## Status (22 November 2026): World 1-1 is played by script on the PC and on the console, at 60 frames/s on both

Tested on one PC (Windows 11, GeForce RTX 3070 Ti, 1280x720), with scripted button presses only.

| Step | State |
| --- | --- |
| Translate `RedCarpet.rpx` (54,051 functions, 3.05 million instructions; the file has no function names) | works |
| Build with the runtime | works on Windows (clang, MSYS2) and Linux |
| Controller notice, title screen, file select, character select | shown, look right |
| Opening scene | plays |
| World map | shown, looks right; Mario walks onto World 1-1 |
| World 1-1 | played by a blind input script for about two minutes: running, jumping, Goombas, clear pipes, shadows, falling off ("Too Bad!") and the restart of the level all look right. The level was **not finished** |
| Sound | present in a recording of the output (not listened to). Reverb, chorus and delay are not computed |
| Speed | 59 to 60 frames/s without picture captures (title and opening measured that way), single late pictures of 15 to 70 ms at scene changes; the renderer needs 1.5 to 4 ms per frame on that card. Each picture capture of the test tools costs about 0.1 s, so captured runs show 56 to 58 |
| Saving and loading | **not tested**: the game saves when a level is finished, and the script does not finish one |
| Controller, GamePad screen, everything after World 1-1 | **not tested** |
| Linux program on a small AMD box (Batocera, Ryzen 3 PRO 4350GE, Vega 6, 1080p TV) | **runs at 59 to 60 frames/s** (22 November): installed with `console/deploy.sh`, started through the menu, World 1-1 reached by script, picture right, the game's sound stream plays (not listened to). It held 30 before: the title waits every frame for a GPU timestamp, and the runtime only lets one retire after it has copied the small render targets back into guest memory. Those copies were read from uncached (write-combined) memory on this APU: 140 KB took 8.4 ms a frame. With cached staging memory (`port/patch_writeback_cached.py`) they take 0.15 to 0.3 ms and the title waits 9 ms instead of 18 (measured with `TTT2_WAIT_LOG=1`, `port/patch_waitlog.py`). Also needed earlier: `TTT2_SCALE=1` (set by `console/launch.sh`) and `port/patch_night4.py`. The held Alt+F4 after quitting is now released by the console's menu program before and after every game (cause: Batocera's `hotkeygen --send exit` removes its short-lived keyboard right after the release, which can be lost); `launch.sh` still checks too |

Known gaps: Mii data files of the console (`FFLRes*.dat`) are not part of a game dump and are missing; occlusion
queries are not run (conditional draws are always drawn); Miiverse and online services answer "offline".

## What is here

Only what was added for this game and its siblings, on top of
[Smash 4 PC](https://github.com/josiahg2502-glitch/Smash4PC) at `f145e7f` (MIT), which is built on
[Tekken Tag 2 Ultimate Edition](https://github.com/Petexy/Tekken-Tag-2-Ultimate-Edition)'s cafe-recomp and
Wii U runtime by Petexy (MIT). All credit for the recompiler and the runtime goes to them.

- `port/upstream-local.patch`: all changes to that runtime and recompiler. `port/patch_*.py` are the scripts that
  made them, each with the reason in its header. The one this game needed most:
  `patch_fetch_2101010.py` (vertex data format 2_10_10_10 in the shader translator; without it the scene's models
  were not drawn).
  The 2_10_10_10 bit layout was checked against Cemu's source (read as a reference only): X in bits 0-9, Y 10-19,
  Z 20-29, W 30-31.
- `port/game_main.cpp`: a game-neutral entry program. `port/os_extra.cpp`: system functions other titles need.
- `port/setup.sh GAME_FOLDER NAME`: the Linux build steps in order (written down from the steps done by hand; the
  script as a whole has not been run). `port/run.sh` starts the result. `port/iter.sh` is the build-and-run loop.
- `tools/run_gpu.sh`, `tools/wincap_loop.py`: run the Windows build with scripted presses, record sound and frame
  times, photograph the window.
- `tools/rpxinfo.py`: prints facts about an RPX. `tools/win_build.sh`, `tools/quick.sh`: Windows build of one title and a
  run without a window that prints the next missing system function.
- `console/launch.sh`, `console/deploy.sh`, `console/install_entry.py`: start script and installer for a Batocera box
  (written for one particular setup with its own front end; not run yet).

The system font is not part of a game dump either: copy your console's `CafeStd.ttf` to `build-NAME/fonts/`;
until then DejaVu Sans stands in.

## License

The files here are under the MIT license, as the projects they build on. Third-party code keeps its own license.
