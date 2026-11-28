#!/usr/bin/env python3
r"""patch_ax_offsets.py RUNTIME_SRC_DIR : AX voice positions are signed (a loop/end address may lie BELOW the voice's
sample address).

A voice keeps its positions (loop start, end, cursor) relative to its sample address. The "Ex" calls
(AXSetVoiceLoopOffsetEx / EndOffsetEx / CurrentOffsetEx) give an offset relative to a sample address of their own,
which the runtime rebases onto the voice's. That rebasing was unsigned: for DSP-ADPCM the nibble offset
"offset + 2 * (address - voice address)" was cut to 32 bits, so an address below the voice's gave a nibble offset near
2^32, i.e. a byte position of voice address + 2^31 + ... - the mixer then read unmapped guest memory and the program
ended with "guest memory fault".

Measured in Mario Kart 8 (win/run/gfxfix7, TTT2_TRACE_AX=1): its streamed music (nw::snd stream player) is one looping
ADPCM voice per channel over a ring of 10 buffers of 0x2900 bytes. Normally the voice is set up on buffer 0 (the lowest
address), so every later loop/end address is at or above the voice's. After a stream underrun (the loader thread did
not deliver for a few seconds: disk or machine busy) the player sets the voices up again ON THE BUFFER IT IS AT, e.g.
buffer 9 (AXSetVoiceOffsets ... data 39132DC0), and the next loop target is buffer 0 at 3911BCC0, below it:
"guest memory fault: access to unmapped guest address 0xB911BCC0" = buffer 0 + 2^31, in ax_main (the two crashes of
the report had exactly this address after a 3 s stall). Reproduced at will by freezing the title's sound task thread
for 7 s during a race (win/run/gfxfix7/stall.sh).

Fix: positions are int64 and all conversions (nibbles <-> samples, frame / index of the ADPCM decoder, byte address of
PCM samples) round toward minus infinity, so positions below the voice's sample address work like those above.
TTT2_TRACE_AX=1 now also prints the Ex calls."""
import sys

root = sys.argv[1] + "/"
MARK = "patch_ax_offsets"


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


edit("os/ax.cpp", [
    ("""    uint64_t loop_start = 0, end = 0;
    uint64_t cursor = 0; // the next sample to read
""", """    // port/patch_ax_offsets.py: relative to `samples` and signed - an "Ex" call may place a position below it.
    int64_t loop_start = 0, end = 0;
    int64_t cursor = 0; // the next sample to read
"""),
    ("""uint64_t nibble_to_sample(uint32_t nibble) { return uint64_t{nibble / 16} * 14 + (nibble % 16 < 2 ? 0 : nibble % 16 - 2); }
uint32_t sample_to_nibble(uint64_t sample) { return static_cast<uint32_t>(sample / 14 * 16 + sample % 14 + 2); }

uint64_t to_sample(const Voice& v, uint32_t offset) {
    return v.format == kAdpcm ? nibble_to_sample(offset) : offset;
}
uint32_t from_sample(const Voice& v, uint64_t sample) {
    return v.format == kAdpcm ? sample_to_nibble(sample) : static_cast<uint32_t>(sample);
}
""", """// Positions may be negative (below the voice's sample address): divisions round toward minus infinity.
int64_t floor_div(int64_t a, int64_t b) { return a / b - (a % b < 0 ? 1 : 0); }
int64_t nibble_to_sample(int64_t nibble) {
    const int64_t frame = floor_div(nibble, 16), rest = nibble - frame * 16;
    return frame * 14 + (rest < 2 ? 0 : rest - 2);
}
int64_t sample_to_nibble(int64_t sample) {
    const int64_t frame = floor_div(sample, 14);
    return frame * 16 + (sample - frame * 14) + 2;
}

int64_t to_sample(const Voice& v, int64_t offset) {
    return v.format == kAdpcm ? nibble_to_sample(offset) : offset;
}
// The offset a title reads back: 32 bits, relative to the voice's sample address (wraps like the console's).
uint32_t from_sample(const Voice& v, int64_t sample) {
    return static_cast<uint32_t>(v.format == kAdpcm ? sample_to_nibble(sample) : sample);
}
// Guest address of the byte `bytes` after (or before) the voice's sample address.
uint32_t sample_address(const Voice& v, int64_t bytes) { return static_cast<uint32_t>(int64_t{v.samples} + bytes); }
"""),
    ("""    const uint32_t frame = static_cast<uint32_t>(v.cursor / 14), index = static_cast<uint32_t>(v.cursor % 14);
    const uint32_t frame_address = v.samples + frame * 8;
""", """    const int64_t frame = floor_div(v.cursor, 14);
    const uint32_t index = static_cast<uint32_t>(v.cursor - frame * 14);
    const uint32_t frame_address = sample_address(v, frame * 8);
"""),
    ("""        s = static_cast<int16_t>(uint16_t{*guest<be<uint16_t>>(v.samples + static_cast<uint32_t>(v.cursor) * 2)});
""", """        s = static_cast<int16_t>(uint16_t{*guest<be<uint16_t>>(sample_address(v, v.cursor * 2))});
"""),
    ("""    case kPcm8: s = static_cast<float>(static_cast<int8_t>(*guest<uint8_t>(v.samples + static_cast<uint32_t>(v.cursor))) * 256); break;
""", """    case kPcm8: s = static_cast<float>(static_cast<int8_t>(*guest<uint8_t>(sample_address(v, v.cursor))) * 256); break;
"""),
    ("""    v->loop_start = to_sample(*v, o->loop_offset);
    v->end = to_sample(*v, o->end_offset);
    v->cursor = to_sample(*v, o->current_offset);
""", """    v->loop_start = to_sample(*v, uint32_t{o->loop_offset});
    v->end = to_sample(*v, uint32_t{o->end_offset});
    v->cursor = to_sample(*v, uint32_t{o->current_offset});
"""),
    ("""uint64_t rebased(const Voice& v, uint32_t offset, uint32_t samples) {
    if (samples == 0 || samples == v.samples) return to_sample(v, offset);
    const int64_t bytes = int64_t{samples} - int64_t{v.samples};
    switch (v.format) {
    case kPcm16: return static_cast<uint64_t>(int64_t{offset} + bytes / 2);
    case kAdpcm: return to_sample(v, static_cast<uint32_t>(int64_t{offset} + bytes * 2));
    default: return static_cast<uint64_t>(int64_t{offset} + bytes);
    }
}
""", """// port/patch_ax_offsets.py: signed - `samples` may lie below the voice's address (a stream player that set the voice
// up on a later buffer of its ring and loops back to the first one).
int64_t rebased(const Voice& v, uint32_t offset, uint32_t samples) {
    if (samples == 0 || samples == v.samples) return to_sample(v, offset);
    const int64_t bytes = int64_t{samples} - int64_t{v.samples};
    switch (v.format) {
    case kPcm16: return int64_t{offset} + floor_div(bytes, 2);
    case kAdpcm: return nibble_to_sample(int64_t{offset} + bytes * 2);
    default: return int64_t{offset} + bytes;
    }
}
"""),
    ("""        v->loop_start = rebased(*v, offset, samples);
""", """        v->loop_start = rebased(*v, offset, samples);
        AX_TRACE("loop offset %08X 0x%X at %08X (voice at %08X, format %u) -> sample %lld\\n", vpb, offset, samples,
                 v->samples, v->format, static_cast<long long>(v->loop_start));
"""),
    ("""        v->end = rebased(*v, offset, samples);
""", """        v->end = rebased(*v, offset, samples);
        AX_TRACE("end offset %08X 0x%X at %08X (voice at %08X, format %u) -> sample %lld\\n", vpb, offset, samples,
                 v->samples, v->format, static_cast<long long>(v->end));
"""),
    ("""        v->cursor = rebased(*v, offset, samples);
""", """        v->cursor = rebased(*v, offset, samples);
        AX_TRACE("current offset %08X 0x%X at %08X (voice at %08X, format %u) -> sample %lld\\n", vpb, offset, samples,
                 v->samples, v->format, static_cast<long long>(v->cursor));
"""),
    ("""    int64_t value = from_sample(*v, v->cursor);
    if (samples != 0 && samples != v->samples) {
        const int64_t bytes = int64_t{samples} - int64_t{v->samples};
        value -= v->format == kPcm16 ? bytes / 2 : v->format == kAdpcm ? bytes * 2 : bytes;
    }
""", """    int64_t value = v->format == kAdpcm ? sample_to_nibble(v->cursor) : v->cursor;
    if (samples != 0 && samples != v->samples) {
        const int64_t bytes = int64_t{samples} - int64_t{v->samples};
        value -= v->format == kPcm16 ? floor_div(bytes, 2) : v->format == kAdpcm ? bytes * 2 : bytes;
    }
"""),
])
