# -*- coding: utf-8 -*-
"""Audit fixes for video-dubbing-skill (wfa f4/f5/f6 + unslop f7/f15/f17)."""
import io

p = 'skills/video-dubbing/SKILL.md'
c = io.open(p, encoding='utf-8').read()

reps = [
 # wfa f4 + unslop f7: slim feature inventory, de-dash
 ('''**Use `cook dub synth` — do not hand-roll worker scripts.** It already has
band-split multi-worker (`--workers/--stagger`), `DUB_DURATION_FACTOR`,
two-voice `speakers.txt`, skip-if-exists resume, and atomic publish. Every
run-local "adapted from last run's worker" script is a fork of this stage
that the fixes below will never reach.''',
  '''**Use `cook dub synth`; do not hand-roll worker scripts.** It already
ships everything a run-local worker reinvents (see the flags below).
Every adapted copy is a fork this document's fixes never reach.'''),

 # unslop f7: Step 3 heading line dash
 ('**Rate-lock order (hard — translation written before the rate is a draft,\nnot a script).** The locked sequence is:',
  '**Rate-lock order (hard: translation written before the rate is a draft,\nnot a script).** The locked sequence is:'),

 # wfa f6 + unslop f7: sidecar lines
 ('''2. `cook dub measure-rate --write dubbed/_reference/rate.json` on the
   WINNING pilot takes — per speaker when speakers.txt exists. The sidecar
   carries the provenance: rates + duration_factor + ref md5s.''',
  '''2. `cook dub measure-rate --write dubbed/_reference/rate.json` on the
   WINNING pilot takes, per speaker when speakers.txt exists. The sidecar
   carries the provenance: rates, duration_factor, ref md5s.'''),

 ('''4. `cook dub gate <output_root> <name> --rate-file dubbed/_reference/rate.json`
   — the gate computes each cue's budget from the transcript windows and
   the sidecar rates, shaves the breathing reserve, and checks every line
   and the coverage total. A typed `--rate` needs `--rate-override`.''',
  '''4. `cook dub gate <output_root> <name> --rate-file dubbed/_reference/rate.json`.
   The gate computes each cue's budget from the transcript windows and
   the sidecar rates, shaves the breathing reserve, and checks every line
   and the coverage total. A typed `--rate` needs `--rate-override`.'''),

 # unslop f15: sin
 ('A translation drafted before step 2 must be re-gated against the measured\nrates — and re-written wherever the measured budget says so. An assumed\nrate is not a smaller sin here: it passes every line check and still dubs\nto dead air.',
  'A translation drafted before step 2 must be re-gated against the measured\nrates, and re-written wherever the measured budget says so. An assumed\nrate passes every line check and still dubs to dead air.'),

 # wfa f5 + unslop f7: breath defaults out, --help pointer in
 ('''(procedure: Step 3a; "
        "the gate consumes the sidecar via `--rate-file`). The gate's "
        "budget shaves a breathing reserve (`--breath`, default 0.12s on "
        "windows above `--breath-min-window`, default 1.2s) so a "
        "fully-filled budget still leaves an audible gap before the next "
        "cue — defaults are calibration starting points, tune per voice.''',
  None),  # handled below via looser match

 # wfa f6: recalibration sentence to sidecar path
 ('re-run `cook dub measure-rate` on the new winner\'s takes before any further gate call.',
  're-run `cook dub measure-rate --write` on the new winner\'s takes and re-gate with `--rate-file` before any further gate call.'),

 # unslop f7: Step 2 reuse dash
 ('**Reuse ruling: a previous run\'s reference is the fallback, not the default** — scan THIS run\'s audio and audition its candidates every time;',
  '**Reuse ruling: a previous run\'s reference is the fallback, not the default.** Scan THIS run\'s audio and audition its candidates every time;'),

 # unslop f7 + wfa: Step 5 fit bullet dash / colon splice f17
 ('''- **Fit pass — automatic, compress only, never stretch.** Synthesis
        edge-trims every take at publish (true silence below -45dB, 80ms
        margins), so the fit pass sees honest durations. A take that still
        runs past its window (cue start → next cue's start) is atempo'd
        down to fit; a residual beyond the atempo cap is hard-cut to the
        window end with a 30ms fade (broadcast ducking — the cue is over
        budget and buried under the next speaker) and logged `CUT idx N`:''',
  None),  # looser match below

 # unslop f7: Place bullet dash
 ('the "\n        "placement invariant (`placed - start <= 20ms`) is enforced inside "\n        "the loop — a take overrunning past the next cue\'s start fails the "\n        "assemble instead',
  None),
]
# apply exact reps
for old, new in reps:
    if new is None:
        continue
    assert old in c, old[:60]
    c = c.replace(old, new)

# wfa f5: breath sentence (match actual formatting)
old = ('the gate consumes the sidecar via `--rate-file`). The gate\'s '
       'budget shaves a breathing reserve (`--breath`, default 0.12s on '
       'windows above `--breath-min-window`, default 1.2s) so a '
       'fully-filled budget still leaves an audible gap before the next '
       'cue — defaults are calibration starting points, tune per voice.')
new = ('the gate consumes the sidecar via `--rate-file`). The gate\'s '
       'budget shaves a breathing reserve (`--breath`) so a fully-filled '
       'budget still leaves an audible gap before the next cue. Defaults '
       'are calibration starting points, tune per voice '
       '(`cook dub gate --help`).')
assert old in c, 'breath sentence'
c = c.replace(old, new)

# Step 5 fit bullet (match actual)
old = ('''- **Fit pass — automatic, compress only, never stretch.** Synthesis '''
       '''edge-trims every take at publish (true silence below -45dB, 80ms
margins), so the fit pass sees honest durations. A take that still
runs past its window (cue start → next cue's start) is atempo'd
down to fit; a residual beyond the atempo cap is hard-cut to the
window end with a 30ms fade (broadcast ducking — the cue is over
budget and buried under the next speaker) and logged `CUT idx N`:''')
new = ('''- **Fit pass — automatic, compress only, never stretch.** Synthesis
edge-trims every take at publish (true silence below -45dB, 80ms
margins), so the fit pass measures durations without the pad silence.
A take that still runs past its window (cue start → next cue's start)
is atempo'd down to fit. A residual beyond the atempo cap is hard-cut
to the window end with a 30ms fade, the broadcast-ducking shape (the
cue is over budget and buried under the next speaker), and logged
`CUT idx N`.''')
assert old in c, 'fit bullet'
c = c.replace(old, new)
# the sentence following the bullet previously spliced via colon; fix its lead
old2 = ('Audio shorter than its window keeps its natural pace and the window '
        'gets a breathing pause')
if old2 in c:
    c = c.replace(old2, 'Audio shorter than its window keeps its natural '
                        'pace and the window gets a breathing pause', 1)

# Place bullet dash
old = ('the placement invariant (`placed - start <= 20ms`) is enforced '
       'inside the loop — a take overrunning past the next cue\'s start '
       'fails the assemble instead')
new = ('the placement invariant is enforced inside the loop: a take '
       'overrunning past the next cue\'s start fails the assemble instead')
assert old in c, 'place bullet'
c = c.replace(old, new)

io.open(p, 'w', encoding='utf-8').write(c)
print('dubbing skill polished')
