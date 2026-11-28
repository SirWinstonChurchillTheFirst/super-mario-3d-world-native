#!/usr/bin/env python3
r"""patch_ax_current_offset_ex.py RUNTIME_SRC_DIR : AXGetVoiceCurrentOffsetEx has TWO arguments and RETURNS the position.

Found while hunting the Mario Kart 8 "thump" (27 Nov): after patch_ax_stream_voice.py one loud crackle was left each
time the race music (a looping DSP-ADPCM wave, 13 s loop) jumped back to its loop start, from the second loop on.

Measured (TTT2_TRACE_AX=1 + a print of the 8 bytes of the loop-start frame each time the voice arrives there):
  first pass / first loop : 16 E8 D0 73 0E A8 89 46   (real frame: header 0x16)
  second loop and later   : 2F 83 86 CA 0E A8 89 46   (first 4 bytes replaced; header 0x2F = scale 2^15 -> the decoder
                                                       hits both rails for a whole frame)
The 4 new bytes are a number: 2 x sample address + the voice's position in nibbles, and they sit exactly at the address
the title passes as "samples" to the Ex calls. Cause: the runtime had
    uint32_t AXGetVoiceCurrentOffsetEx(voice, be<uint32_t>* offset, samples)   // guessed in patch_more_os.py
but the real call is
    uint32_t AXGetVoiceCurrentOffsetEx(AXVoice* voice, const void* samples)    // returns the offset (wut sndcore2/voice.h)
So the runtime took the title's SAMPLE ADDRESS for an output pointer and wrote 4 bytes of position into the sound data
(first frame header + 3 data bytes of whatever the title asked about: the start of a wave, later its loop start), used
whatever was left in r5 as the "samples" address, and returned 0, so the title always read "position 0".

Fix: two arguments, the position (relative to `samples`, in the voice's units, 32 bits like the console) is returned;
nothing is written to guest memory. Affects every title that asks for a voice position this way (nw::snd wave/stream
sounds: Mario Kart 8, 3D World, Tennis ...)."""
import sys

root = sys.argv[1] + "/"
MARK = "patch_ax_current_offset_ex"

path = root + "os/ax.cpp"
s = open(path, encoding="utf-8").read()
if MARK in s:
    print("already applied: os/ax.cpp")
    sys.exit(0)

old = """uint32_t AXGetVoiceCurrentOffsetEx(uint32_t vpb, be<uint32_t>* offset, uint32_t samples) {
    std::lock_guard lock(g_ax_mutex);
    Voice* v = voice_of(vpb);
    if (v == nullptr || offset == nullptr) return 0xFFFFFFFFu;
    int64_t value = v->format == kAdpcm ? sample_to_nibble(v->cursor) : v->cursor;
    if (samples != 0 && samples != v->samples) {
        const int64_t bytes = int64_t{samples} - int64_t{v->samples};
        value -= v->format == kPcm16 ? floor_div(bytes, 2) : v->format == kAdpcm ? bytes * 2 : bytes;
    }
    *offset = static_cast<uint32_t>(value);
    return 0;
}
"""
new = """// port/patch_ax_current_offset_ex.py: (voice, samples) -> the position relative to `samples`. It has no output
// pointer: the old three-argument guess wrote the position INTO the title's sample data and returned 0.
uint32_t AXGetVoiceCurrentOffsetEx(uint32_t vpb, uint32_t samples) {
    std::lock_guard lock(g_ax_mutex);
    Voice* v = voice_of(vpb);
    if (v == nullptr) return 0;
    int64_t value = v->format == kAdpcm ? sample_to_nibble(v->cursor) : v->cursor;
    if (samples != 0 && samples != v->samples) {
        const int64_t bytes = int64_t{samples} - int64_t{v->samples};
        value -= v->format == kPcm16 ? floor_div(bytes, 2) : v->format == kAdpcm ? bytes * 2 : bytes;
    }
    return static_cast<uint32_t>(value);
}
"""
if s.count(old) != 1:
    sys.exit(f"{MARK}: os/ax.cpp: AXGetVoiceCurrentOffsetEx not found as expected ({s.count(old)})")
open(path, "w", encoding="utf-8", newline="\n").write(s.replace(old, new))
print("patched: os/ax.cpp")
