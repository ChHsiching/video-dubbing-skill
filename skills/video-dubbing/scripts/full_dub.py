"""全片中配版制作：141 条翻译 → TTS 合成 → 串珠时间轴 → v3 插帧 → 烧录。

分阶段设计，每阶段产物落盘，支持断点续跑：
  Stage 1: TTS 合成（单线程，~5h）→ _segments/sent_NNNN.wav
  Stage 2: 时间轴计算 + JSON 落盘（秒级）
  Stage 3: 视频分段 + 插帧（~1.6h）→ _vsegs/v_NNNN.mp4
  Stage 4: concat + 音频 + ASS + 烧录（~10min）

用法：
  python full_dub.py stage1   # 只跑 TTS 合成
  python full_dub.py stage2   # 只算时间轴
  python full_dub.py stage3   # 只跑插帧（耗时）
  python full_dub.py stage4   # concat + 烧录
  python full_dub.py all      # 全部（stage1 后自动接 234）
"""
import os, sys, time, re, json, subprocess, contextlib, wave, shutil

# ===== 单线程必须在最前面（坑 5）=====
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

OUT = r"C:\Users\Administrator\Git\video-subtitle\matt-pocock\dont-waste-time-on-specs-prototype-instead"
INDEXTTS = r"C:\Users\Administrator\Git\novel-promotion\index-tts"
RAW_MP4 = OUT + r"\raw\dont-waste-time-on-specs-prototype-instead.raw.mp4"
EN_SRT = OUT + r"\transcript\dont-waste-time-on-specs-prototype-instead.en.full.srt"
ZH_TXT = OUT + r"\transcript\translations_dub.txt"
REF_WAV = OUT + r"\dubbed\_test_indextts\ref.wav"
SEG_DIR = OUT + r"\dubbed\_full\_segments"
VSEG_DIR = OUT + r"\dubbed\_full\_vsegs"
WORK_DIR = OUT + r"\dubbed\_full"
TIMELINE_JSON = WORK_DIR + r"\timeline.json"
RAW_DUR = 658.914

os.makedirs(SEG_DIR, exist_ok=True)
os.makedirs(VSEG_DIR, exist_ok=True)

def get_dur(p):
    with contextlib.closing(wave.open(p, "rb")) as w:
        return w.getnframes() / float(w.getframerate())

def probe_dur(p):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","default=noprint_wrappers=1:nokey=1",p], capture_output=True, text=True)
    return float(r.stdout.strip())

def fmt_ts(s):
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def fmt_ass_ts(s):
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:d}:{m:02d}:{sec:02d}.{ms//10:02d}"

def _ts(s):
    s = s.replace(",", ".")
    h, m, sec = s.split(":")
    return int(h)*3600 + int(m)*60 + float(sec)

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ===== 解析 en.full.srt + translations_dub.txt =====
def load_cues():
    _CUE_RE = re.compile(r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n(.*?)(?=\n\n|\n\d+\s*\n|\Z)", re.DOTALL)
    cues = []
    with open(EN_SRT, encoding="utf-8") as f:
        for m in _CUE_RE.finditer(f.read()):
            cues.append((int(m[1]), _ts(m[2]), _ts(m[3]), re.sub(r"\s+", " ", m[4].strip())))
    with open(ZH_TXT, encoding="utf-8") as f:
        zh = [l.rstrip("\n") for l in f if l.strip()]
    assert len(cues) == len(zh), f"行数不匹配 en={len(cues)} zh={len(zh)}"
    return [(idx, s, e, en, z) for (idx, s, e, en), z in zip(cues, zh)]

# ===== Stage 1: TTS 合成 =====
def stage1():
    sys.path.insert(0, INDEXTTS)
    for mod in list(sys.modules):
        if mod.startswith("indextts"): del sys.modules[mod]
    import torch
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)

    cues = load_cues()
    log(f"Stage 1: TTS 合成 {len(cues)} 条（单线程）")

    # 检查已完成
    done = sum(1 for idx,_,_,_,_ in cues
               if os.path.exists(os.path.join(SEG_DIR, f"sent_{idx:04d}.wav"))
               and os.path.getsize(os.path.join(SEG_DIR, f"sent_{idx:04d}.wav")) > 1000)
    log(f"  已缓存 {done}/{len(cues)} 条")

    if done < len(cues):
        log("loading IndexTTS2...")
        t0 = time.time()
        from indextts.infer_v2 import IndexTTS2
        tts = IndexTTS2(
            cfg_path=os.path.join(INDEXTTS, "checkpoints", "config.yaml"),
            model_dir=os.path.join(INDEXTTS, "checkpoints"),
            use_fp16=False, use_cuda_kernel=False, use_deepspeed=False, device="cpu",
        )
        log(f"loaded in {time.time()-t0:.1f}s")

    t_start = time.time()
    n_done = done
    for i, (idx, s, e, en, zh) in enumerate(cues):
        out = os.path.join(SEG_DIR, f"sent_{idx:04d}.wav")
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            continue
        t1 = time.time()
        tts.infer(spk_audio_prompt=REF_WAV, text=zh, output_path=out, use_random=False)
        dur = get_dur(out)
        n_done += 1
        elapsed = time.time() - t_start
        rate = (n_done - done) / max(elapsed, 1) if elapsed > 0 else 0
        eta = (len(cues) - n_done) / rate if rate > 0 else 0
        log(f"  [{i+1}/{len(cues)}] idx{idx} {dur:.2f}s zh='{zh[:30]}' elapsed={elapsed/60:.1f}min ETA={eta/60:.1f}min")
    log(f"Stage 1 DONE: {len(cues)} 条合成完成")

# ===== Stage 2: 时间轴计算 =====
def stage2():
    cues = load_cues()
    log(f"Stage 2: 时间轴计算（串珠法）")

    zh_durs = []
    for idx, s, e, en, zh in cues:
        seg = os.path.join(SEG_DIR, f"sent_{idx:04d}.wav")
        if not os.path.exists(seg):
            log(f"  ERROR: 缺 {seg}，请先跑 stage1"); return
        zh_durs.append(get_dur(seg))

    # 构建时间轴段：gap + cue 交替
    timeline = []
    prev_end = 0.0
    for i, (idx, s, e, en, zh) in enumerate(cues):
        if s > prev_end:
            timeline.append({"kind":"gap","orig_start":prev_end,"orig_end":s,"idx":None})
        timeline.append({"kind":"cue","orig_start":s,"orig_end":e,"idx":idx,
                         "zh_dur":zh_durs[i],"text":zh,"en":en})
        prev_end = e
    if prev_end < RAW_DUR:
        timeline.append({"kind":"gap","orig_start":prev_end,"orig_end":RAW_DUR,"idx":None})

    # 累计新时间轴
    new_t = 0.0
    for seg in timeline:
        orig_dur = seg["orig_end"] - seg["orig_start"]
        if seg["kind"] == "cue":
            new_dur = seg["zh_dur"]   # cue 段新长度 = 中文时长
        else:
            new_dur = orig_dur         # gap 保留原长
        seg["new_start"] = new_t
        seg["new_end"] = new_t + new_dur
        seg["new_dur"] = new_dur
        seg["speed"] = orig_dur / new_dur if new_dur > 0 else 1.0  # >1快进 <1放慢
        new_t = new_t + new_dur

    total_new = new_t
    log(f"  新时间轴总长: {total_new:.2f}s（原 {RAW_DUR:.2f}s，{'缩短' if total_new<RAW_DUR else '拉长'} {abs(total_new-RAW_DUR):.1f}s）")

    # 统计
    cues_seg = [s for s in timeline if s["kind"]=="cue"]
    fast = [s for s in cues_seg if s["speed"]>1.05]
    slow = [s for s in cues_seg if s["speed"]<0.95]
    log(f"  快进(>1.05x): {len(fast)} 条")
    log(f"  放慢(<0.95x, setpts 帧重复): {len(slow)} 条")
    if slow:
        log(f"  放慢段 speed 范围: {min(s['speed'] for s in slow):.2f}x - {max(s['speed'] for s in slow):.2f}x")

    with open(TIMELINE_JSON, "w", encoding="utf-8") as f:
        json.dump({"timeline":timeline,"total_new":total_new,"raw_dur":RAW_DUR}, f, ensure_ascii=False, indent=2)
    log(f"  写入 {TIMELINE_JSON}")
    log(f"Stage 2 DONE")

# ===== Stage 3: 视频分段 + v3 插帧 =====
def stage3():
    if not os.path.exists(TIMELINE_JSON):
        log("  ERROR: 缺 timeline.json，请先跑 stage2"); return
    with open(TIMELINE_JSON, encoding="utf-8") as f:
        data = json.load(f)
    timeline = data["timeline"]
    log(f"Stage 3: 视频分段 + v3 插帧（{len(timeline)} 段）")

    # 预估插帧耗时
    slow_segs = [s for s in timeline if s["kind"]=="cue" and s["speed"]<0.95]
    slow_video_dur = sum(s["new_dur"] for s in slow_segs)
    log(f"  需插帧段: {len(slow_segs)} 条，视频 {slow_video_dur:.1f}s，预估 ~{slow_video_dur*23/60:.0f}min")

    t_stage = time.time()
    for i, seg in enumerate(timeline):
        out = os.path.join(VSEG_DIR, f"v_{i:04d}.mp4")
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            continue   # 断点续跑
        os_v = seg["orig_start"]; oe_v = seg["orig_end"]
        orig_dur = oe_v - os_v
        new_dur = seg["new_dur"]
        factor = new_dur / orig_dur if orig_dur > 0 else 1.0
        speed = seg["speed"]

        if seg["kind"] == "cue" and speed < 0.95:
            # v3 方案：放慢段 setpts + minterpolate mci 插帧（保持 60fps）
            vf = (f"setpts={factor:.6f}*PTS,"
                  f"minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:"
                  f"me_mode=bidir:me=epzs:vsbmc=1")
            label = f"放慢{speed:.2f}x+插帧"
        elif seg["kind"] == "cue":
            # 快进/不变段：纯 setpts（本来就有冗余帧，无需插帧）
            vf = f"setpts={factor:.6f}*PTS"
            label = f"{'快进' if speed>1.05 else '不变'}{speed:.2f}x"
        else:
            vf = "null"
            label = "gap"

        t0 = time.time()
        cmd = ["ffmpeg","-y","-ss",f"{os_v:.3f}","-t",f"{orig_dur:.3f}","-i",RAW_MP4,
               "-vf",vf,"-an","-c:v","libx264","-preset","ultrafast","-crf","18",
               "-r","60",out]
        r = subprocess.run(cmd, capture_output=True, text=True)
        wall = time.time() - t0
        if r.returncode != 0:
            log(f"  [{i+1}/{len(timeline)}] ERR seg {i}: {r.stderr[-200:]}")
        else:
            elapsed = time.time() - t_stage
            n_done = i + 1
            rate = n_done / max(elapsed, 1)
            eta = (len(timeline) - n_done) / rate if rate > 0 else 0
            log(f"  [{n_done}/{len(timeline)}] {label} {orig_dur:.1f}s→{new_dur:.1f}s wall={wall:.0f}s ETA={eta/60:.0f}min")
    log(f"Stage 3 DONE")

# ===== Stage 4: concat + 音频 + ASS + 烧录 =====
def stage4():
    if not os.path.exists(TIMELINE_JSON):
        log("  ERROR: 缺 timeline.json"); return
    with open(TIMELINE_JSON, encoding="utf-8") as f:
        data = json.load(f)
    timeline = data["timeline"]
    total_new = data["total_new"]
    log(f"Stage 4: concat + 音频 + ASS + 烧录")

    # concat
    log("  4a: concat 视频段")
    concat_txt = WORK_DIR + r"\_concat.txt"
    with open(concat_txt, "w") as f:
        for i in range(len(timeline)):
            f.write(f"file '{VSEG_DIR}\\v_{i:04d}.mp4'\n")
    video_adj = WORK_DIR + r"\video_adjusted.mp4"
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",concat_txt,
                    "-c:v","libx264","-preset","ultrafast","-crf","18","-r","60",video_adj],
                   capture_output=True, text=True)
    log(f"    video_adjusted.mp4: {probe_dur(video_adj):.2f}s")

    # 音频 adelay + amix
    log("  4b: 音频放置（adelay + amix）")
    audio_plan = []
    for seg in timeline:
        if seg["kind"] != "cue": continue
        ns = seg["new_start"]; ne = seg["new_end"]
        audio_plan.append((SEG_DIR + f"\\sent_{seg['idx']:04d}.wav",
                           int(round(ns*1000)), ns, ne, seg["text"]))
    TARGET = probe_dur(video_adj)
    inputs = ["-f","lavfi","-t",f"{TARGET}","-i","anullsrc=r=22050:cl=mono"]
    filter_parts = ["[0:a]volume=0[base]"]
    for i, (seg, delay_ms, _, _, _) in enumerate(audio_plan):
        inputs.extend(["-i", seg])
        filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[d{i+1}]")
    mix = "[base]" + "".join(f"[d{i+1}]" for i in range(len(audio_plan)))
    filter_str = ";".join(filter_parts) + f";{mix}amix=inputs={len(audio_plan)+1}:duration=first:normalize=0[aout]"
    dub_wav = WORK_DIR + r"\dub.wav"
    r = subprocess.run(["ffmpeg","-y"] + inputs + ["-filter_complex",filter_str,"-map","[aout]",
                       "-t",f"{TARGET}","-ar","22050","-ac","1",dub_wav], capture_output=True, text=True)
    log(f"    dub.wav: {get_dur(dub_wav):.2f}s" + (f" ERR:{r.stderr[-200:]}" if r.returncode else ""))

    # 验证无重叠
    for i in range(1, len(audio_plan)):
        assert audio_plan[i][2] >= audio_plan[i-1][3], f"重叠! cue{i} {audio_plan[i][2]} < {audio_plan[i-1][3]}"
    log(f"    ✓ {len(audio_plan)} 条 cue 无重叠")

    # ASS + SRT
    log("  4c: 生成 ASS + SRT")
    ass_path = WORK_DIR + r"\dubbing.ass"
    srt_path = WORK_DIR + r"\dubbing.srt"
    ass_header = """[Script Info]
Title: 中配版
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1260

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,72,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,3,4,1,2,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        for (_, _, cs, ce, text) in audio_plan:
            f.write(f"Dialogue: 0,{fmt_ass_ts(cs)},{fmt_ass_ts(ce)},Default,,0,0,0,,{text}\\N\n")
    srt_lines = []
    for i, (_, _, cs, ce, text) in enumerate(audio_plan):
        srt_lines += [str(i+1), f"{fmt_ts(cs)} --> {fmt_ts(ce)}", text, ""]
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines))
    log(f"    dubbing.ass + dubbing.srt ({len(audio_plan)} cues)")

    # 烧录
    log("  4d: 烧录（pad + ass，bottom-bar 180px）")
    final_mp4 = OUT + r"\cooked\dont-waste-time-on-specs-prototype-instead.dubbed.mp4"
    ass_local = WORK_DIR + r"\burn.ass"
    shutil.copy(ass_path, ass_local)
    r = subprocess.run(["ffmpeg","-y","-i",video_adj,"-i",dub_wav,
                        "-vf","pad=iw:ih+180:0:0:color=black,ass=burn.ass",
                        "-map","0:v","-map","1:a",
                        "-c:v","libx264","-preset","medium","-crf","20","-r","60",
                        "-c:a","aac","-b:a","128k","-shortest",final_mp4],
                       cwd=WORK_DIR, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"    ERR: {r.stderr[-500:]}")
    else:
        log(f"    DONE: {final_mp4} ({probe_dur(final_mp4):.2f}s)")
    log(f"Stage 4 DONE")

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("stage1", "1"):
        stage1()
    if stage in ("stage2", "2", "all") and stage != "stage1":
        stage2()
    if stage in ("stage3", "3", "all") and stage not in ("stage1","stage2"):
        stage3()
    if stage in ("stage4", "4", "all") and stage not in ("stage1","stage2","stage3"):
        stage4()
    if stage == "all":
        log("全部完成")
