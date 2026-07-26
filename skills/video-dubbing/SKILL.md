---
name: video-dubbing
description: Replace the original vocals in a video with Chinese voiceover cloned from the original speaker, preserving background music and sound effects. Use when the user wants to add a Chinese dub to a video, mentions 中配/中文配音/声音克隆/换原声, has a cooked bilingual video and wants a second release with Chinese narration, or another skill (e.g. video-cooking) hands off "video is done with subtitles, add a Chinese dub."
---

Replace a video's original English vocals with **Chinese voiceover cloned from the original speaker**, while preserving the background music and sound effects. The result is a second release — same picture, same subtitles, same BGM, but the spoken audio is Chinese.

This skill does the **voice cloning** (the creative part that needs judgment about reference audio and Ultimate Cloning). Deterministic execution (Demucs vocal separation, audio mixing, muxing) is handled by the [`cook`](https://github.com/ChHsiching/video-cook) CLI's `cook dub` subcommand, with this skill's `scripts/` as a fallback if cook lacks the dub command.

## When to reach for this skill

You have a video that already has:
- A **raw video file** (`<output-root>/raw/<name>.raw.mp4`) — the original, with English vocals + BGM + SFX mixed in one audio track.
- A **Chinese subtitle file** (`<output-root>/transcript/<name>.zh.srt`) — the dub script, already translated with timestamps from `video-subtitle`.

You want a Chinese-dubbed release. If you don't have these two files yet, run `video-download` then `video-subtitle` first — this skill reads their outputs.

## What you produce

A new `dubbed/` stage folder added to the video's output directory (alongside the existing `raw/`, `transcript/`, `cooked/`):

1. `dubbed/_reference/ref.wav` — 5-10s clean clip of the original speaker (voice-cloning reference)
2. `dubbed/_reference/ref.txt` — English transcript of ref.wav (enables VoxCPM2 Ultimate Cloning)
3. `dubbed/vocals.wav` — original vocals, separated by Demucs (used for the reference + as the "what to replace" map)
4. `dubbed/no_vocals.wav` — original BGM + SFX (kept, only vocals are replaced)
5. `dubbed/dub.wav` — the synthesized Chinese dub, aligned to the original timeline
6. `dubbed/<name>.dubbed.mp4` — **the product**: video with Chinese dub + original BGM, subtitles still burned in
7. `dubbed/alignment-issues.md` — cues where the Chinese didn't fit the original time window (>25% stretch), for your review

The run is not done until `cook dub verify <output-root> <name>` exits 0 — see Step 6.

## Directory layout

This skill adds `dubbed/` to the per-video directory that `video-download` and `video-subtitle` already produced:

```
<output-root>/
├── raw/                            ← from video-download (this skill reads it)
│   └── <name>.raw.mp4
├── transcript/                     ← from video-subtitle (this skill reads it)
│   └── <name>.zh.srt
├── cooked/                         ← from video-subtitle (untouched)
│   └── <name>.cooked.mp4
└── dubbed/                         ← this skill's outputs
    ├── _reference/
    │   ├── ref.wav
    │   └── ref.txt
    ├── _segments/                  ← per-cue TTS cache
    ├── vocals.wav
    ├── no_vocals.wav
    ├── dub.wav
    ├── <name>.dubbed.mp4
    └── alignment-issues.md
```

Rule: **`dubbed/` is additive** — it never touches `raw/`, `transcript/`, or `cooked/`. If this skill fails halfway, the bilingual cooked shipment is still complete and publishable.

## The pipeline

### Step 0 — Ensure the shared environment

cook CLI, VoxCPM2, and Demucs must live in **one persistent shared Python environment** — the same one `video-subtitle` uses for whisperX. This is the agent's job, not the user's.

**0a. Find or create the shared environment.** Check these locations in order; use the first that has the dub tooling:

1. A `VIDEO_TOOLS_VENV` environment variable (explicit user override).
2. `~/.venvs/video-tools/` (the conventional shared location — same as `video-subtitle`).
3. The system Python (if `cook`, `voxcpm`, `demucs` are already pip-installed there).

If none exists, create one and install everything into it:

```bash
python -m venv ~/.venvs/video-tools
# Install CPU torch FIRST (avoid pulling CUDA torch via voxcpm's deps):
~/.venvs/video-tools/Scripts/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
~/.venvs/video-tools/Scripts/pip install voxcpm demucs soundfile --no-deps
~/.venvs/video-tools/Scripts/pip install video-cook[all]
```

The `--no-deps` on voxcpm/demucs is critical: it stops pip from reinstalling CUDA torch. See REFERENCE.md for the torch SDPA bug workaround if you hit it.

**0b. Always invoke cook via the shared environment's interpreter.** Resolve `<venv>/Scripts/cook.exe` (Windows) or `<venv>/bin/cook` (macOS/Linux). For the Python scripts (`dub_audio.py`, `extract_reference.py`), use the shared venv's python directly — `<venv>/Scripts/python.exe`.

**0c. Run doctor from the shared environment:**

```
<shared-venv>/Scripts/cook doctor
```

If `cook` lacks the `dub` subcommand, the skill falls back to its own `scripts/` (which call Demucs and ffmpeg directly). Tell the user either path is fine — but `cook dub` is preferred for the same reason `cook transcribe` is: deterministic, no shell-escaping traps.

Done when the shared environment exists, VoxCPM2 imports cleanly (`python -c "from voxcpm import VoxCPM"` exits 0), Demucs is installed, and ffmpeg is on PATH.

**`cook` in every step below means the shared-environment cook binary resolved here.** Same convention as `video-subtitle`.

### Step 1 — Separate vocals from the raw video

The original audio is one mixed track (vocals + BGM + SFX). Demucs splits it so we can replace only the vocals.

```
cook dub separate <output-root> <name> [--model htdemucs_ft]
```

Runs Demucs `htdemucs_ft` with `--two-stems=vocals` — produces `vocals.wav` (the original speaker) and `no_vocals.wav` (everything else). `htdemucs_ft` (fine-tuned) is the quality choice; on a technical-talk video it crosses the human-perception threshold (SDR ~9dB) so the separation is essentially inaudible. CPU runs at ~1.5× audio duration; a 30-min video takes ~45 min.

For long videos, `cook dub separate` auto-detaches (returns a JSON object with `pid`, `log`, `done_marker`; poll the log file). Don't chunk — Demucs handles long audio internally; chunking introduces boundary artifacts.

Done when `dubbed/vocals.wav` AND `dubbed/no_vocals.wav` both exist, and `ffprobe` reports each has duration matching `raw/<name>.raw.mp4` ±0.5s. If either is missing, the separation failed — surface the Demucs log and stop.

### Step 2 — Extract the reference clip + its transcript

This is the step that makes the dub sound like the **original speaker**, not a generic voice. VoxCPM2's Ultimate Cloning mode takes both the reference audio AND its transcript — the transcript lets the model do audio-continuation-based cloning that preserves timbre, rhythm, and emotion far better than audio-only cloning.

Run the skill's `extract_reference.py`:

```bash
<shared-venv>/Scripts/python <skill>/scripts/extract_reference.py \
    <output-root>/dubbed/vocals.wav \
    <output-root>/dubbed/_reference/
```

The script slides across `vocals.wav`, uses ffmpeg's `silencedetect` to find a continuous speech region (no silence gaps), and picks the 8-second window with the highest steady energy. Then it transcribes that clip with whisperX (same model `video-subtitle` used, `large-v3`) → `ref.txt`.

You can let the agent pick the clip automatically (default), or override:
- **Specify a time range**: "use 01:23-01:31" → the script's `--target-window` flag isn't needed; just run it and then trim manually, or pass a custom `--start`/`--end` once added.
- **Use a custom reference**: drop a `.wav`/`.mp3` into `voices/` (skill's bundled voice samples) or any path; skip `extract_reference.py` and write your own `ref.txt` by transcribing it yourself.

Done when `dubbed/_reference/ref.wav` exists (5-12s, 16kHz mono) AND `dubbed/_reference/ref.txt` exists with at least one full English sentence. If `ref.txt` is empty or looks like garbage (whisperX failed on a noisy clip), try a different region or a cleaner reference.

### Step 3 — Configure cloning

Use `AskUserQuestion` to confirm three things in one shot — don't ask them one at a time:

1. **Reference source**: the auto-extracted `ref.wav` (default, recommended) / a file in `voices/` / a custom path the user provides.
2. **Ultimate Cloning**: on (default — uses both ref.wav + ref.txt) / off (audio-only cloning, faster but less faithful).
3. **TTS backend**: VoxCPM2 (default, July 2026 SOTA for zero-shot cloning) / IndexTTS2 (if VoxCPM2 fails to install on this machine — see REFERENCE.md) / GPT-SoVITS (if both fail, last-resort CPU-friendly option).

The defaults are right 90% of the time. Only the reference source warrants asking — if the auto-extracted clip sounds wrong to the user (they'll hear it in the final), they'll come back and pick a different one. Recording the answers here lets Step 4 run without further interruption.

Done when you have `ref_wav_path`, `ultimate` (bool), and `tts_backend` recorded to pass to Step 4.

### Step 4 — Synthesize the Chinese dub (the slow step)

Read `<output-root>/transcript/<name>.zh.srt` (the dub script with original timestamps), synthesize each cue with VoxCPM2 cloning the reference, and align each cue to its original time window.

```bash
<shared-venv>/Scripts/python <skill>/scripts/dub_audio.py \
    <output-root>/transcript/<name>.zh.srt \
    <output-root>/dubbed/_reference/ref.wav \
    <output-root>/dubbed/_reference/ref.txt \
    <output-root>/dubbed \
    --tts-backend voxcpm2
```

What `dub_audio.py` does, per cue:

1. **Synthesize** the Chinese text via VoxCPM2 with Ultimate Cloning (`prompt_wav_path` + `prompt_text` + `reference_wav_path`).
2. **Time-align** via ffmpeg `atempo`: stretch the cue's natural duration to fit the original SRT cue's window. Capped at ±25% (1.25× / 0.8×) — beyond that the voice sounds chipmunked or drugged. Cues that exceed the cap are logged to `dubbed/alignment-issues.md` with their natural vs. target duration, for your later review.
3. **Place on timeline**: pad silence up to each cue's start offset, then mix down to `dub.wav` matching the original video's total duration.

The model loads once and is reused for every cue (loading VoxCPM2 is the expensive part). Cues are cached in `dubbed/_segments/sent_NNNN_<hash>.wav` keyed by `(backend, ultimate, text)` — so changing the reference or the backend invalidates the cache correctly, but re-running after a single cue's text was fixed only re-synthesizes that cue.

**This step is slow on CPU.** On a Ryzen 9 7950X, VoxCPM2 runs near-realtime per cue (RTF ~1-2), but a 30-minute video has hundreds of cues, so the total wall time is hours. **Launch detached** — copy `<skill>/scripts/windows-detached.ps1` into `<output-root>/dubbed/scripts/`, fill the path variables, and run it. The launch returns immediately; poll `<output-root>/dubbed/dub.log` until it contains `DONE`.

Tell the user this is the long step. Use the wait productively — pre-draft the alignment-issues review (you can already see which cues are long translations that might not fit).

Done when `dubbed/dub.wav` exists AND `ffprobe` reports its duration matches `raw/<name>.raw.mp4` ±2% AND the log file contains `DONE`. If `dub.wav` is significantly shorter than the raw, some cues failed — check `dub.err.log` and `alignment-issues.md`.

### Step 5 — Mix and mux

Combine the original BGM (no_vocals.wav) with the Chinese dub (dub.wav), then mux into the video:

```
cook dub mix <output-root> <name> [--bg-gain -18]
```

The mix:
- Takes `dubbed/no_vocals.wav` (original BGM + SFX) at the configured gain (default -18dB — audible but not competing with the dub).
- Takes `dubbed/dub.wav` (Chinese vocals) at full volume.
- Muxes onto the video's picture (from `cooked/<name>.cooked.mp4` — so the burned subtitles survive).

The default -18dB background is the "ducking" level — BGM is present during silence but the dub wins when the speaker talks. For music-heavy videos where BGM matters more, raise to -12dB. For pure-talk videos, lower to -24dB or use the original `raw/<name>.raw.mp4`'s picture (no subs) if you want a clean undubbed-but-subtitled alternate.

Done when `dubbed/<name>.dubbed.mp4` exists AND `ffprobe` reports duration matching the raw AND a spot-check at a speaking timestamp plays the Chinese dub.

### Step 6 — Verify and report

```
cook dub verify <output-root> <name>
```

The final gate. Checks that `dubbed/` contains the full shipment (vocals.wav, no_vocals.wav, dub.wav, `<name>.dubbed.mp4`, _reference/{ref.wav,ref.txt}), and cross-checks durations. Exit 0 = the dub is complete. Non-zero = the `missing` list tells you what to go back and produce.

Then report to the user:
- The absolute path of `<name>.dubbed.mp4`.
- The reference clip used (so they can sanity-check: "I cloned the voice from 02:14-02:22 of the original").
- The number of alignment-issues flagged (and that `alignment-issues.md` lists them).
- The TTS backend actually used (in case it fell back from VoxCPM2 to IndexTTS2).

Done when `cook dub verify` exits 0. The run is not done until this passes.

## Reference

The following details are pushed out of this file because they're consulted on demand, not every run. Load them when the situation calls for it:

- **[REFERENCE.md](REFERENCE.md)** — VoxCPM2 install details (CPU torch wheel sequence, the torch SDPA bug and its two fixes, model download via ModelScope vs HuggingFace), Demucs raw commands (when `cook dub separate` isn't available), the full ffmpeg mix/mux command (background gain, sidechain-compress ducking alternative), the time-alignment engineering notes (why ±25%, what to do with over-long cues, why we don't use IndexTTS2's `target_dur`), VoxCPM2 Ultimate Cloning internals, the fallback TTS backends (IndexTTS2, GPT-SoVITS — when to reach for them), and the Chinese-dub quality self-check (洋腔 / mis-readings / fragmentation).
