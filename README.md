# video-dubbing

A skill that replaces the original vocals in a video with **Chinese voiceover cloned from the original speaker**, while preserving the background music and sound effects. Input is a cooked bilingual video plus its Chinese subtitle file; output is a second release with Chinese dubbing.

Built and tested on a CPU-only Windows machine (AMD Ryzen 9 7950X, no NVIDIA GPU).

## What it produces

A new `dubbed/` stage folder added to the video's output directory, alongside the existing `raw/`, `transcript/`, `cooked/`:

| File | What it is |
|---|---|
| `dubbed/_reference/ref.wav` | 5-10s clean clip of the original speaker (voice-cloning reference) |
| `dubbed/_reference/ref.txt` | English transcript of ref.wav (enables Ultimate Cloning) |
| `dubbed/vocals.wav` | Original vocals separated by Demucs (for the reference + optional remix) |
| `dubbed/no_vocals.wav` | Original BGM + SFX (kept, only vocals are replaced) |
| `dubbed/dub.wav` | Full Chinese dub audio, aligned to the original timeline |
| `dubbed/<name>.dubbed.mp4` | **The product** — video with Chinese dub + original BGM |
| `dubbed/alignment-issues.md` | Cues where the dub couldn't fit in the original time window (>25% stretch) |

## How it works

```
<output-root>/raw/<name>.raw.mp4   (from video-download)
<output-root>/transcript/<name>.zh.srt   (from video-subtitle)
                    │
                    ├─ cook dub separate ──► vocals.wav + no_vocals.wav   (Demucs htdemucs_ft)
                    │
                    ├─ extract_reference.py ──► ref.wav + ref.txt         (pick clean clip + ASR)
                    │
                    ├─ dub_audio.py ──► dub.wav                            (VoxCPM2 Ultimate Cloning, per cue)
                    │   ├─ atempo stretch per cue to fit zh.srt window    (±25% max)
                    │   └─ cache to _segments/sent_NNNN.wav
                    │
                    ├─ cook dub mix ──► <name>.dubbed.mp4                  (BGM -18dB + dub, mux to video)
                    │
                    └─ cook dub verify ──► exit 0                          (final gate)
```

Three design choices that matter:

1. **VoxCPM2 with Ultimate Cloning.** As of July 2026, VoxCPM2 (`openbmb/VoxCPM2`) is the open-source SOTA for zero-shot voice cloning (Chinese CER 0.97%, speaker similarity 79.5%). Its Ultimate Cloning mode — passing both the reference audio **and** its transcript — is what makes the dub sound like the original speaker, not a generic TTS voice. Runs on CPU (the only realistic option on non-NVIDIA hardware).
2. **Vocals are separated, not replaced wholesale.** Demucs splits the original audio into vocals + (BGM + SFX). Only the vocals are replaced with the Chinese dub; the music and sound effects survive. A whole-track replacement would sound flat and lose the original's atmosphere.
3. **Deterministic execution (separation, mixing, muxing) is handled by [`cook`](https://github.com/ChHsiching/video-cook)** via the `cook dub` subcommand, with the skill's own `scripts/` as a fallback if cook lacks the dub command. The TTS synthesis itself lives in the skill (`dub_audio.py`) because it carries creative parameters (reference audio, Ultimate Cloning toggle) that don't belong in a deterministic executor. Same split as [`video-subtitle`](https://github.com/ChHsiching/video-subtitle-skill): brain in the skill, hands in cook.

## Requirements

- **Python 3.10-3.12** (VoxCPM2 needs `<3.13`)
- **`cook` CLI** with the `dub` subcommand, **or** the fallback scripts in `skills/video-dubbing/scripts/` (which call Demucs and ffmpeg directly)
- **VoxCPM2** (`pip install voxcpm`, source install recommended to dodge the torch SDPA bug — see REFERENCE.md)
- **Demucs** (`pip install demucs`) — used by `cook dub separate`
- **ffmpeg** on PATH
- **whisperX** (for reference-clip transcription in Step 2 — already installed if you ran video-subtitle)

Models download on first run and cache under `~/.cache/` for reuse. VoxCPM2 is ~2B params; expect a multi-GB download.

CPU works (built and tested on CPU). On a Ryzen 9 7950X, VoxCPM2 runs near-realtime per cue. A GPU would speed it up but isn't required — and on AMD hardware without CUDA, CPU is the only path that works reliably.

## Install

```bash
npx skills add ChHsiching/video-dubbing-skill
pip install voxcpm demucs soundfile          # TTS + vocal separation
pip install video-cook[all]                  # cook CLI (pulls whisperx too)
```

See [`REFERENCE.md`](skills/video-dubbing/REFERENCE.md) for the CPU-specific install sequence (install the CPU torch wheel first, then voxcpm with `--no-deps` to avoid pulling CUDA torch).

## Usage

Inside your agent, after `video-subtitle` has produced the bilingual cooked video:

> 给这个视频做中配（中文配音）：把英文原声换成念中文字幕的中文配音，声音要像原说话人

The skill fires, runs `cook doctor` to confirm the environment, then runs the pipeline. The agent tells you when the slow step (VoxCPM2 synthesis, which is detached and may take a while on CPU) is happening.

To run the full download → subtitle → dub chain in one command, use the [`video-cooking`](https://github.com/ChHsiching/video-cooking-skill) router with the dub stage enabled:

> /video-cooking <URL> （连中配一起做）

## Scripts (standalone, without cook)

The `scripts/` directory is usable without the `cook dub` subcommand:

```bash
SK=skills/video-dubbing/scripts

# Step 2: extract reference clip + transcript from separated vocals
python $SK/extract_reference.py dubbed/vocals.wav dubbed/_reference/

# Step 4: synthesize the Chinese dub from zh.srt
python $SK/dub_audio.py transcript/<name>.zh.srt \
    dubbed/_reference/ref.wav \
    dubbed/_reference/ref.txt \
    dubbed/

# Step 1 & 5 (separate + mix) use cook dub, or see REFERENCE.md for raw Demucs/ffmpeg commands
```

## License

MIT
