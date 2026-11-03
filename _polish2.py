# -*- coding: utf-8 -*-
"""Second pass: the five dubbing reps that never landed (first script died
mid-assert before its single write), plus remaining cook.py/length_gate.py
instances from the unslop audit."""
import io

# ---- dubbing SKILL.md: five missing reps ----
p = 'C:/Users/Administrator/Git/video-dubbing-skill/skills/video-dubbing/SKILL.md'
c = io.open(p, encoding='utf-8').read()
reps = [
 ('''**Use `cook dub synth` — do not hand-roll worker scripts.** It already has
band-split multi-worker (`--workers/--stagger`), `DUB_DURATION_FACTOR`,
two-voice `speakers.txt`, skip-if-exists resume, and atomic publish. Every
run-local "adapted from last run's worker" script is a fork of this stage
that the fixes below will never reach.''',
  '''**Use `cook dub synth`; do not hand-roll worker scripts.** It already
ships everything a run-local worker reinvents (see the flags below).
Every adapted copy is a fork this document's fixes never reach.'''),
 ('**Rate-lock order (hard — translation written before the rate is a draft,\nnot a script).**',
  '**Rate-lock order (hard: translation written before the rate is a draft,\nnot a script).**'),
 ('''   WINNING pilot takes — per speaker when speakers.txt exists. The sidecar
   carries the provenance: rates + duration_factor + ref md5s.''',
  '''   WINNING pilot takes, per speaker when speakers.txt exists. The sidecar
   carries the provenance: rates, duration_factor, ref md5s.'''),
 ('''   --rate-file dubbed/_reference/rate.json`
   — the gate computes each cue's budget from the transcript windows and''',
  '''   --rate-file dubbed/_reference/rate.json`.
   The gate computes each cue's budget from the transcript windows and'''),
 ('A translation drafted before step 2 must be re-gated against the measured\nrates — and re-written wherever the measured budget says so. An assumed\nrate is not a smaller sin here: it passes every line check and still dubs\nto dead air.',
  'A translation drafted before step 2 must be re-gated against the measured\nrates, and re-written wherever the measured budget says so. An assumed\nrate passes every line check and still dubs to dead air.'),
 ('**Reuse ruling: a previous run\'s reference is the fallback, not the default** — scan THIS run\'s audio and audition its candidates every time;',
  '**Reuse ruling: a previous run\'s reference is the fallback, not the default.** Scan THIS run\'s audio and audition its candidates every time;'),
]
for old, new in reps:
    assert old in c, old[:60]
    c = c.replace(old, new)
io.open(p, 'w', encoding='utf-8').write(c)
print('dubbing: 6 reps landed')

# ---- cook.py: remaining instances ----
p = 'C:/Users/Administrator/Git/video-cook/cook.py'
c = io.open(p, encoding='utf-8').read()
reps = [
 ('_die(f"--rate-file {path} has no positive \'rate\' — regenerate it "',
  '_die(f"--rate-file {path} has no positive \'rate\'. Regenerate it "'),
 ('''        _log(f"gate: rate-file was measured at duration_factor={df} but the "
             f"env now says {os.environ.get('DUB_DURATION_FACTOR', '1.0')} — "
             "rates are df-dependent; re-measure if df changed")''',
  '''        _log(f"gate: rate-file was measured at duration_factor={df} but the "
             f"env now says {os.environ.get('DUB_DURATION_FACTOR', '1.0')}. "
             "Rates are df-dependent; re-measure if df changed")'''),
 ('''                     help="rate sidecar written by `cook dub measure-rate "
                          "--write` — the preferred rate source (provenance: "
                          "df, ref md5s, per-speaker rates via speakers.txt)")''',
  '''                     help="rate sidecar written by `cook dub measure-rate "
                          "--write`; the preferred rate source (provenance: "
                          "df, ref md5s, per-speaker rates via speakers.txt)")'''),
]
for old, new in reps:
    assert old in c, old[:60]
    c = c.replace(old, new)
io.open(p, 'w', encoding='utf-8').write(c)
print('cook.py: 3 reps landed')

# ---- full_dub.py: remaining comment dash ----
p = 'C:/Users/Administrator/Git/video-cook/stages/dub/full_dub.py'
c = io.open(p, encoding='utf-8').read()
old = '''                # unreachable while the fit pass cuts every residual; a
                # regression guard, not a recovery path — 46 cues up to'''
new = '''                # unreachable while the fit pass cuts every residual; a
                # regression guard, not a recovery path (46 cues up to'''
assert old in c
c = c.replace(old, new)
io.open(p, 'w', encoding='utf-8').write(c)
print('full_dub.py: 1 rep landed')

# ---- length_gate.py: remaining docstring dashes ----
p = 'C:/Users/Administrator/Git/video-cook/stages/dub/length_gate.py'
c = io.open(p, encoding='utf-8').read()
reps = [
 ('''    label->chars/s map (a measure-rate sidecar's per_speaker block) — each
    cue gates by its own speaker's rate, falling back to `rate` per label.''',
  '''    label->chars/s map (a measure-rate sidecar's per_speaker block). Each
    cue gates by its own speaker's rate, falling back to `rate` per label.'''),
 ('''    breath_s/breath_min_window_s: the breathing reserve (see BREATH_*
    above) — windows longer than the exemption are budgeted at''',
  '''    breath_s/breath_min_window_s: the breathing reserve (see BREATH_*
    above); windows longer than the exemption are budgeted at'''),
 ('            f"speakers.txt has {len(speakers)} labels vs {len(lines)} "
            "translation lines — per-speaker gating needs the 1:1 pairing")',
  '            f"speakers.txt has {len(speakers)} labels vs {len(lines)} "
            "translation lines; per-speaker gating needs the 1:1 pairing")'),
]
for old, new in reps:
    assert old in c, old[:60]
    c = c.replace(old, new)
io.open(p, 'w', encoding='utf-8').write(c)
print('length_gate.py: 3 reps landed')
