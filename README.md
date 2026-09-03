# video-dubbing

A skill that replaces a video's original English vocals with **Chinese voiceover cloned from the original speaker**, then **re-times the video** so the picture stays in sync with the Chinese. The result is a second release — same picture, Chinese audio, bilingual ZH+EN subtitles burned in — sitting alongside the bilingual subtitled release from [`video-subtitle`](https://github.com/ChHsiching/video-subtitle-skill).

Built and tested on a CPU-only Windows machine.

## Why

A subtitled release is the primary product, but some audiences want a Chinese-narrated version they can listen to without reading. Voice-cloning the original speaker (rather than a generic TTS voice) preserves the speaker's timbre and prosody, so the dub feels like the same person speaking Chinese. The video is re-timed to the Chinese audio — never the other way around — because stretched TTS audio sounds unnatural while re-timed video is barely noticeable.

This skill is **additive**: it reads the bilingual release that `video-subtitle` produced and writes to a separate `dubbed/` stage folder plus `cooked/<name>.dubbed.mp4`. It does not modify anything `video-subtitle` produced, so a dub failure never blocks the bilingual release.

## Install

```bash
npx skills add ChHsiching/video-dubbing-skill
pip install video-cook[all]                  # cook CLI (pulls whisperx + yt-dlp)
```

The dub pipeline also needs **IndexTTS2** (the voice-cloning TTS), **Demucs** (vocal separation), and **whisperX** (reference extraction), which live in a separate venv because their heavy deps are isolated from cook's own Python. See [`REFERENCE.md`](skills/video-dubbing/REFERENCE.md) for the exact venv setup and the single-thread constraint IndexTTS2 requires.

## Use

Inside your agent, after `video-subtitle` has produced the bilingual cooked video:

> 给这个视频做中配（中文配音）：把英文原声换成念中文字幕的中文配音，声音要像原说话人

Or run the full download → subtitle → dub chain in one command via the [`video-cooking`](https://github.com/ChHsiching/video-cooking-skill) router:

> /video-cooking <URL> （连中配一起做）

Note: the dub is slow on CPU — IndexTTS2 synthesis plus frame interpolation for re-timing runs for hours. The agent will tell you when the long steps are happening.

## How it works

The pipeline, the dub-specific translation step, the quality gates, and all command details live in **[SKILL.md](skills/video-dubbing/SKILL.md)** — that is the authoritative source the agent runs from. This README is intentionally a landing page only; execution details are not duplicated here so they cannot drift out of sync.

## License

AGPL-3.0-only · Copyright (c) 2026 ChHsiching —— 见 [LICENSE](LICENSE)。

- 使用（含公司内部使用）、修改、分发均免费；但分发或以本代码提供网络服务时，衍生作品须以 AGPL-3.0 开源。
- 闭源商用须另行获取商业授权：hsichingchang@gmail.com

### 贡献条款

提交 PR 即表示你同意以 AGPL-3.0 授权你的贡献，并授予维护者在 AGPL 之外另行提供商业授权的权利（你的贡献始终以 AGPL 对所有人开放）。
