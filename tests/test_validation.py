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
