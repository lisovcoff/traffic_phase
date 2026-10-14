# One sealed 2C development run

Base: `36b6752a4794e482570944b22656d6cc58f0db31`.
Implementation: `25db3dfbaa9c852fb9644d8a934285ba2cf3a47a`.
Pre-benchmark seal: `04b965bfd430da2272657282a4162e67c62420fe`.
Exactly one unchanged standard benchmark was run, dt=1, seed=0, tolerance ±2s,
hard worker timeout 90s/file. No code/config/parameters were changed afterwards.
Frozen baseline is benchmarks/stage2b1_20261013; config/source/annotation hashes
match, and original baseline artifacts remain unchanged.

## Structural checks

8 predeclared tests passed (including two compact real K2..4 recovery searches,
K4 chosen before/after bijective stream renaming). K5..8 admission was verified
only with a cheap fit stub. 5 affected existing selector/redundancy regressions,
33 contract checks and 26 config/leakage/regime/evaluator tests passed. Overlap
among these test selections is intentional; their totals are not a count of
unique tests. No full archive or K5..8 training was performed.

The independent three-subphase example with a shared fourth movement retained
all three supported phases. Redundancy logic remains byte-for-byte functionally
unchanged. All fit.py functions except discover_phase_count have identical ASTs
to base, including em_fit and evaluate_phase_redundancy. Protected detector,
period, evaluator, uncertainty, mapping and UI source paths are unchanged.

## Before/after

Quality metrics below are identical before and after. M/T/P means matched,
truth and predicted interior boundaries within the evaluator's annotated range.
MAE and p95 use matches within ±2s; nearest MAE is a separate all-truth-boundary
diagnostic. Full observation counts, ranges, missing reasons, period error and
coverage are preserved in comparison.json and baseline_metrics.json.

| Recording | K before→after | Candidates | Runtime seconds | Raw M/T/P | Raw precision/recall | Raw MAE/p95, s | Baseline M/T/P | Baseline precision/recall | Baseline MAE/p95, s |
|---|---|---|---|---|---|---|---|---|---|
| 17 | 3→3 | 2→5 | 28.358→32.488 | 15/17/18 | .833/.882 | .709/1.485 | 15/17/17 | .882/.882 | .748/1.786 |
| 19 | 2→2 | 2→5 | 17.204→19.112 | 1/8/8 | .125/.125 | 1.546/1.546 | 1/8/8 | .125/.125 | 1.599/1.599 |
| 6 | 3→3 | 2→5 | 20.248→23.858 | 3/9/15 | .200/.333 | 1.471/1.797 | 1/9/15 | .067/.111 | 1.418/1.418 |

Nearest-boundary MAE raw/baseline respectively: recording17 1.105/1.086s;
recording19 4.782/3.952s; recording6 2.806/2.752s, all unchanged.
Period and period-error metrics are unchanged. Raw/baseline temporal coverage
is 1.0 for all three annotated ranges; it is not physical observability or lamp
accuracy. Full schedule dictionaries, phase segments, event evidence core fields
and period dictionaries also compare exactly against the frozen predictions.

Every recording evaluated K2..6. Search was complete within the configured
cooperative budget; no timeout, skipped K, budget overrun or unavailable metric
occurred. Search times were 9.404, 2.983 and 9.282s respectively, distinct from
end-to-end benchmark runtime. All runtimes increased; these are single-run wall
times on different historical executions, not a controlled microprofile.

K4 for recording19 remained eligible but lost by the unchanged criterion. K4+
for recordings17/6 and some K5/6 candidates were evaluated, then excluded by
the existing multiple-unsupported-signature rule. Their finite criterion scores,
exclusion reasons, event counts and unsupported phases remain available.
Selected K3 for recordings17/6 has one unsupported signature despite nonzero
events in every phase: the report states UNSUPPORTED_PHASES_OR_NO_EVENTS and
does not convert the score margin into confidence. Recording19 has model
signature support, explicitly without independent external validation.

There is no quality improvement on the three recordings. The historical
recording6 K regression and low boundary recall persist. Removing the hard cap
solves candidate admission and naming invariance, not event semantics or phase
identifiability. Next work should use independent event/lamp validation and
separately investigate the existing support/complexity assumptions with new
predeclared structural cases; no parameter selection from this run is justified.
Work stops here, without starting 2D.
