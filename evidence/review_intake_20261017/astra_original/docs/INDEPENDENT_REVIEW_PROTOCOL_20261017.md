# Independent review: one seed-flow correction

Reviewed base: b7675c70bf191a20454fe974baa18cc161f01856.
Task branch: review/seed-flow-20261017. Main and historical artifacts unchanged.

## Frozen hypothesis and scope (before new development inference)

The two K3 internal split candidates never reach fitting because deduplication
runs before they are appended. Move the existing deduplication block after all
candidate generation. No other production change. Keep seed construction,
ordering among existing seeds, ensemble preference, objectives, extraction,
selection, period, K bounds/criterion, Bernoulli model and decoder unchanged.
Known score/ensemble/circular/support/ranking/baseline defects are independently
recorded, not bundled into this correction. No thresholds/offsets/prior tuning.

Independent regression gate: both distinct split parents visit template fitting
and refinement at dt=.5/1/2; duplicates are not refitted; K2 unchanged; existing
K4/renaming/shared movement/search budget/recurrence/cache/state tests pass.
Strict expected failures for other defects remain visible.

## One bounded development comparison

Only the three saved lossless event bundles at
benchmarks/stage2c_20261014/predictions/*_v9.json are inputs. Verify their exact
event/selection/anchor reconstruction using the existing cached_bundle function.
No raw JSON/ZIP ingestion, no large archives, no parameter search.

One unchanged b7675c7 control on record19, then at most three corrected workers,
one per existing development record. Each worker has a hard90s timeout; total
worker allowance360s. Ordinary K2..6/max5/cooperative60s, dt1, seed0, one thread.
Control must reproduce saved corrected schedule/period/K exactly; otherwise stop.
Seal code/input/output hashes and source-selection traces before scoring. No retry
or code/parameter adjustment after seeing new results. These are development
recordings, not an independent holdout.

The original *_manual_marks.json files are absent. No invented annotation file
or phase label reconstruction is permitted. After sealing predictions, use the
already saved complete interior truth-boundary set (matches.truth_ms union
missed_truth_ms) and known interval from the historical corrected comparison.
Require raw/baseline truth sets to agree. Run the existing unchanged
offline_benchmark.match_boundaries and segments_absolute at tolerance2s.
First reproduce ALL saved boundary metrics and coverage from the historical
predictions. This is a boundary-only replay against saved annotation-derived
targets, not a new full evaluate_prediction run or independent validation.
If this parity check fails, new boundary metrics are UNAVAILABLE. Report K against
the saved expert distinct-label count; do not claim full controller K ground truth.

## Predeclared acceptance and rejection

Structural success does not imply real accuracy. For a useful development result:

- No previously correct K becomes incorrect; number of matching K increases,
  OR total raw matched boundaries increases above19/34 with no loss in K matches.
- Every record's raw matched count and precision must not decrease; aggregate
  precision must be at least19/41. Report any tradeoff as a regression, not success.
- Nearest MAE must not increase in any record; matched MAE/p95 are separately
  reported conditional diagnostics, never substitutes for recall/false positives.
- Raw/baseline coverage, logical UNKNOWN and physical UNKNOWN remain explicit;
  no physical or calibrated lamp probability claim. Local2D.1 stays off/FAIL.
- All requested K candidates must finish; hard90s/worker remains the runtime gate.

Report per record and history: K, matched/truth/predicted, precision/recall±2s,
matched MAE/p95, nearest MAE, temporal coverage/logical UNKNOWN, physical UNKNOWN,
worker runtime with cached-only scope. Preserve periodic baseline as a second
history and both historical code/predictions as immutable controls.

Identical schedules/metrics refute benefit on these inputs (not the existence of
the code defect). Worse K/boundaries or exhausted budget reject the usefulness
hypothesis for this change. Stop after this comparison regardless of outcome.
