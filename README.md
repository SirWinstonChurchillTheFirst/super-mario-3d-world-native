# Super Mario 3D World (Wii U): native build, work in progress

An attempt to run the Wii U game as a native PC program by static recompilation: the game's PowerPC code is
translated to C++ ahead of time and runs on a reimplementation of the Wii U's system libraries. No emulator.

> **No game files are included.** You need your own dump of the game (Europe, title `0005000010145D00`, v0),
> unpacked to `code/`, `content/`, `meta/`. The translated C++ and the program built from it contain the game's
> code: do not share them. Not affiliated with or endorsed by Nintendo.

## Status (19 November 2026): reaches World 1-1, barely tested

Tested on one PC (Windows 11, GeForce RTX 3070 Ti, 1280x720), with scripted button presses only.

| Step | State |
| --- | --- |
| Translate `RedCarpet.rpx` (54,051 functions, 3.05 million instructions; the file has no function names) | works |
| Build with the runtime | works on Windows (clang, MSYS2) and Linux |
| Controller notice, title screen, file select, character select | shown, look right |
| Opening scene | plays |
| World map | shown, looks right; Mario walks onto World 1-1 |
| World 1-1 | starts: level, Mario, timer and score are drawn; about 20 seconds seen, nothing played |
| Sound | present in a recording of the output (not listened to). Reverb, chorus and delay are not computed |
| Speed | the game's 60 frames/s are held; the renderer needs 1.5 to 3 ms per frame on that card |
| Controller, saving and loading, anything after the first seconds of World 1-1, GamePad screen | **not tested** |

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
- `port/game_main.cpp`: a game-neutral entry program. `port/os_extra.cpp`: system functions other titles need.
- `port/setup.sh GAME_FOLDER NAME`: the Linux build steps in order (written down from the steps done by hand; the
  script as a whole has not been run). `port/run.sh` starts the result. `port/iter.sh` is the build-and-run loop.
- `tools/run_gpu.sh`, `tools/wincap_loop.py`: run the Windows build with scripted presses, record sound and frame
  times, photograph the window.
- `tools/rpxinfo.py`: prints facts about an RPX.

The system font is not part of a game dump either: copy your console's `CafeStd.ttf` to `build-NAME/fonts/`;
until then DejaVu Sans stands in.

## License

The files here are under the MIT license, as the projects they build on. Third-party code keeps its own license.
