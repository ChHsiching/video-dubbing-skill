# DEPRECATED — retired re-timing reference sections
# (moved out of the live REFERENCE.md when the pipeline switched to the
# identity timeline; kept here with the code snapshot.)

## Bi-directional re-timing — the math

### The ratio

For each cue:
```
ratio = chinese_TTS_duration / english_window_duration
```
- `ratio < 1`: Chinese is shorter. The video segment gets **sped up** (compressed) to match.
- `ratio > 1`: Chinese is longer. The video segment gets **slowed down** (stretched) to match.
- `ratio ≈ 1`: no change.

Normal-rate audio is **never** time-stretched or atempo'd — every cue plays at its natural TTS speed, and length mismatches are absorbed on the video side. Slow cues (the short-line pacing bug) are fixed per SKILL.md Step 4's speed-up ladder — the ladder's last rung is DSP `atempo` capped at 1.6x per cue, under the pacing policy, not a contradiction of it.

### The string-of-pearls timeline (overlap-proof)

Naive approaches overlap. If you place each cue at `original_start + front_padding` independently, cues that were close in the original (e.g. 0.14s gap) collide after re-timing (both expand into the same new-timeline region). The string-of-pearls construction is provably overlap-free:

1. Walk the cues in order. Maintain a running `new_clock`, starting at 0.
2. For each gap between cues: `new_clock += original_gap_duration`. (Gaps are preserved as-is — they carry the original rhythm.)
3. For each cue: `cue.new_start = new_clock`. `cue.new_end = new_clock + chinese_TTS_duration`. `new_clock = cue.new_end`.

Because `new_clock` only ever increases, and each cue's `new_end` becomes the next cue's `new_clock` baseline, **two cues cannot overlap by construction**. This is checkable: assert `cues[i].new_start >= cues[i-1].new_end` for all i.

### Why re-time video, not audio

The old approach (VoxCPM2 + atempo) stretched the audio to fit the window. Problems:
- atempo > 1.3x: chipmunk voice.
- atempo < 0.8x: drunken drawl.
- The ±25% cap meant long Chinese cues still didn't fit, producing alignment-issues.md files full of "this cue couldn't be stretched enough."

Re-timing the video instead:
- 1.2x video speedup is invisible on talking-head footage (viewers don't notice frame-dropping at 60fps source).
- 0.7x video slowdown is acceptable (the speaker moves a bit slower; with minterpolation it's smooth).
- Normal-rate audio stays untouched end to end — the only audio processing the pipeline ever does is the pacing policy's bounded per-cue speed-up of confirmed-slow cues.
- The only limit is how much speedup viewers tolerate before the picture looks fast-forwarded (>1.5x is the threshold).

### Expected duration change

A faithful Chinese translation is typically 10-30% longer or shorter than the English, depending on the content. Technical talks (lots of English terms retained) tend to run shorter (Chinese grammar is more compact). Storytelling content runs longer (Chinese needs more syllables for the same meaning). The re-timed video will be 10-30% off the original duration — this is expected and acceptable.

### timeline.json — schema

`dubbed/_full/timeline.json` is the plan every later stage (retime, burn, subtitles, adjuster) consumes. Top level: `{"timeline": [segments], "total_new": float, "raw_dur": float, "adjust": {...} (written by adjust_timeline.py)}`. Segment fields:

| field | kind | meaning |
|---|---|---|
| `kind` | cue/gap | `cue` = a spoken sentence (audio + video); `gap` = pause between cues (video only) |
| `idx` | cue | cue number — indexes `sent_<idx:04d>.wav`, translations_dub.txt line, en.full.srt cue |
| `orig_start`, `orig_end` | both | the segment's window on the RAW video clock |
| `zh_dur` | cue | the synthesized audio's exact duration (seconds) |
| `text` | cue | the ZH sentence (same as translations_dub line `idx`) |
| `en` | cue | the EN full sentence |
| `new_start`, `new_end`, `new_dur` | both | the segment's window on the re-timed clock; segments tile back-to-back (next.new_start == prev.new_end) |
| `speed` | both | orig_dur / new_dur playback rate (0.45x = slowed, 1.2x = sped up); gaps carry it too (1.0 unless an adjuster stretched them) |

Invariants to respect when writing tools that edit this file: segments tile contiguously; starts strictly monotonic; a cue's audio (`zh_dur` from its `new_start`) never overlaps the next cue's audio.

## minterpolate — parameter tuning and alternatives

### The chosen parameters

```
minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=epzs:vsbmc=1
```

- `mi_mode=mci` — motion-compensated interpolation (the only mode that actually generates new frames; `blend` just averages).
- `mc_mode=aobmc` — advanced overlapped block motion compensation (highest quality).
- `me_mode=bidir` — bidirectional motion estimation (uses both past and future frames).
- `me=epzs` — the motion estimation algorithm. `esa` is higher quality but 5-10x slower; `epzs` is the quality/speed sweet spot.
- `vsbmc=1` — variable-size block motion compensation (handles local motion better than fixed blocks).

### The hand-artifact limitation

Optical-flow interpolation fails on **fast non-rigid motion**. The classic case: a waving hand. The hand moves too fast for the flow estimator to track, so it produces two ghosted hands (the before and after positions averaged). This is architectural — no parameter tuning fixes it.

**Mitigations** (in order of preference):
1. **Accept it** — on talking-head videos (the common case), hands are in frame briefly and the artifact is tolerable. The user has accepted this trade-off.
2. **`mi_mode=blend`** — frame averaging produces a natural motion blur (like a camera shutter) instead of ghosting. Smoother-looking but less sharp. Use if the user objects to ghosting.
3. **No interpolation** — pure `setpts` slowdown. The segment plays at 15-40fps effective (choppy) but has zero artifacts. Use for action footage where ghosting is unacceptable.

Do **not** try `mc_mode=obmc` (lower quality than aobmc) or `vsbmc=0` (worse) thinking they reduce artifacts — they don't, they just reduce quality.

### Cost

Interpolated segments run at RTF ~23 on CPU. A typical 11-min video has ~90 slowed segments totaling ~7 min of output video — that's ~2.8 hours of processing. Combined with TTS (~8h at 141 cues), the full pipeline is ~11 hours on CPU. GPU (if available) cuts minterpolate to minutes but doesn't help IndexTTS2 (which is CPU-bound by the single-thread constraint).

