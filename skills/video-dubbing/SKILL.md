---
name: video-dubbing
description: Replace a video's original English vocals with Chinese voiceover, then re-time the video so the picture matches the Chinese. Use when the user wants to dub a video into Chinese — mentions 中配 / 配音 / 中文配音 / 换原声, or has a cooked bilingual video and wants a second Chinese-narrated release, or another skill (e.g. video-cooking) hands off "video is done with subtitles, add a Chinese dub."
---

Replace a video's original English vocals with **Chinese voiceover**, then **re-time the video** so picture stays in sync with the longer/shorter Chinese. The result is a second release — same picture, Chinese audio, Chinese subtitles burned in.

This skill does the two creative parts the CLI can't: **translating for dubbing** (complete sentences, not the subtitle fragmentation) and **bi-directional re-timing** (slow down or speed up each video segment to match the Chinese audio, never stretching the audio). Deterministic execution (Demucs, ffmpeg, IndexTTS2) is handled by the [`cook`](https://github.com/ChHsiching/video-cook) CLI's `cook dub` subcommand, with this skill's `scripts/` as a fallback.

## When to reach for this skill

You have a video that already has:
- A **raw video file** (`<output-root>/raw/<name>.raw.mp4`) — the original, with English vocals.
- A **bilingual subtitle run** from `video-subtitle` — specifically `transcript/<name>.en.full.srt` (the full-sentence English transcript, merged from whisperX fragments) and `transcript/translations.txt`.

You want a Chinese-dubbed release. If you don't have these yet, run `video-download` then `video-subtitle` first — this skill reads their outputs.

## What you produce

A new `dubbed/` stage folder added to the video's output directory, plus the final products (video + upload subtitle) in `cooked/` and `cloud-srt/`:

1. `transcript/translations_dub.txt` — the dub script (one Chinese line per `en.full.srt` cue, translated for dubbing, not subtitle fragments)
2. `transcript/<name>.zh.dub.srt` — Chinese SRT (timestamps inherited from `en.full.srt`, before re-timing)
3. `dubbed/_reference/ref.wav` — 14-30s clean clip of the original speaker (IndexTTS2 reference)
4. `dubbed/vocals.wav` — original vocals, separated by Demucs
5. `dubbed/no_vocals.wav` — original BGM + SFX (kept for inspection; only mixed when BGM is present)
6. `dubbed/_segments/sent_NNNN.wav` — per-cue IndexTTS2 output (cache, re-usable)
7. `dubbed/_full/timeline.json` — the re-timed timeline (every cue's new start/end on the dubbed video's clock)
8. `dubbed/_full/dub.wav` — the synthesized Chinese dub, placed on the new timeline
9. `dubbed/_full/dubbing.srt` / `dubbing.merged.srt` — Chinese subtitles on the new timeline (working files; merged.srt is the shorten+merge-short version used for burning)
10. `cooked/<name>.dubbed.mp4` — **the product**: raw video, re-timed, with Chinese dub + burned Chinese subtitles
11. `cloud-srt/zh.dub.srt` — **the upload subtitle**: copy of `dubbing.merged.srt`, for platforms that accept soft subs (B站云字幕). Named simply, sits next to `cloud-srt/zh.srt` from `video-subtitle`.

The run is not done until the final video plays end-to-end with synced audio and readable subtitles — see Step 8.

## Directory layout

This skill adds `dubbed/` (working directory) and writes the final products to `cooked/` and `cloud-srt/`:

```
<output-root>/
├── raw/                            ← from video-download (this skill reads it)
│   └── <name>.raw.mp4
├── transcript/                     ← from video-subtitle (this skill reads + adds)
│   ├── <name>.en.full.srt          ← full-sentence English (the dub script source)
│   ├── translations_dub.txt        ← this skill writes: one Chinese line per cue
│   └── <name>.zh.dub.srt           ← this skill writes: pre-re-timing SRT
├── cooked/                         ← final videos live here
│   ├── <name>.cooked.bar.mp4       ← from video-subtitle (untouched)
│   └── <name>.dubbed.mp4           ← this skill's product
├── cloud-srt/                      ← upload subtitles live here
│   ├── zh.srt                      ← from video-subtitle (untouched)
│   ├── en.srt                      ← from video-subtitle (untouched)
│   └── zh.dub.srt                  ← this skill's upload subtitle (copy of dubbing.merged.srt)
└── dubbed/                         ← this skill's working directory
    ├── _reference/
    │   └── ref.wav
    ├── _segments/                  ← per-cue IndexTTS2 cache
    ├── _full/
    │   ├── timeline.json
    │   ├── _vsegs/                 ← per-segment re-timed video chunks
    │   ├── dub.wav
    │   ├── video_adjusted.mp4      ← re-timed video (before burn)
    │   ├── dubbing.srt             ← working file (141 cues, pre-shorten)
    │   └── dubbing.merged.srt      ← working file (187 cues, post-shorten; copied to cloud-srt)
    ├── vocals.wav
    └── no_vocals.wav
```

Rule: **`dubbed/` is the working directory; `cooked/<name>.dubbed.mp4` and `cloud-srt/zh.dub.srt` are the products.** Never touch `raw/`, `transcript/<name>.zh.srt`, `cooked/<name>.cooked.mp4`, or `cloud-srt/{zh,en}.srt` — those belong to `video-subtitle`. If this skill fails halfway, the bilingual cooked shipment is still complete.

## The pipeline

The pipeline is implemented in `scripts/full_dub.py`, which takes a `synth|timeline|retime|burn|full` argument so each phase runs independently and resumes from cache. The steps below describe what each stage does; `cook dub <stage> --python <indextts-venv>/Scripts/python.exe` invokes each through cook (which runs full_dub.py as a subprocess under the IndexTTS2 venv), and the scripts run directly as a fallback.

### Step 0 — Resolve the environments

There are **two** Python environments in play, and confusing them is the failure mode this step exists to prevent:

- **cook's environment** (system Python or `~/.venvs/video-tools/`) — where the `cook` CLI lives, with whisperX/yt-dlp/torch for the subtitle pipeline.
- **IndexTTS2's environment** (`~/Git/index-tts/.venv`) — a separate venv holding `indextts`, `torch` (CPU build), and `demucs`. These deps are heavy and isolated on purpose; do **not** try to install them into cook's environment.

cook runs each dub stage as a subprocess under the IndexTTS2 venv via `--python`, so `from indextts import ...` resolves there. **Every `cook dub` command in this skill takes `--python <indextts-venv>/Scripts/python.exe`.** Resolve the venv path once (default `~/Git/index-tts/.venv`) and reuse it for the whole run.

**0a. Probe both environments are reachable:**

```
<cook-venv>/Scripts/cook doctor                                    # whisperX/yt-dlp/ffmpeg
<indextts-venv>/Scripts/python -c "import indextts, demucs; print('ok')"   # indextts + demucs
```

**0b. Single-thread constraint.** IndexTTS2 must run single-threaded (`OMP_NUM_THREADS=1`), or it produces garbage audio. `full_dub.py` sets this internally before importing torch, so you don't need to export it yourself — just don't run two dub stages in parallel.

Done when cook's doctor reports whisperX/yt-dlp/ffmpeg installed, the IndexTTS2 venv imports `indextts` + `demucs`, and you know the absolute path to `<indextts-venv>/Scripts/python.exe` to pass as `--python`.

### Step 1 — Separate vocals from the raw video

The original audio is one mixed track (vocals + BGM + SFX). Demucs splits it so we can extract a clean reference and check for BGM later.

```
cook dub separate <output-root> <name> [--model htdemucs] --python <indextts-venv>/Scripts/python.exe
```

Demucs lives in the IndexTTS2 venv, so `--python` points there. Use `htdemucs` (single model, ~3GB RAM), not `htdemucs_ft` (bag of 4 models, ~20GB RAM — OOMs on 32GB machines). Quality is slightly lower but adequate for reference extraction.

In foreground mode (default), cook moves the separated stems to `dubbed/vocals.wav` + `dubbed/no_vocals.wav` automatically; in `--detach` mode you move them yourself after the done marker appears.

Done when `dubbed/vocals.wav` AND `dubbed/no_vocals.wav` both exist with duration matching raw ±0.5s.

### Step 2 — Extract the reference clip

IndexTTS2 needs a **14-30 second** clean clip of the original speaker. Longer than the old VoxCPM2 requirement (8s) because IndexTTS2 clones prosody, not just timbre — it needs more material to learn rhythm.

Run the skill's `extract_reference.py` against `vocals.wav`:

```bash
<indextts-venv>/Scripts/python <skill>/scripts/extract_reference.py \
    <output-root>/dubbed/vocals.wav \
    <output-root>/dubbed/_reference/
```

The script uses whisperX internally to transcribe the reference clip, so it needs a venv with whisperX — the IndexTTS2 venv has it (alongside indextts/demucs), so reuse that one for consistency.

The script finds the longest continuous speech region (no silence gaps > 0.3s) within 14-30s. If no single region is long enough, it picks the densest 14s window. Override by dropping a `.wav` into `voices/` or passing a custom path.

Done when `dubbed/_reference/ref.wav` exists, is 14-30s, 16kHz mono, and contains continuous speech (no long silences).

### Step 3 — Translate for dubbing (the agent does this)

This is where dubbing diverges from subtitles. **Do not use `translations.txt`** (the subtitle translation) — it follows whisperX's 151-fragment cuts, which split sentences. Dubbing needs **complete sentences** so the Chinese flows naturally when spoken.

Read `<output-root>/transcript/<name>.en.full.srt` (the full-sentence English transcript — produce it from `en.srt` via video-subtitle's `scripts/make_full_srt.py`; 141 cues for an 11-min video, each one complete sentence). Translate each cue yourself, writing to `transcript/translations_dub.txt` — **one Chinese line per English cue, line N = cue N**.

**The remaining stages (Step 4 synth → Step 5 timeline → Step 6 retime → Step 7 burn) are all implemented in `scripts/full_dub.py` and invoked through cook:**

```
cook dub synth    <root> <name> --python <indextts-venv>/Scripts/python.exe
cook dub timeline <root> <name> --python <indextts-venv>/Scripts/python.exe
cook dub retime   <root> <name> --python <indextts-venv>/Scripts/python.exe
cook dub burn     <root> <name> --python <indextts-venv>/Scripts/python.exe
# or all four at once:
cook dub full <root> <name> --python <indextts-venv>/Scripts/python.exe
```

Each runs as a subprocess under the IndexTTS2 venv, so `from indextts import ...` resolves. The steps below describe what each stage does (so you can verify outputs and diagnose failures); the `cook dub <stage>` commands above are how you run them. The standalone script names in the code blocks below (`synth_dub.py`, `build_timeline.py`, etc.) are the legacy per-stage scripts — `full_dub.py` supersedes them, and cook calls `full_dub.py` internally.

**Dubbing translation principles** (different from subtitle translation):

- **Translate complete thoughts, not fragments.** The English is already full sentences (that's what `en.full.srt` is). Match that — your Chinese cue is one complete thought.
- **Let length be natural.** Don't pad to fill the time window (the re-timing in Step 5 handles mismatches), and don't compress to fit (you'll lose meaning). Translate faithfully; the algorithm absorbs ±30%.
- **Keep technical terms in English where Chinese devs do** — spec, plan, prototype, agent, token, compact, Wayfinder, grilling, skill, session, ticket, branch, route, etc. See **[REFERENCE.md → "Term retention list"](REFERENCE.md)** for the full set.
- **Keep English for anything shown on screen.** If the speaker says "I'll search for model" and types "model" into a search box visible in the video, keep "model" — translating it to "模型" while the screen shows "model" disorients the viewer. Same for UI labels, code, URLs, filenames.
- **Translate concepts that have standard Chinese names** — 数据模型 (data model), 快照 (snapshot), 选择器 (picker), 选项 (option). When a term has a common Chinese name and isn't shown on screen, use it.
- **Line count must equal cue count.** 141 English cues = 141 Chinese lines. Never merge or split lines — it desyncs the SRT generation.

Then generate the pre-re-timing SRT (timestamps inherited from `en.full.srt`):

```bash
python <skill>/scripts/make_zh_dub_srt.py <output-root>/transcript/<name>.en.full.srt \
    <output-root>/transcript/translations_dub.txt \
    <output-root>/transcript/<name>.zh.dub.srt
```

**Self-review — two passes, mandatory** (same discipline as `video-subtitle` Step 3):
- **Pass 1**: read every line as a spoken sentence. Does it sound like something a person would say?
- **Pass 2**: scan for term-retention errors — every on-screen label, search term, UI element kept in English; every standard-concept term in Chinese. Cross-check against the term-retention list in REFERENCE.md.

Done when `translations_dub.txt` has the same line count as `en.full.srt` cues, `<name>.zh.dub.srt` exists, and both review passes pass.

### Step 4 — Synthesize the Chinese dub (the slow step)

IndexTTS2 synthesizes each cue. **Single-threaded only** — multi-threaded inference produces garbage audio (0.05s truncated outputs) due to a float-reduction non-determinism in `SeamlessM4TFeatureExtrator`'s FFT. See **[REFERENCE.md → "The single-thread constraint"](REFERENCE.md)**.

```bash
<indextts>/.venv/Scripts/python <skill>/scripts/synth_dub.py \
    <output-root>/transcript/<name>.zh.dub.srt \
    <output-root>/dubbed/_reference/ref.wav \
    <output-root>/dubbed/_segments/
```

The script sets `OMP_NUM_THREADS=1` + `torch.set_num_threads(1)` before importing torch (load-bearing — order matters), loads IndexTTS2 once, then synthesizes each cue. Output is `dubbed/_segments/sent_NNNN.wav`, cached by cue index — re-running only re-synthesizes cues whose text changed.

**No audio post-processing.** Do not run `silenceremove` or `atempo` on IndexTTS2 output — both corrupt it (silenceremove with `stop_threshold=0.01` truncates normal speech; atempo stretches artifacts). IndexTTS2's raw output is clean.

**This step is slow on CPU.** RTF ~30-36 (a 5s cue takes ~3 min). A 141-cue video takes ~7 hours. Launch detached and poll the log. Tell the user this is the long step.

Done when `dubbed/_segments/sent_NNNN.wav` exists for every cue AND each is > 1KB (not a truncated garbage file).

### Step 5 — Bi-directional re-timing (the core innovation)

This is what makes the dub watchable. The Chinese audio is **never stretched** — it plays at its natural TTS speed. Instead, **each video segment is re-timed** to match the Chinese:

For each cue, compute `ratio = chinese_duration / english_window`:
- **ratio < 1 (Chinese shorter)**: **speed up** the video segment (drop redundant frames). No audio change.
- **ratio > 1 (Chinese longer)**: **slow down** the video segment (stretch the picture). No audio change.
- **ratio ≈ 1**: no change.

**Why this beats atempo-stretching the audio** (the old approach): stretched TTS audio sounds unnatural (chipmunk at >1.3x, drawl at <0.8x). Re-timed video looks fine — viewers don't notice 1.2x speedup or 0.7x slowdown on a talking-head video, but they immediately hear stretched speech.

**The string-of-pearls timeline** (prevents audio overlap and subtitle collision):

Build a new linear timeline where each cue plays back-to-back with its neighbors, gaps preserved from the original:
1. For each cue, the new segment duration = the Chinese TTS duration (audio never changes).
2. For each gap between cues, the new gap duration = the original gap (preserves rhythm).
3. Each cue's `new_start` = sum of all preceding segments' new durations — strictly monotonically increasing, mathematically impossible to overlap.
4. Each video segment is cut from the raw video at its original `[start, end]`, then `setpts` re-times it to the new duration.

Run the skill's timeline builder:

```bash
python <skill>/scripts/build_timeline.py \
    <output-root>/transcript/<name>.zh.dub.srt \
    <output-root>/dubbed/_segments/ \
    <output-root>/dubbed/_full/timeline.json
```

Done when `timeline.json` exists, every cue's `new_start < new_end`, no two cues overlap, and the total new duration is within ±50% of the raw (a healthy dub is 10-30% longer or shorter than the original).

### Step 6 — Re-time the video segments + interpolate slow segments

Cut the raw video into segments (cues + gaps), re-time each, and interpolate frames on slowed segments to maintain 60fps.

```bash
python <skill>/scripts/retime_video.py \
    <output-root>/raw/<name>.raw.mp4 \
    <output-root>/dubbed/_full/timeline.json \
    <output-root>/dubbed/_full/_vsegs/
```

For each segment:
- **Speed-up segment (ratio<1)**: `setpts=factor*PTS` only. The source has redundant frames at 60fps; dropping them is invisible.
- **Slow-down segment (ratio>1)**: `setpts=factor*PTS,minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=epzs:vsbmc=1`. The `setpts` stretches the timeline (each source frame displays longer), then `minterpolate` inserts motion-compensated intermediate frames to maintain 60fps. Without interpolation, slowed segments look choppy (15-35fps effective).

**Known limitation**: `minterpolate`'s optical-flow estimation fails on fast non-rigid motion — waving hands leave after-image artifacts (two ghosted hands). This is an architectural limitation of optical flow, not a tunable parameter. On talking-head videos (the common case) it's acceptable; on action footage it's not. The user has accepted this trade-off — see REFERENCE.md for alternatives that don't (no interpolation = choppy but no artifacts).

**Cost**: interpolated segments run at RTF ~23 on CPU. A video with ~90 slowed segments (the typical count) takes ~3 hours. This is the second slow step after TTS.

Done when `_vsegs/v_NNNN.mp4` exists for every timeline segment AND the segment count matches timeline length.

### Step 7 — Assemble audio, subtitles, and burn

Concatenate the re-timed video segments, place the Chinese audio on the new timeline, generate subtitles, and burn.

**7a. Concat segments + place audio:**

```bash
python <skill>/scripts/assemble.py \
    <output-root>/dubbed/_full/timeline.json \
    <output-root>/dubbed/_full/_vsegs/ \
    <output-root>/dubbed/_segments/ \
    <output-root>/dubbed/_full/
```

Produces `video_adjusted.mp4` (concatenated re-timed video) and `dub.wav` (Chinese audio placed via `adelay` on the new timeline, mixed onto a silence base).

**7b. Generate subtitles** — run the same `shorten` + `merge-short` + `ass` pipeline as `video-subtitle`, so each cue is one readable Chinese line. The `ass` step uses **dub-specific style parameters** (not the bilingual release's 180px bar): a shorter 70px bottom bar with font 48 and marginv 5. The dub is single-language Chinese, so it doesn't need the tall two-line bar the bilingual release uses.

```bash
python <video-subtitle>/scripts/subtitles.py shorten \
    <output-root>/dubbed/_full/dubbing.srt \
    <output-root>/dubbed/_full/dubbing.short.srt --lang zh --max-zh 56
python <video-subtitle>/scripts/subtitles.py merge-short \
    <output-root>/dubbed/_full/dubbing.short.srt \
    <output-root>/dubbed/_full/dubbing.merged.srt --min-dur 1.2 --max-len 56 --lang zh
python <video-subtitle>/scripts/subtitles.py ass \
    <output-root>/dubbed/_full/dubbing.merged.srt \
    <output-root>/dubbed/_full/dubbing.zh.ass \
    --fontsize 48 --marginv 5 --bottom-bar 70
```

`shorten` splits long cues at punctuation, allocating sub-cue time by display-width proportion. The bar is 70px (dub-specific; shorter than the bilingual release's 180px), each cue is one zh line, and `--fontsize 48 --marginv 5` keeps the text tight against the bottom edge. The `--fontsize`/`--marginv` flags require the upstream `subtitles.py ass` parameterization (video-subtitle-skill commit 181914d).

**7b-cont. Copy the upload subtitle to `cloud-srt/`:**

```bash
cp <output-root>/dubbed/_full/dubbing.merged.srt \
   <output-root>/cloud-srt/zh.dub.srt
```

The `dubbing.merged.srt` is a working file inside `_full/`; the upload subtitle that the user actually submits to B站云字幕 lives at `cloud-srt/zh.dub.srt` — same convention as `video-subtitle`'s `cloud-srt/zh.srt`. Simple name, sits next to its sibling, easy to find at upload time.

**7c. Burn** (run from `_full/` so the ASS uses a relative path — the Windows `ass` filter rejects `C:` paths). The ffmpeg `pad` height must match the `ass --bottom-bar` value (70px):

```bash
cd <output-root>/dubbed/_full
ffmpeg -y -i video_adjusted.mp4 -i dub.wav \
    -vf "pad=iw:ih+70:0:0:color=black,ass=burn.ass" \
    -map 0:v -map 1:a -c:v libx264 -preset medium -crf 20 -r 60 \
    -c:a aac -b:a 128k -shortest \
    <output-root>/cooked/<name>.dubbed.mp4
```

Done when `<name>.dubbed.mp4` exists, duration matches the new timeline ±0.5s, and a spot-check frame at a speaking timestamp shows Chinese subtitles rendered in the bottom bar.

### Step 8 — Verify

Play the video end-to-end (or spot-check at 5-6 timestamps). Check:
- **Audio-video sync**: the Chinese audio matches the speaker's lip movements and on-screen actions.
- **Subtitle readability**: no single line overflows the screen (sample frames at different points — if you see text clipped at left/right edges, the `shorten` max-zh is too high for this font size).
- **Slow-segment smoothness**: the interpolated segments play without obvious stutter. Hand-motion artifacts are expected and accepted.
- **No audio gaps or overlaps**: every cue has audio, no two cues play simultaneously.

Then report to the user:
- The absolute path of `<name>.dubbed.mp4`.
- The reference clip used (so they can sanity-check the voice).
- The total duration change (e.g. "11min → 12.4min, +13%").
- The number of cues that needed slow-down interpolation.

Done when the video plays clean end-to-end. The run is not done until this passes.

## Reference

The following details are pushed out of this file because they're consulted on demand:

- **[REFERENCE.md](REFERENCE.md)** — IndexTTS2 install (the single-thread constraint, the garbage-audio bug, model download), the full term-retention list (which English terms stay English, which become Chinese, and the on-screen-content rule with examples), Demucs raw commands, the bi-directional re-timing math (ratio formula, the string-of-pearls construction proof), `minterpolate` parameter tuning and its artifact alternatives (blend mode, no-interpolation), the IndexTTS2 vs VoxCPM2 vs 豆包 API comparison (why IndexTTS2 won), and the Chinese-dub quality self-check (洋腔 detection, term-translation audit).
