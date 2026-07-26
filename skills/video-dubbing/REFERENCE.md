# REFERENCE — video-dubbing

Loaded on demand from `SKILL.md` when the situation calls for it. The main skill file is the pipeline skeleton; this file holds the details you consult only when something needs explaining, when `cook dub` isn't available, or when VoxCPM2 misbehaves on your machine.

## Why this skill exists alongside `video-subtitle`

`video-subtitle` produces a **bilingual subtitled** release — the original English audio survives, the Chinese is only in the subtitles. That serves viewers who can read Chinese but want to hear the original speaker's tone and emphasis.

This skill produces a **Chinese-dubbed** release — the original English vocals are replaced with Chinese voiceover cloned from the same speaker. That serves viewers who want to listen in Chinese without reading subtitles (e.g. background listening, accessibility, broader reach on Chinese platforms).

The two releases are complementary, not alternatives. `video-cooking` produces both when the user asks for "连中配一起做".

## VoxCPM2 — install details (CPU, non-NVIDIA hardware)

VoxCPM2 ([openbmb/VoxCPM2](https://github.com/OpenBMB/VoxCPM), 2B params, released April 2026) is the open-source SOTA for zero-shot Chinese voice cloning as of July 2026: Chinese CER 0.97%, speaker similarity 79.5% (highest among open models), Apache 2.0, native `--device cpu` support, near-realtime on a Zen-architecture CPU (RTF ~1.0-1.9 in community benchmarks).

### The CPU torch wheel sequence (the critical install detail)

`pip install voxcpm` will pull **CUDA torch** as a dependency by default — which fails to actually use CUDA on AMD/Intel hardware and wastes ~2GB of disk. The correct sequence on a non-NVIDIA machine:

```bash
# 1. Install CPU torch FIRST (small, ~200MB):
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# 2. Then install voxcpm WITHOUT its torch dependency:
pip install voxcpm demucs soundfile --no-deps

# 3. Verify voxcpm's other deps are present:
pip install numpy scipy soundfile transformers accelerate
```

If you skip step 1 and let voxcpm pull torch itself, you'll get CUDA torch that doesn't work on your AMD GPU and wastes disk. If you skip `--no-deps` in step 2, pip will try to "fix" the missing CUDA torch by reinstalling it.

### The torch SDPA bug (the most common CPU failure)

On torch ≥ 2.6 with CPU, VoxCPM2's use of `torch.nn.functional.scaled_dot_product_attention` hits an `IndexError` due to a 1D attention mask + GQA interaction (PyTorch issue [#163597](https://github.com/pytorch/pytorch/issues/163597)). Symptoms: the model loads but the first `generate()` call crashes with an `IndexError` mentioning SDPA or attention mask shape.

**Three fixes, in order of preference:**

1. **Use source install** (the patches are merged into `main` but lag behind the pip release):
   ```bash
   git clone https://github.com/OpenBMB/VoxCPM.git
   cd VoxCPM
   pip install -e .
   ```
   This pulls the fix that reshapes the mask to 4D before SDPA. Tracked in [Issue #71](https://github.com/OpenBMB/VoxCPM/issues/71).

2. **Downgrade torch to 2.5.1** (the bug was introduced in 2.6):
   ```bash
   pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
   ```

3. **Use the ONNX backend** (community export, [DakeQQ/Text-to-Speech-TTS-ONNX](https://github.com/DakeQQ/Text-to-Speech-TTS-ONNX)) — runs via ONNX Runtime's CPUExecutionProvider, sidesteps the torch bug entirely. Slower but bulletproof.

If you see Windows users reporting this in [Issue #256](https://github.com/OpenBMB/VoxCPM/issues/256) or [#286](https://github.com/OpenBMB/VoxCPM/issues/286), the source-install fix is confirmed working.

### Model download (HuggingFace vs ModelScope)

`VoxCPM.from_pretrained("openbmb/VoxCPM2")` auto-downloads from HuggingFace on first call (~5-8GB). If HuggingFace is slow or blocked in your region, use ModelScope:

```bash
pip install modelscope
python -c "from modelscope import snapshot_download; snapshot_download('OpenBMB/VoxCPM2', local_dir='./pretrained_models/VoxCPM2')"
```

Then pass the local path: `VoxCPM.from_pretrained("./pretrained_models/VoxCPM2")`.

### CPU inference speed (real numbers, not estimates)

From community benchmarks on Zen-architecture CPUs (same family as the Ryzen 9 7950X this skill was built on):

| Source | CPU | Mode | RTF |
|---|---|---|---|
| [Sleeping Robots blog](https://sleepingrobots.com/dreams/voxcpm-strix-halo/) | AMD Strix Halo (Zen 5, 16 threads) | VoxCPM2 Python, 5 timesteps, short text | 1.06 |
| Same | Same | VoxCPM2 Python, 10 timesteps | 1.58-1.93 |
| Same | Same | VoxCPM.cpp Q8_0 GGUF | 1.66 |
| [VoxCPM.cpp benchmark](https://github.com/bluryar/VoxCPM.cpp) | Intel i5-12600K, 8 threads | VoxCPM1.5 Q8_0 | 4.29 |
| [Issue #256](https://github.com/OpenBMB/VoxCPM/issues/256) | Intel Core Ultra 7 255H (16 cores) | Python, warm | ~1.53 it/s |

A 30-minute video dubbed on a Ryzen 9 7950X with VoxCPM2 Python typically takes 4-8 hours of wall time (hundreds of cues, each ~1-2s of TTS). Plan accordingly — run detached overnight.

### Ultimate Cloning — why the transcript matters

VoxCPM2's standard zero-shot mode (`reference_wav_path` only) clones the timbre but treats the reference as a generic style hint. Its **Ultimate Cloning** mode (`prompt_wav_path` + `prompt_text` + `reference_wav_path`) does audio-continuation-based cloning: the model is told "here is an audio clip and exactly what it says," which lets it align phoneme-level features and preserve rhythm, emotion, and speaking-rate idiosyncrasies — not just timbre. The README's exact words: "faithfully preserving every vocal detail — timbre, rhythm, emotion, and style."

This is why Step 2 transcribes the reference clip with whisperX rather than letting you type a transcript by hand — the transcript must match the audio exactly for Ultimate Cloning to work. A mismatched transcript degrades cloning quality below the audio-only baseline.

The dub_audio.py default is Ultimate Cloning ON. Pass `--no-ultimate-cloning` only if you have reason to believe the auto-transcript is wrong (rare — whisperX large-v3 is accurate on a clean 8-second clip).

## Demucs — raw commands (fallback when `cook dub separate` is missing)

`cook dub separate` runs Demucs internally. If cook lacks the dub subcommand, run Demucs directly:

```bash
demucs --two-stems=vocals -n htdemucs_ft --shifts 1 --overlap 0.5 \
    -o <output-root>/dubbed/separated \
    <output-root>/raw/<name>.raw.mp4
```

This produces `dubbed/separated/htdemucs_ft/<name>.raw/{vocals.wav, no_vocals.wav}`. Move/rename them to `dubbed/vocals.wav` and `dubbed/no_vocals.wav` (the layout the rest of the pipeline expects).

Demucs `htdemucs_ft` (fine-tuned) is the quality choice — vocal SDR ~9dB on speech, crossing the human-perception threshold so the separation is essentially inaudible. The non-fine-tuned `htdemucs` is ~4× faster but ~1dB worse; use it only if `htdemucs_ft` is too slow.

### Demucs flags

- `--two-stems=vocals` — produce only `vocals.wav` and `no_vocals.wav` (everything else). Don't run 4-stem or 6-stem unless you have a reason — for dubbing you only need vocals vs. not-vocals.
- `--shifts 1` — average over 1 random shift to reduce boundary artifacts. Higher is better but slower; on CPU keep at 1.
- `--overlap 0.5` — segment overlap, reduces chunk-boundary glitches. Default 0.25; raise to 0.5 for cleaner output at 2× slower.
- `-d cuda` / `-d cpu` — explicit device. Auto-detects by default.

### When Demucs isn't good enough

For music-heavy videos (Vlog, MV, documentary with prominent score), Demucs's vocal SDR drops and BGM leaks into `vocals.wav`, which corrupts the reference clip. The absolute SOTA as of July 2026 is [Mel-Band RoFormer](https://github.com/ZFTurbo/Music-Source-Separation-Training) (vocal SDR ~11dB), but the engineering overhead (community implementation, manual weight download) isn't worth it for the typical technical-talk video. If you hit a music-heavy source, fall back to: use the original raw audio as the reference (let some BGM leak — Ultimate Cloning is robust to it) rather than chasing a cleaner separation.

## ffmpeg mix/mux — raw commands (fallback when `cook dub mix` is missing)

`cook dub mix <output-root> <name>` runs this ffmpeg pipeline. If cook lacks it, run ffmpeg directly:

```bash
# Mix: dub.wav at full volume, no_vocals.wav at -18dB, sum them
ffmpeg -y \
    -i <output-root>/dubbed/dub.wav \
    -i <output-root>/dubbed/no_vocals.wav \
    -filter_complex "[0:a]volume=1.0[dub];[1:a]volume=0.125[bg];[dub][bg]amix=inputs=2:duration=longest:normalize=0[aout]" \
    -map "[aout]" -ac 2 -ar 44100 \
    <output-root>/dubbed/_mixed.wav

# Mux: take the video (with burned subtitles) from cooked/, replace audio
ffmpeg -y \
    -i <output-root>/cooked/<name>.cooked.mp4 \
    -i <output-root>/dubbed/_mixed.wav \
    -map 0:v -map 1:a \
    -c:v copy -c:a aac -b:a 192k \
    -movflags +faststart \
    <output-root>/dubbed/<name>.dubbed.mp4

rm <output-root>/dubbed/_mixed.wav
```

### Background-gain choices

- `-18dB` (0.125×, default): BGM audible during silence, dub wins when speaker talks. Right for most videos.
- `-12dB` (0.25×): BGM clearly present throughout. For music-heavy videos where BGM is part of the experience.
- `-24dB` (0.063×): BGM barely there. For pure-talk videos where BGM is incidental.
- `-60dB` (essentially mute): equivalent to "replace audio wholesale" — use only if BGM is distracting.

### Sidechain-compress ducking (advanced alternative)

For a more dynamic mix where BGM auto-ducks only while the speaker talks, use sidechain compression instead of a fixed gain:

```bash
ffmpeg -y \
    -i <output-root>/dubbed/dub.wav \
    -i <output-root>/dubbed/no_vocals.wav \
    -filter_complex "[1:a][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=200[bgducked];[0:a][bgducked]amix=inputs=2:duration=longest:normalize=0[aout]" \
    -map "[aout]" ...
```

This is what professional dubbing mixes use, but it adds complexity and the threshold needs tuning per source. The fixed -18dB default is the pragmatic choice.

### Audio codec notes

- Output audio is AAC 192k — matches what Bilibili/YouTube/小红书 expect, and avoids the Opus-in-mp4 trap that breaks iMovie/QuickTime (same reason `video-subtitle`'s `cook burn` transcodes to AAC).
- `-movflags +faststart` moves the moov atom to the front so the file streams instead of buffering fully. Required for web playback.
- `-c:v copy` — no re-encode of the video (it's already burned with subtitles by `video-subtitle`). If the source cooked.mp4 has an odd codec, fall back to `-c:v libx264 -preset faster -crf 20`.

## Time alignment — engineering notes

### Why ±25% is the atempo limit

ffmpeg's `atempo` filter changes playback speed without changing pitch. Below 1.25× speed-up and above 0.8× slow-down, the result sounds natural. Beyond those bounds, even though atempo supports 0.5-2.0 by chaining, the speech becomes noticeably chipmunked (>1.25×) or drugged (<0.8×). The 1.25× / 0.8× bounds are the empirically-validated human-perception threshold for spoken content — [TTS.ai's dubbing docs](https://tts.ai/video-dubbing/) cite the same number.

The dub_audio.py default `--max-stretch 1.25` caps at this threshold. Cues that would need more stretch are instead **capped at 1.25× and logged to `alignment-issues.md`** with their natural vs. target durations. Review those manually — the fix is usually to re-translate that cue shorter in the zh.srt (the translation phase in `video-subtitle` is where length should be controlled; this skill only flags what slipped through).

### Why we don't use IndexTTS2's `target_dur`

IndexTTS2 has a unique feature: pass `target_dur` and it generates exactly N seconds of audio, by controlling the autoregressive token count. Sounds perfect for dubbing — except:

1. **It forces unnatural pacing.** When `target_dur` is shorter than the natural reading, IndexTTS2 compresses phoneme timing, producing rushed speech. When longer, it pads with awkward pauses. Either way, the result is less natural than atempo on naturally-paced speech.
2. **IndexTTS2 is slower on CPU than VoxCPM2** (~2.5 min per sentence in [liudon's benchmark](https://liudon.com/posts/voice-cloning-solution-comparison/) on an RTX 4090, worse on CPU).
3. **IndexTTS2's cloning quality is below VoxCPM2.** (SS 76.5 vs 79.5 on Seed-TTS-eval.) For "sound like the original speaker," VoxCPM2 Ultimate Cloning + atempo gives a better result than IndexTTS2 + target_dur.

The right answer for "the dub must fit this window" is **length-aware translation upstream** (which `video-subtitle`'s translation step already does — it keeps cues ≤42 chars and times them to the original), with atempo absorbing the residual ±25%. This skill's job is the residual absorption, not the primary length control.

### What to do with over-long cues

If `alignment-issues.md` flags many cues as `too_long_capped`, the dub will have those cues playing faster than natural. Three options, in order of preference:

1. **Re-translate those cues shorter** in `transcript/<name>.zh.srt` (the dub script). Run `video-subtitle`'s translation step again with explicit instructions to keep those specific cues under N characters. Then re-run Step 4 — the cache means only the changed cues re-synthesize.
2. **Accept the speed-up** for those cues if they're rare and the content allows it (a fast-talking speaker is less jarring than you'd think, if the original was also fast).
3. **Extend the cue's time window** by stealing time from adjacent silence. More complex; rarely worth it.

## Fallback TTS backends

dub_audio.py supports `--tts-backend indextts2` and (future) `--tts-backend gptsovits` for when VoxCPM2 won't install or produces poor results on your hardware.

### IndexTTS2 (`--tts-backend indextts2`)

- Already installed if you ran [`narrate-video`](https://github.com/ChHsiching/narrate-video-skill) (the sibling skill that uses IndexTTS2 for narration).
- Set `INDEXTTS_DIR` env var to the install path; dub_audio.py's `IndexTTS2Backend` reads it.
- Lower cloning quality than VoxCPM2 (SS 76.5 vs 79.5), no Ultimate Cloning mode (reference audio only), slower on CPU.
- Use only if VoxCPM2 fails to install. License note: IndexTTS2's model weights require written permission from bilibili for commercial use — fine for personal, problematic if you're publishing commercially.

### GPT-SoVITS (not yet wired in)

- The most CPU-friendly option ([official `--Device CPU` install path](https://github.com/RVC-Boss/GPT-SoVITS), RTF 0.526 on Apple M4, MIT license).
- Strongest when you can do 1-minute fine-tuning on the reference speaker (not pure zero-shot).
- If you need this backend, extend dub_audio.py with a `GPTSoVITSBackend` class following the same interface. Pull requests welcome.

## Chinese-dub quality self-check

After Step 5, before declaring done, listen to a 30-second sample of `<name>.dubbed.mp4` and check for:

1. **洋腔 (foreign accent)** — does the Chinese sound like a native speaker, or does it have the telltale flat intonation of cross-lingual TTS? If present, the reference clip is too short or too noisy — re-run Step 2 with a longer/cleaner clip.
2. **错字 (mis-readings)** — does the dub read every Chinese character correctly? VoxCPM2's CER is 0.97%, so rare, but technical terms and rare characters can trip it. Compare a few cues against the zh.srt text.
3. **断句不自然 (unnatural phrasing)** — does the dub pause at natural Chinese boundaries, or mid-word? This usually means the zh.srt cue text itself is fragmented (a `video-subtitle` translation issue, not this skill's).
4. **声音不像 (doesn't sound like the speaker)** — the most common complaint. Causes: (a) reference clip is from a different speaker (multi-speaker video), (b) reference clip has BGM bleed corrupting the clone, (c) the speaker's voice is outside VoxCPM2's training distribution. Fix: pick a different reference clip from a clearly-single-speaker section.

If multiple issues persist, the ultimate fallback is to accept the English-audio subtitled release (`cooked/<name>.cooked.mp4`) as the primary and treat the dub as a bonus — the bilingual subtitled release is the more universally useful product.
