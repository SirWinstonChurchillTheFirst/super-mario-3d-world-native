#!/usr/bin/env python3
r"""patch_ax_stream_voice.py RUNTIME_SRC_DIR : AX "stream" voices keep their ADPCM history across the loop jump
(Mario Kart 8: a thump every 0.45 s in all streamed music).

User report (26 Nov): "es kommt ein Ton, der die ganze Zeit bummt ... bummt ... bummt, egal wo, ausser wenn es laedt".

Measured (TTT2_AUDIO_DUMP, PC and console, same in both): in the TV output a rectangular pulse every 0.448 s - within
two samples the signal jumps by up to half of full scale, stays flat for 2 ms, falls back within 2 ms. 0.448 s is
14336 samples at 32 kHz = one block (0x2000 bytes, 0x4000 nibbles) of the title's streamed music: the nw::snd stream
player plays a ring of buffers with ONE looping DSP-ADPCM voice per channel and moves the voice's loop and end
addresses one buffer ahead each time (AXSetVoiceLoopOffsetEx / AXSetVoiceEndOffsetEx, visible with TTT2_TRACE_AX=1).
So each "loop" of that voice is really the seam between two consecutive blocks of one continuous sound.

Cause: at a loop jump the runtime always reloaded the decoder state (predictor/scale, yn1, yn2) from the voice's loop
context (AXSetVoiceAdpcmLoop). That is right for a normal looping sample (the context is the decoder state at the loop
start). A stream player cannot know that state in advance; it marks its voices with AXSetVoiceType(vpb, 1) ("stream"),
and for such a voice the console's mixer only takes the predictor/scale from the loop context and lets yn1/yn2 run on
(the samples just decoded ARE the history of the next block). AXSetVoiceType was an empty function here, so at every
block seam the two history samples were replaced by stale values (zero or the previous context): the first samples of
each block were decoded from a wrong history -> the decoder ran into its limit (the flat top) until the predictor
had forgotten the error. Silent while loading because no stream plays then.

Fix: the voice remembers its type; a stream voice (type 1) keeps yn1/yn2 at the loop jump and takes only the
predictor/scale (which the next frame header replaces anyway when the loop start is on a frame boundary).

Second cause, same place (found after the first fix: small flat steps of 1.5-2 ms were left at the seams): the end
of a voice was tested with "position >= end". The stream player moves the END address only after it has seen the voice
arrive in the next buffer (its sound thread runs once per 3 ms audio frame). Until then the voice is already in the
next buffer, i.e. BEYOND the old end. With ">=" every sample read there counted as "end reached": the voice jumped
back to the start of the new buffer again and again (up to one audio frame = 96 samples: the same sample repeated =
the flat top; with the reloaded garbage history that sample was large = the thump) and the loop counter rose by up
to 96 per seam instead of 1. The console's DSP compares addresses for equality: a voice that jumped beyond its end
simply plays on until the title has set the new end.
Fix: a loop jump to a position beyond the end marks the voice as "ahead"; while ahead, only the exact end position
ends the block. A voice that is beyond its end for any other reason still stops/loops at once (as before; no reading
through guest memory).

TTT2_AX_STREAM_LOOP=0 restores the old behaviour of both points (before/after recordings with one program).
TTT2_TRACE_AX=1 prints the voice type and each loop jump's state."""
import sys

root = sys.argv[1] + "/"
MARK = "patch_ax_stream_voice"


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
    ("""    uint32_t loop_count = 0; // times the voice went back to its loop start
""", """    uint32_t loop_count = 0; // times the voice went back to its loop start
    // port/patch_ax_stream_voice.py: AXSetVoiceType 1 = stream: the loop jump is a seam inside one continuous sound.
    bool stream = false;
    // The last loop jump went to a position beyond `end` (a stream player moves the end afterwards): play on.
    bool ahead = false;
"""),
    ("""    if (v.cursor >= v.end) {
        if (v.loop) {
            v.cursor = v.loop_start;
            ++v.loop_count;
""", """    // port/patch_ax_stream_voice.py: the end is one position (the DSP compares for equality). A voice whose loop
    // jump landed beyond the end plays on until the title has moved the end; any other voice beyond its end ends.
    if (v.cursor <= v.end) v.ahead = false;
    if (v.cursor == v.end || (v.cursor > v.end && !v.ahead)) {
        if (v.loop) {
            v.cursor = v.loop_start;
            v.ahead = g_stream_loop && v.loop_start > v.end;
            ++v.loop_count;
"""),
    ("""std::recursive_mutex g_ax_mutex;
""", """// port/patch_ax_stream_voice.py: TTT2_AX_STREAM_LOOP=0 = old behaviour (stream voices reload yn1/yn2 at the loop).
const bool g_stream_loop = [] {
    const char* e = std::getenv("TTT2_AX_STREAM_LOOP");
    return !(e && e[0] == '0');
}();
uint64_t g_stream_seams = 0;

std::recursive_mutex g_ax_mutex;
"""),
    ("""            if (v.format == kAdpcm) {
                v.pred_scale = v.loop_pred_scale;
                v.yn1 = v.loop_yn1;
                v.yn2 = v.loop_yn2;
            }
""", """            if (v.format == kAdpcm) {
                // port/patch_ax_stream_voice.py: a stream voice continues one sound across the jump - the samples
                // just decoded are the history of what follows; only the predictor/scale comes from the loop context.
                if (g_trace && v.stream && (++g_stream_seams & 63) == 1) {
                    AX_TRACE("stream seam #%llu voice %08X -> sample %lld: history %d/%d, loop context %d/%d (%s)\\n",
                             static_cast<unsigned long long>(g_stream_seams), v.vpb,
                             static_cast<long long>(v.loop_start), v.yn1, v.yn2, v.loop_yn1, v.loop_yn2,
                             g_stream_loop ? "history kept" : "history replaced");
                }
                v.pred_scale = v.loop_pred_scale;
                if (!(v.stream && g_stream_loop)) {
                    v.yn1 = v.loop_yn1;
                    v.yn2 = v.loop_yn2;
                }
            }
"""),
    ("""void AXSetVoiceType(uint32_t, uint32_t) {}
""", """// port/patch_ax_stream_voice.py: 0 = normal, 1 = stream (see next_sample's loop jump).
void AXSetVoiceType(uint32_t vpb, uint32_t type) {
    std::lock_guard lock(g_ax_mutex);
    if (Voice* v = voice_of(vpb)) {
        v->stream = type == 1;
        AX_TRACE("voice type %08X %u\\n", vpb, type);
    }
}
"""),
])
