"""生成 zh.dub.srt（配音版字幕，时间戳继承自 en.full.srt）+ 估算新翻译的 ratio 改善。
时间戳策略：用 en.full.srt 的窗口，中文放置在窗口内。
注：实际配音合成后，时间戳会根据 TTS 实际时长 + 双向调节重新计算。
这里先生成一个版本供字幕烧录前的预览。
"""
import os, re

OUT = r"C:\Users\Administrator\Git\video-subtitle\matt-pocock\dont-waste-time-on-specs-prototype-instead"
SRT = OUT + r"\transcript\dont-waste-time-on-specs-prototype-instead.en.full.srt"
TXT = OUT + r"\transcript\translations_dub.txt"
ZH_SRT = OUT + r"\transcript\dont-waste-time-on-specs-prototype-installed.zh.dub.srt"

# 解析 en.full.srt
_CUE_RE = re.compile(r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n(.*?)(?=\n\n|\n\d+\s*\n|\Z)", re.DOTALL)
cues = []
with open(SRT, encoding="utf-8") as f:
    for m in _CUE_RE.finditer(f.read()):
        cues.append((int(m[1]), m[2], m[3], re.sub(r"\s+", " ", m[4].strip())))

with open(TXT, encoding="utf-8") as f:
    zh = [l.rstrip("\n") for l in f if l.strip()]

assert len(cues) == len(zh), f"行数不匹配 en={len(cues)} zh={len(zh)}"

# 直接用 en.full.srt 的时间戳写 zh.dub.srt
lines = []
for (idx, st, et, _), z in zip(cues, zh):
    lines.append(str(idx))
    lines.append(f"{st} --> {et}")
    lines.append(z)
    lines.append("")

with open(ZH_SRT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"已生成: {ZH_SRT}")
print(f"  {len(cues)} cues")

# ============ 估算新翻译的 ratio 改善 ============
# 用字数估算 TTS 时长：IndexTTS2 中文约 4.5 字/秒（保守估计）
# 实际会因标点、英文术语略有变化，但作为预估够用
TTS_RATE = 4.5  # 字/秒

def _ts(s):
    s = s.replace(",", ".")
    h, m, sec = s.split(":")
    return int(h)*3600 + int(m)*60 + float(sec)

print(f"\n{'='*70}")
print(f"新翻译 ratio 预估（按 {TTS_RATE} 字/秒估算 TTS 时长）")
print(f"{'='*70}")

ratios_new = []
windows = []
for (idx, st, et, en), z in zip(cues, zh):
    win = _ts(et) - _ts(st)
    windows.append(win)
    # 估算 TTS 时长（中文+英文术语都按字符数算，英文术语 TTS 会读字母或单词，略慢）
    # 粗略：英文单词按 0.3 秒/词，中文字按 1/TTS_RATE 秒
    en_words_in_zh = len(re.findall(r'[a-zA-Z]+', z))
    zh_chars = len(re.sub(r'[a-zA-Z\s]', '', z))
    est_dur = zh_chars / TTS_RATE + en_words_in_zh * 0.35
    ratio = est_dur / win if win > 0 else 0
    ratios_new.append(ratio)

# 对比新旧 ratio 分布
print(f"\n  新翻译预估 ratio 分布：")
buckets = {"<0.5":0, "0.5-0.7":0, "0.7-0.9":0, "0.9-1.1":0, "1.1-1.3":0, "1.3-1.5":0, ">1.5":0}
for r in ratios_new:
    if r < 0.5: buckets["<0.5"] += 1
    elif r < 0.7: buckets["0.5-0.7"] += 1
    elif r < 0.9: buckets["0.7-0.9"] += 1
    elif r < 1.1: buckets["0.9-1.1"] += 1
    elif r < 1.3: buckets["1.1-1.3"] += 1
    elif r < 1.5: buckets["1.3-1.5"] += 1
    else: buckets[">1.5"] += 1
for k, v in buckets.items():
    print(f"    {k:8s}: {v:3d} {'#'*v}")

srt = sorted(ratios_new)
print(f"\n  min: {min(ratios_new):.3f} | median: {srt[len(srt)//2]:.3f} | max: {max(ratios_new):.3f}")
print(f"  0.7-1.3 区间内（算法可处理）: {sum(1 for r in ratios_new if 0.7<=r<=1.3)} / {len(ratios_new)}")

# 模拟双向调节后的视频总时长
non_speech = 658.914 - sum(windows)
vid_total = non_speech
for r, win in zip(ratios_new, windows):
    zh_dur_est = r * win
    if zh_dur_est < win:
        # 中文短：快进视频到 zh_dur（但最多 1.5x）
        target = max(zh_dur_est, win/1.5)
        vid_total += target
    else:
        # 中文长：放慢视频到 zh_dur（无上限，放慢可接受）
        vid_total += zh_dur_est
print(f"\n  预估调速后视频总时长: {vid_total:.1f}s（{vid_total/60:.1f}min，原 11.0min）")
print(f"  缩短: {658.914-vid_total:.1f}s")
