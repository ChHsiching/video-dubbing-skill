"""Tests for the pure check logic: identity-assemble math + length_gate.

These test the pure functions directly — the heavy deps (indextts,
torch, ffmpeg) are not touched. The length_gate main() tests drive the
gate end-to-end on tiny fixture files in tmp_path.
"""
import importlib.util
import sys
from pathlib import Path

# Load full_dub.py / length_gate.py as modules without importing a package.
_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent / "skills" / "video-dubbing" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


full_dub = _load("full_dub")


# ---------- assemble math (identity timeline) ----------

class TestAssembleMath:
    def test_window_runs_to_next_cue_start(self):
        # window = next cue's start - this start (not this cue's end): the
        # following pause belongs to this cue's absorption budget.
        cues = [(1, 10.0, 12.0, "en", "zh"), (2, 15.0, 18.0, "en", "zh")]
        assert full_dub.cue_window(cues, 0, 100.0) == 5.0

    def test_last_cue_window_runs_to_video_end(self):
        cues = [(1, 10.0, 12.0, "en", "zh")]
        assert full_dub.cue_window(cues, 0, 100.0) == 90.0

    def test_fit_factor_lands_audio_in_window(self):
        assert abs(full_dub.fit_factor(6.0, 5.0) - 1.2) < 1e-9
        assert full_dub.fit_factor(5.0, 5.0) == 1.0
        # faster-than-window audio is slowed down (factor < 1) — the window
        # fills either way; the budget, not the synth, sets the target
        assert abs(full_dub.fit_factor(4.0, 5.0) - 0.8) < 1e-9

    def test_fit_factor_zero_window_is_noop(self):
        assert full_dub.fit_factor(3.0, 0.0) == 1.0

    def test_clamp_keeps_atempo_in_filter_range(self):
        assert full_dub.clamp_factor(9.0) == 2.0
        assert full_dub.clamp_factor(0.1) == 0.5
        assert full_dub.clamp_factor(1.2) == 1.2


# ---------- length_gate (pre-synth syllable + coverage gate) ----------

class TestLengthGate:
    """Pure-arithmetic gate run between writing translations_dub.txt and
    synth — catches short-line narration traps, per-line budget misses, and
    a uniformly thin translation (coverage) before burning hours of TTS."""

    @staticmethod
    def _gate():
        return _load("length_gate")

    def test_syllable_counting(self):
        m = self._gate()
        assert m.syllables("大家好") == 3
        assert m.syllables("走 Claude Code") == 5   # 走=1, Claude(au,e)=2, Code(o,e)=2
        assert m.syllables("150K token") == 3       # token=2, bare K=1, digits ignored

    def _write_fixtures(self, tmp_path, zh_lines, cues):
        (tmp_path / "transcript").mkdir(exist_ok=True)
        srt = "".join(
            f"{i+1}\n{c[0]} --> {c[1]}\nEnglish cue {i+1}.\n\n" for i, c in enumerate(cues))
        (tmp_path / "transcript" / "v.en.full.srt").write_text(srt, encoding="utf-8")
        (tmp_path / "transcript" / "translations_dub.txt").write_text(
            "\n".join(zh_lines) + "\n", encoding="utf-8")

    def _run(self, m, tmp_path, capsys):
        old_argv = sys.argv
        sys.argv = ["length_gate.py", str(tmp_path), "v"]
        try:
            m.main()
            rc = 0
        except SystemExit as ex:
            rc = ex.code
        finally:
            sys.argv = old_argv
        return rc, capsys.readouterr().out

    def test_short_line_flagged(self, tmp_path, capsys):
        m = self._gate()
        self._write_fixtures(
            tmp_path,
            ["大家好。", "这是一个足够长的中文句子用来撑住正常的语速。"],
            [("00:00:00,000", "00:00:00,500"), ("00:00:00,550", "00:00:06,000")])
        rc, out = self._run(m, tmp_path, capsys)
        assert rc == 1
        assert "line 1" in out and "short-line" in out

    def test_coverage_underfill_fails(self, tmp_path, capsys):
        """A uniformly thin translation passes the line checks but dubs to
        long silences — the coverage total is what catches it."""
        m = self._gate()
        # two 6s windows, ~10 sylls each -> ~2.4s est each: coverage ~40%
        self._write_fixtures(
            tmp_path,
            ["这是一个很短的句子。", "这又是一个很短的句子。"],
            [("00:00:00,000", "00:00:06,000"), ("00:00:06,100", "00:00:12,000")])
        rc, out = self._run(m, tmp_path, capsys)
        assert rc == 1
        assert "coverage" in out and "FAIL" in out

    def test_budget_math(self):
        m = self._gate()
        assert abs(m.est_duration(30) - 30 / 4.9) < 1e-9
        assert m.est_duration(6) == 6 / 3.0

    def test_over_budget_line_flagged(self, tmp_path, capsys):
        m = self._gate()
        # 1s window + 0.1s gap = 1.1s budget; a 21-char line ests 21/4.9=4.3s
        # -> factor ~3.9x: text nowhere near its budget
        self._write_fixtures(
            tmp_path,
            ["这是一个明显超出时间窗口预算长度的中文句子。",
             "这是一个足够长的中文句子用来撑住正常的语速和覆盖率的检查要求。"],
            [("00:00:00,000", "00:00:01,000"), ("00:00:01,100", "00:00:09,000")])
        rc, out = self._run(m, tmp_path, capsys)
        assert rc == 1
        assert "over budget" in out and "line 1" in out
