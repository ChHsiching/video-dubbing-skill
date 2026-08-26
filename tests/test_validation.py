"""Tests for the retime/burn validation logic added in ticket #3.

These test the pure check functions directly — the heavy deps (indextts,
torch, ffmpeg) are not touched. The check functions accept an injectable
prober so tests can simulate corrupted/missing segments without touching
the filesystem.
"""
import importlib.util
import sys
from pathlib import Path

# Load full_dub.py as a module without importing its package (it has none).
_HERE = Path(__file__).resolve().parent
_SCRIPT = _HERE.parent / "skills" / "video-dubbing" / "scripts" / "full_dub.py"
spec = importlib.util.spec_from_file_location("full_dub", _SCRIPT)
full_dub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(full_dub)


# ---------- _vseg_is_valid ----------

def _valid(out, expected_dur=2.0, prober=None):
    """Thin wrapper so each test reads as 'is this vseg valid?'."""
    return full_dub._vseg_is_valid(Path(out), expected_dur, prober=prober)


def test_vseg_valid_when_file_exists_and_probe_returns_positive(tmp_path):
    f = tmp_path / "v_0000.mp4"
    f.write_bytes(b"x" * 2000)  # > 1000 bytes
    ok, reason = _valid(f, expected_dur=2.0, prober=lambda p: 2.0)
    assert ok is True
    assert reason == ""


def test_vseg_invalid_when_missing(tmp_path):
    ok, reason = _valid(tmp_path / "v_0000.mp4", prober=lambda p: 2.0)
    assert ok is False
    assert "missing" in reason


def test_vseg_invalid_when_truncated_file(tmp_path):
    f = tmp_path / "v_0000.mp4"
    f.write_bytes(b"x" * 100)  # < 1000 bytes = truncated
    ok, reason = _valid(f, prober=lambda p: 2.0)
    assert ok is False
    assert "truncated" in reason.lower() or "small" in reason.lower()


def test_vseg_invalid_when_probe_returns_zero(tmp_path):
    """The corruption symptom this ticket exists to catch: moov atom missing
    -> ffprobe returns 0. Must be flagged invalid so stage_retime redoes it."""
    f = tmp_path / "v_0000.mp4"
    f.write_bytes(b"x" * 2000)
    ok, reason = _valid(f, prober=lambda p: 0.0)
    assert ok is False
    assert "0" in reason or "probe" in reason.lower()


def test_vseg_invalid_when_probe_raises(tmp_path):
    """ffprobe raising (e.g. 'moov atom not found') must surface as invalid,
    not crash the pipeline."""
    f = tmp_path / "v_0000.mp4"
    f.write_bytes(b"x" * 2000)

    def raising(_):
        raise RuntimeError("moov atom not found")

    ok, reason = _valid(f, prober=raising)
    assert ok is False
    assert "probe" in reason.lower() or "moov" in reason.lower()


# ---------- _concat_duration_ok ----------

def test_concat_ok_when_within_tolerance():
    ok, reason = full_dub._concat_duration_ok(probed=660.0, expected=650.0)
    assert ok is True
    assert reason == ""


def test_concat_ok_at_exactly_5pct_boundary():
    # 5% of 650 = 32.5; difference of exactly 32.5 is the edge — inclusive.
    ok, _ = full_dub._concat_duration_ok(probed=682.5, expected=650.0)
    assert ok is True


def test_concat_aborts_when_truncated_beyond_5pct():
    """The silent-truncation failure mode: concat drops corrupted vsegs,
    producing a video much shorter than the timeline total."""
    ok, reason = full_dub._concat_duration_ok(probed=500.0, expected=650.0)
    assert ok is False
    # 500 vs 650 = 23% short
    assert "short" in reason.lower() or "5%" in reason or "%" in reason


def test_concat_aborts_when_too_long_beyond_5pct():
    ok, reason = full_dub._concat_duration_ok(probed=800.0, expected=650.0)
    assert ok is False
    assert "long" in reason.lower() or "%" in reason


def test_concat_invalid_when_probed_zero():
    ok, reason = full_dub._concat_duration_ok(probed=0.0, expected=650.0)
    assert ok is False
    assert "probe" in reason.lower() or "0" in reason


def test_concat_invalid_when_expected_zero():
    ok, reason = full_dub._concat_duration_ok(probed=650.0, expected=0.0)
    assert ok is False


# ---------- stage_retime post-loop verification list ----------

def test_missing_vsegs_reported():
    """_verify_all_vsegs returns the list of indices whose vseg is missing or
    invalid, so stage_retime can name them in its error message."""
    tmp = Path(sys.path[0]) if False else Path("/tmp/nonexistent_test_dir_xyz")
    # Simulate: timeline has 5 segments; only v_0000 and v_0002 exist & valid.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        vd = Path(td) / "_vsegs"
        vd.mkdir()
        (vd / "v_0000.mp4").write_bytes(b"x" * 2000)
        (vd / "v_0002.mp4").write_bytes(b"x" * 2000)
        timeline = [
            {"new_dur": 2.0},
            {"new_dur": 2.0},
            {"new_dur": 2.0},
            {"new_dur": 2.0},
            {"new_dur": 2.0},
        ]
        missing = full_dub._verify_all_vsegs(
            vd, timeline, prober=lambda p: 2.0,
        )
        assert missing == [1, 3, 4]


# ---------- _segment_cmds (frame pinning + degenerate holds) ----------

class TestSegmentCmds:
    """Q3: every segment pins its output to the exact CFR-60 frame count;
    sub-frame spans render as a held frame instead of trusting ffmpeg's
    frame duplication under setpts (the 41-segment incident)."""

    def _seg(self, kind, s, e, new_dur, speed=1.0):
        return {"kind": kind, "orig_start": s, "orig_end": e,
                "new_dur": new_dur, "speed": speed}

    def test_normal_segment_pins_frames(self, tmp_path):
        seg = self._seg("cue", 10.0, 14.0, 4.6, speed=0.87)
        cmds, label = full_dub._segment_cmds(seg, Path("raw.mp4"),
                                             tmp_path / "v_0001.mp4", tmp_path)
        assert len(cmds) == 1
        cmd = cmds[0]
        assert "-frames:v" in cmd
        assert cmd[cmd.index("-frames:v") + 1] == str(round(4.6 * 60))
        assert "minterpolate" in cmd[cmd.index("-vf") + 1]  # slow cue interp

    def test_gap_stretch_pins_frames(self, tmp_path):
        # 0.06s gap stretched 23x — the classic failing shape
        seg = self._seg("gap", 0.492, 0.552, 1.396)
        cmds, label = full_dub._segment_cmds(seg, Path("raw.mp4"),
                                             tmp_path / "v_0002.mp4", tmp_path)
        assert len(cmds) == 1
        cmd = cmds[0]
        assert cmd[cmd.index("-frames:v") + 1] == str(round(1.396 * 60))
        assert "minterpolate" not in cmd[cmd.index("-vf") + 1]

    def test_subframe_gap_uses_held_frame(self, tmp_path):
        # 0.02s span: no real footage, must become a 2-step frame hold
        seg = self._seg("gap", 128.166, 128.186, 1.83)
        cmds, label = full_dub._segment_cmds(seg, Path("raw.mp4"),
                                             tmp_path / "v_0066.mp4", tmp_path)
        assert len(cmds) == 2
        assert cmds[0][cmds[0].index("-ss") + 1] == "128.176"  # midpoint
        assert "-loop" in cmds[1] and "1" == cmds[1][cmds[1].index("-loop") + 1]
        assert cmds[1][cmds[1].index("-frames:v") + 1] == str(round(1.83 * 60))
        assert "-pix_fmt" in cmds[1]  # png loop must land on yuv420p


# ---------- length_gate (pre-synth syllable gate) ----------

class TestLengthGate:
    """Q9: pure-arithmetic gate run between writing translations_dub.txt and
    synth — catches short-line narration traps and lines whose speech cannot
    fit the absorption budget (visible freeze risk) before burning 8h of TTS."""

    @staticmethod
    def _gate():
        spec = importlib.util.spec_from_file_location(
            "length_gate", _HERE.parent / "skills" / "video-dubbing" / "scripts" / "length_gate.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_syllable_counting_matches_rate_report(self):
        m = self._gate()
        assert m.syllables("大家好") == 3
        assert m.syllables("走 Claude Code") == 5   # 走=1, Claude(au,e)=2, Code(o,e)=2
        assert m.syllables("150K token") == 3       # token=2, bare K=1, digits ignored

    def test_short_line_flagged(self, tmp_path, capsys):
        m = self._gate()
        (tmp_path / "transcript").mkdir()
        (tmp_path / "transcript" / "v.en.full.srt").write_text(
            "1\n00:00:00,000 --> 00:00:00,500\nHello, pals.\n\n"
            "2\n00:00:00,550 --> 00:00:06,000\nA longer english sentence here.\n\n",
            encoding="utf-8")
        (tmp_path / "transcript" / "translations_dub.txt").write_text(
            "大家好。\n这是一个足够长的中文句子用来撑住正常的语速。\n", encoding="utf-8")
        old_argv = sys.argv
        sys.argv = ["length_gate.py", str(tmp_path), "v"]
        try:
            m.main()
            rc = 0
        except SystemExit as ex:
            rc = ex.code
        finally:
            sys.argv = old_argv
        out = capsys.readouterr().out
        assert rc == 1
        assert "line 1" in out and "short-line" in out

    def test_budget_math(self):
        m = self._gate()
        # 30 sylls -> est 30/4.9 = 6.1s; budget 3s*1.15 + 1s*0.9 = 4.35 -> freeze 1.77
        est = m.est_duration(30)
        assert abs(est - 30 / 4.9) < 1e-9
        assert m.est_duration(6) == 6 / 3.0
