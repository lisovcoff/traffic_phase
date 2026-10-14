# 2D.1 development results and limits

**FAIL / NOT ACCEPTED.** Later confirmed diagnostic-candidate matches are7/34
(3/17,1/8,3/9), also worse than raw19/34. The sparse review restores accepted2C
defaults and makes this history explicitly opt-in; see SPARSE_OBSERVATION_2D1_REVIEW.md.

Base `b248b4c7bac27def4a131ba61301f2678cd0b05a`; implementation/config sealed at
`400dad78f7276ac025427e7cef02af9ef3d58fb6` before the sole development run.
No code or configuration was tuned after reading its results. No K search,
template fitting, offset fitting, raw trajectory or ZIP reads occurred in this
run. Each of three frozen2C models received one local decoding. All prediction
hashes were sealed before evaluation. The evaluator and ±2s tolerance are unchanged.

Independent dense synthetic cases passed the predeclared ±1s logical-boundary
tolerance for stable, +10/+30 hold, shortening and compensated/uncompensated
timelines. Adjacent cycles retain generated timings, without an artificial global
offset. Silence/blocked demand, tied templates, explicit gaps and cropped intervals
abstain. Test selections:66 initial,65 regression,18 final decoder and63 final
contract tests passed; selections overlap. This is not real or lamp accuracy.

## Preserved recurring model

| Recording | K | Period, s | Local worker runtime, s | Decoder runtime, s |
|---|---|---|---|---|
| 17 | 3 | 99.84281321021679 | 6.336 | .802 |
| 19 | 2 | 120.02849954941996 | 4.895 | .128 |
| 6 | 3 | 99.99524773335186 | 6.057 | .669 |

Schedule, selection, period inference and event extraction dictionaries compare
exactly with the frozen input. Old raw/baseline segments and metrics are preserved.
Worker time includes loading/serialization/process overhead; it is not directly
comparable to historical full-discovery runtime. No timeout/work-budget exhaustion
occurred. All new histories have status ok, with partial supported coverage.

## Separate history evaluation

M/T/P = matched/truth/predicted interior boundaries. Precision/recall and MAE/p95
refer to the unchanged evaluator. Coverage is annotated-range temporal support;
physical observability and camera coverage are not measured.

| Recording | History | M/T/P | Precision / recall | Matched MAE / p95, s | Nearest MAE, s | Coverage |
|---|---|---|---|---|---|---|
| 17 | raw | 15/17/18 | .833 / .882 | .709 / 1.485 | 1.105 | 100% |
| 17 | baseline | 15/17/17 | .882 / .882 | .748 / 1.786 | 1.086 | 100% |
| 17 | new | 0/17/0 | unavailable / 0 | unavailable | unavailable | 15.208% |
| 19 | raw | 1/8/8 | .125 / .125 | 1.546 / 1.546 | 4.782 | 100% |
| 19 | baseline | 1/8/8 | .125 / .125 | 1.599 / 1.599 | 3.952 | 100% |
| 19 | new | 0/8/3 | 0 / 0 | unavailable | 60.807 | 33.526% |
| 6 | raw | 3/9/15 | .200 / .333 | 1.471 / 1.797 | 2.806 | 100% |
| 6 | baseline | 1/9/15 | .067 / .111 | 1.418 / 1.418 | 2.752 | 100% |
| 6 | new | 0/9/1 | 0 / 0 | unavailable | 210.527 | 25.216% |

New matched MAE/p95 are unavailable because there are no matches within tolerance;
recording17 precision and nearest MAE are unavailable because no supported
adjacent predicted boundaries exist. Full ranges/counts/missing reasons are in
comparison.json. Evaluated field is schedule.reconstruction_segments in a separate
hashed adapter sourced from reconstruction_history.segments, not overwritten raw.

## Regression and identifiability

The new history has **0/34 matched boundaries**, versus raw19/34 and baseline17/34.
This is a severe real-data boundary/coverage regression. Returning only observed
positive bins creates fragmented segments: unsupported candidate boundaries are
retained diagnostically but do not count as supported history. The unchanged
evaluator counts transitions only across adjacent supported intervals; gaps are
not filled. There are282/160/532 NO_LOCAL_VEHICLE_EVIDENCE intervals respectively
over the full input extents. Lack of traffic events establishes neither a camera
gap, RED, skipped phase nor cause of blockage. The strict support policy is an
engineering assumption, not independently validated observability calibration.

The dense synthetic recovery confirms that a nonperiodic fixed-template decoder
can represent local duration changes. It does not establish a usable real-event
observation model. The local decoder's prior-assisted candidate path is not claimed
as independently identified history. Current raw/baseline remain separately
available; reconstructed queries deliberately abstain in the new history's gaps.
Physical states and causes remain UNKNOWN.

Next investigation should independently establish how selected vehicle evidence
supports intervals and how demand/blockage affect identifiability, then preregister
any interval-support observation model on independent data. Do not tune gap filling,
duration bounds or uncertainty on these three annotations. No such change was made
after this result. 2D.2/online work is not started.
