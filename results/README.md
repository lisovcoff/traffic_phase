# Validation and accuracy limits

[English](README.md) · [Русский: предел точности](accuracy_limits.ru.md)

**Status: research prototype; universal 95% physical-signal accuracy is not
established. The theoretical maximum on these six archives is unknown.**
Latest: [integrated v8](causal_v8.md), 93.51% on eight independent SUMO controls,
with explicit strict-gate failures and real/browser receipts. Earlier v7 and
experimental measurements below remain historical.

This page summarizes earlier production measurements. Dated follow-ups describe
new validation and experimental algorithm runs.
The [delivery receipt](delivery_readiness.json) records real HTTP replay and cold
journal recovery separately from the still-failed physical-estimator acceptance.
The earlier [queue-front timing stage](front_release_timing.md) restores the
period-change GREEN recall and improves five known SUMO controls beyond 95%,
but excess false GREEN and a real onset regression blocked promotion at that stage.
The [section-support follow-up](section_consensus.md) recovers the four real
seconds lost in the [joint timing stage](transition_timing.md), but persistent
timing changes still fail GREEN-recall/false-GREEN gates; default v7 was retained at that stage.
The [2026-10-20 physical-validation follow-up](physical_validation.md) adds
independent SUMO controls and original-video brackets. It identifies limitations
in the old custom simulator; the historical synthetic scores below are software
stress checks, not sufficient evidence of real-road fidelity.
[Machine-readable counts and provenance](summary.json) identify the frozen
source receipts in revision `9924a35`; full saved runs remain local and in that
Git revision. The application never receives validation videos or lamp labels.

## Real-data coverage

| Archive | What the available independent reference supports |
|---|---|
| Lenina–Sverdlovsky, February 11–19 | Offline trajectory model; no complete independent lamp history |
| Lenina–Sverdlovsky, February 27 | Visible N main head in two previously revealed five-minute windows; conditional vehicle-based clock mapping |
| Lenina–Enthusiasts, October 5 | Visible E head and crash video; JSON/video clock association remains unaccepted |
| Lenina–Enthusiasts, February 10–17 | No paired independent lamp reference |
| Chicherina–40 Let Pobedy, April 12 | No paired independent lamp reference |
| Chicherina–40 Let Pobedy, April 19 | No paired independent lamp reference |

The corpus run processed 219 sources: 216 ZIP members and three loose JSONs.
Successful parsing, movement prediction, K agreement and lamp-color accuracy
are different measurements. No archive has complete video-confirmed truth for
every approach, additional section and second. An E/W pair assumed equivalent
is not two independently observed heads. The crash does not reveal invisible N.

## Selected measured results

| Evaluation | Result | Scope |
|---|---|---|
| Offline discovery, 24 reserved synthetic cases | K 24/24; phase-state error 2.85% | Automatic discovery; simulator truth; now revealed, not a new holdout |
| Cross-day replay, visible N onsets | 18/18 within 5s; 11/18 within 2s; one extra red onset | Two known video windows, conditional clock; not all colors/heads |
| Production, original labelled N GREEN/YELLOW | 147/153 = 96.08% | Narrow known window; RED and RED_YELLOW excluded |
| Production, copied JSON with +12s green | 147/165 = 89.09% | Counterfactual time warp; not an observed emergency |
| Production, 12 synthetic streams | 66,848/77,280 = 86.50% | All four main heads/colors; UNKNOWN counts as incorrect |
| Production, 4 later synthetic controls | 22,297/25,760 = 86.56% | Fresh at candidate freeze; now revealed |
| Experimental 10s history, same 4 controls | 23,903/25,760 = 92.79% | Delayed history, not instantaneous output; candidate disabled for regressions |

No result above proves automatic hardware discovery and video-confirmed
all-head accuracy jointly. Online scores use the structure learned offline;
they do not test discovering K again on each incoming packet. Per-second samples
are correlated, so treating every second as an independent trial would give
misleading confidence intervals. Do not pool unlike scopes into one percentage.

The production 12-stream score is dominated by RED. Per-color recall makes
transition failures visible:

| True color | Correct / labelled head-seconds | Recall |
|---|---|---|
| GREEN | 18,284 / 21,069 | 86.78% |
| RED | 48,148 / 51,962 | 92.66% |
| YELLOW | 337 / 2,550 | 13.22% |
| RED_YELLOW | 79 / 1,699 | 4.65% |

Mean recall across these four colors is **49.33%**. The 86.50% overall result
therefore does not establish reliable short transition colors. Future acceptance
must retain per-color and false-GREEN checks, not just an aggregate 95% target.

## Why an exact theoretical ceiling is unavailable

The input-to-signal mapping need not be unique. A stationary queue can coexist
with either RED or GREEN plus an unseen obstruction. No arrivals reveal no lamp
color. A permissive turn does not establish whether an additional arrow exists.
An empty approach can hide a controller phase. More tuning cannot distinguish
worlds with identical observations without additional assumptions.

The [constructive witness](nonidentifiability_witness.json) records one identical
input compatible with K=3 and K=4. Observed movements keep exactly the same
signal intervals. This is an impossibility example, **not a measured ceiling on
the six real archives**, and does not imply that 95% on a specified dataset is
impossible. Reproduce the construction without private data:

```sh
python -m pytest -q tests/test_corpus_realistic_validation.py -k absent_traffic
```

Formally, for N scored positions and two admissible histories with the same
input but D differing labels, any single prediction makes at least D errors
across the two histories combined. Its worst-case accuracy on one history is at
most `1 - D/(2*N)`. With equal prior probability this is also an average-accuracy
upper bound. D and the prior distribution are unknown for the six real archives;
this expression cannot supply their numeric maximum.

Even full video truth would measure performance, not certify global optimality
over every possible algorithm. Therefore “stop at the theoretical maximum” has
no verifiable numerical stopping condition with the current materials.

## Acceptance protocol for further changes

1. Freeze algorithm, source split, clock mapping and metrics before opening new
   labels. Keep video, source names and hand-set topology out of inference.
2. Report automatic approach/K/section discovery separately from timing against
   a fixed offline structure. Score all main colors and available arrows,
   UNKNOWN coverage, false GREEN episodes and onset precision/recall.
3. Score instantaneous and delayed estimates separately. Include startup,
   persistent new cycle lengths, isolated extensions, blocked approaches and
   missing detections; retain ordinary-yellow and K2/K3 regression checks.
4. Use independent, clock-supported visible-head intervals where available.
   Leave unobservable heads and unpaired archives unscored rather than invent
   truth. Existing labels may guide development but are no longer fresh tests.
5. Promote a candidate only after measured improvement without critical
   regressions. Current duration/observation candidates have not passed this gate.

Private datasets and generated full reports are excluded from new Git trees.
Historical receipts remain retrievable from the provenance revision. The small
generator specification under `tests/fixtures/` is public so unit tests do not
depend on those local reports.
