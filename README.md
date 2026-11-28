# Super Mario 3D World (Wii U): native build, work in progress

An attempt to run the Wii U game as a native PC program by static recompilation: the game's PowerPC code is
translated to C++ ahead of time and runs on a reimplementation of the Wii U's system libraries. No emulator.

> **No game files are included.** You need your own dump of the game (Europe, title `0005000010145D00`, v0),
> unpacked to `code/`, `content/`, `meta/`. The translated C++ and the program built from it contain the game's
> code: do not share them. Not affiliated with or endorsed by Nintendo.

## Selbst bauen / Build it yourself

One command builds the native program from **your own dump** of Super Mario 3D World. Nothing from the game is in this repository
or downloaded by the scripts: the game's code (RedCarpet.rpx) is translated to C++ and compiled on your computer.
*Ein Befehl baut das native Programm aus deinem eigenen Dump; nichts vom Spiel ist hier enthalten oder wird geladen.*

**You need / Du brauchst**
- your own dump of the game, **unpacked**: a folder with `code/`, `content/`, `meta/` (as Cemu or a Wii U dumper
  such as Dumpling gives it; `.wua`/`.wud` images must be unpacked first). Tested with Europe
  (0005000010145D00); other versions are translated from your files the same way and may work.
- Windows 10/11 64-bit or Linux x86-64; a CPU with AVX2/FMA (Intel Haswell, AMD Zen or newer); a GPU with a Vulkan driver.
- internet for the build tools and the pinned sources (Smash4PC `f145e7f`, ZArchive, addrlib, Vulkan-Headers from GitHub).
- about **2 GB** free in this folder (plus about 3 GB for MSYS2 on Windows) and 8 GB of RAM or more.
- time: about **5-15 minutes** for the first build on an 8-core PC; a second run only redoes what changed.

**Miis / Mii-Dateien.** Visible Miis need the Mii resource title (`0005001B-10056000`, files `FFLRes*.dat`) from **your own Wii U** — it is not part of the game, not in this repository and never downloaded. The game runs without it; only Miis are missing. Give the setup a Cemu-style `mlc01/sys` folder that holds `title/0005001b/10056000/content/` (`-SysDir` on Windows, `--sys` on Linux); it is written into the starter as `CAFE_SYS_DIR` and only read.
*Deutsch:* Sichtbare Miis brauchen den Mii-Systemtitel deiner **eigenen** Wii U (z. B. aus Cemus `mlc01/sys`), angegeben mit `-SysDir` bzw. `--sys`. Er ist nicht im Spiel-Dump und nicht hier enthalten.

**Windows** (PowerShell):

```powershell
git clone https://github.com/SirWinstonChurchillTheFirst/super-mario-3d-world-native
cd super-mario-3d-world-native
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -GameDir "D:\Games\Super Mario 3D World" -SysDir "D:\Cemu\mlc01\sys"
.\play\Start.bat
```

It installs [MSYS2](https://www.msys2.org) with winget if it is missing and the build packages into its CLANG64
environment with pacman (clang, lld, cmake, ninja, Python, git, SDL3, Vulkan loader + headers, shaderc, zlib, zstd,
xz, DejaVu fonts). Without `-GameDir` it asks for the folder. `-Jobs N` limits the parallel compile jobs; the build
runs at low priority so the PC stays usable.

**Linux** (Debian/Ubuntu, Arch, Fedora; others: install the same packages yourself):

```bash
git clone https://github.com/SirWinstonChurchillTheFirst/super-mario-3d-world-native
cd super-mario-3d-world-native
./setup-linux.sh "/path/to/Super Mario 3D World" --sys ~/.local/share/Cemu/mlc01/sys
./play/start.sh
```

Missing packages are installed with sudo (apt: clang cmake ninja-build git python3 pkg-config zlib1g-dev libzstd-dev
libssl-dev libvulkan-dev libshaderc-dev fonts-dejavu-core, and libsdl3-dev where the distribution has it; without it
SDL 3.2.26 is built from source, e.g. on Ubuntu 24.04). `--jobs N` limits the compile jobs.

**What the setup does** (`tools/native-build.sh`, the same on both systems): checks your dump; clones
[Smash4PC](https://github.com/josiahg2502-glitch/Smash4PC) at `f145e7f` and the three pinned dependencies; applies
`port/upstream-local.patch` (all runtime/recompiler changes, made by the `port/patch_*.py` scripts in order); builds the
recompiler `cafe-recomp`; translates your `code/`; compiles runtime + translated game; and puts `cafegame`, a stand-in
font and the starter into `play/`. Everything it makes stays in `build/` and `play/` (both ignored by git): they hold
code translated from the game — **keep them for yourself, do not share them.**

The Wii U system font is not part of a game dump: DejaVu Sans stands in (`play/fonts/CafeStd.ttf`); put your console's
own `CafeStd.ttf` there to replace it. Saves go to `play/save/`. The system language follows your PC
(`CAFE_LANGUAGE=de|en|fr|...` overrides it).

**Getestet / tested (23 Nov 2026):** For this game the Windows setup's translation step was run on the tested dump: it gives the same code as the build that runs on the Batocera console (only the newer recompiler's `dcbf` lines differ); the complete build of this game through the scripts was not run yet. The same scripts were run end to end from an empty folder on 23 November 2026: Lost Levels and Mario Kart 8 on Windows 11, Lost Levels on Ubuntu 26.04 and on a fresh Ubuntu 24.04 (SDL3 built from source there), Mario Party 10 on Windows 11.

## Update 28 November 2026: no more shader hitches, the right light after a time-of-day change

- **Hitches while playing.** The shader cache key held state the translation never reads (texture slots the shader
  does not sample, raw output/input semantics), so the same shader was translated again and again on the draw thread
  (a player's log: 8,774 cache entries after 6 minutes). `port/patch_shader_key_canon.py` keys only what the
  translation reads (`TTT2_SHADER_KEY_CHECK=1` re-translates every hit and compares; `TTT2_SHADER_KEY_FULL=1` = old key).
  Console (Ryzen 3 4350GE), cave in 1-2: 59.35 -> 59.82 frames/s, slowest 10 s 55.1 -> 58.9; 1-1: 59.07 -> 59.81;
  about 670 instead of 2,000 shaders in the same run.
- **Wrong light after the time of day changed** (title demo: glaring white-cyan at night after sunset, dark walls at
  dusk). The scene is lit from small cube maps the CPU rewrites and flushes with `DCFlushRangeNoSync`, which did
  nothing here, so the textures were never re-read. It now tells the renderer like `DCFlushRange`
  (`port/patch_dcflush_nosync.py`). Checked against Cemu on the console.
- `TTT2_GUEST_DMABUF=1` is now set for this game on the console (`console/game-env`): frames over 25 ms in 170 s of
  play 31 -> 11. A 27-minute session on the console: 59.89 frames/s, slowest 10 s 59.0, memory flat.
- The runtime now carries the work done for Mario Kart 8 since 23 November (render-target eviction, texture
  retention, image pool, submit chunks, sound fixes); with all of it the console still gives 59.8 frames/s here.
- Known open: the HUD group at the top left in a level (lives, coins, green stars) is pale (about 30 %), Cemu shows it
  fully; the draws are right, the alpha comes from the game's layout state - cause not found yet.
- Measuring tools: `patch_frame_hist.py`, `patch_trace_shader_keys.py`.

## Update 23 November 2026: a real Wii Remote is a Wii Remote

Before, a Wii Remote (Linux kernel driver hid-wiimote) reached the game only through SDL as a "GamePad" with the
console menu's upright mapping: its A arrived as the Wii U's B, B as A, 1 and 2 as ZL and ZR (measured with a
stand-in remote on the console, `tools/ctl/vwii.py` + `tools/ctl/ctlrun.sh`, and the runtime's `TTT2_INPUT_RECORD`).

Now `CAFE_WIIMOTE=real` (`port/patch_wiimote_real.py`, set in `console/game-env/3dworld.env`) makes the runtime read
real Wii Remotes itself (buttons, accelerometer, pointer, Nunchuk) and hand them to the game as Wii Remotes on the
KPAD channels, while every other controller stays GamePad / Pro Controller. Checked on the console with the stand-in
remote: the game's controller screen shows the remote, button 2 joins and confirms, the opening plays (58 to 60
frames/s). The game drops all remotes at its title screen, as on the Wii U: the first button press connects the
remote again. Not checked with a real remote in the hand: tilt, shake, pointer.

Also fixed on the way: `KPADReadEx` on an empty channel now reports "no controller" (-2); it reported "no new
samples" (-1), and the game's controller library took all four channels for connected remotes.

`console/launch.sh` gives a remote that the runtime does not read (GamePad-only games, or no direct access) a sideways
mapping instead of the menu's upright one (`console/padfix.py --profil=quer-ab|quer|quer-kart`).

## Update 22 November 2026, afternoon: brightness as on the console

The picture was much too dark. The game declares its TV and GamePad scan buffers as sRGB (format 0x41A) but renders linear values into a 10-bit UNORM colour buffer; the console's copy into the scan buffer encodes them, and Cemu does the same. The runtime copied the bytes unchanged. Now the copy converts when the declared kind and the colour buffer's kind differ (`port/patch_scan_srgb.py`; `TTT2_SCAN_RAW=1` gives the old copy). Measured on the same title-screen shot: mean brightness 132 before, 177 after, Cemu 177 (0-255). Both presentation paths were checked to show the scan buffer unchanged (`tools/console_bright.sh`).

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
| Wii Remote (stand-in device on the console) | recognised as a Wii Remote, button 2 joins and starts the game; real remote, tilt and shake **not tested** |
| GamePad screen, everything after World 1-1 | **not tested** |
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
- `setup-windows.ps1`, `setup-linux.sh`, `tools/native-build.sh`, `game.conf`: the one-command build (above).
  `port/iter.sh` is the build-and-run loop used while porting.
- `tools/run_gpu.sh`, `tools/wincap_loop.py`: run the Windows build with scripted presses, record sound and frame
  times, photograph the window.
- `tools/rpxinfo.py`: prints facts about an RPX. `tools/win_build.sh`, `tools/quick.sh`: Windows build of one title and a
  run without a window that prints the next missing system function.
- `console/launch.sh`, `console/deploy.sh`, `console/install_entry.py`: start script and installer for a Batocera box
  (written for one particular setup with its own front end; not run yet).

## License

The files here are under the MIT license, as the projects they build on. Third-party code keeps its own license.
