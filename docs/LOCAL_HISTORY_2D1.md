# Fixed-model local history — 2D.1, 2026-10-14

Base `b248b4c7bac27def4a131ba61301f2678cd0b05a`, separate branch. No K-search,
period, extraction/selection, mapping, offset or evaluator changes. No skip,
reorder, K change, regime segmentation or online decoding is introduced.

Confirmed discovery mechanism: em_fit compares seed/refinement quality including
periodic boundary coherence. Refinement must exceed seed quality by .0001; ensemble
seed preference also uses .002. Therefore the chosen `raw_hsmm_segments` may be
periodic seed labels. That existing selection remains untouched.

Actual-history estimation is now a separate single `decode_local_history` call.
K, templates, cyclic order, initial phase, period and duration targets are frozen
from discovery. The baseline is a duration prior/reference; no global offset or
templates are optimized. Cyclic-HSMM decoding is reused, with wider local duration
bounds, an observation mask and cooperative deadline. Defaults of the original
decoder callers remain unchanged, including penalty strength2. Masked emissions
are neutral rather than negative observations. Bounds are explicit engineering
scope assumptions, not learned from manual marks: min2s, max180s, factors .1/4,
duration penalty2, transition penalty.25; max10,000 bins, 5M conservative work
units, 15s local deadline, 90s development worker timeout. Durations below two
bins or outside bounds are not promised. Budget failure is unavailable/UNKNOWN.

`reconstruction_history` is additive and separately labelled logical_phase. It
contains model/config provenance, candidate path, supported segments, coverage,
explicit abstention intervals, local boundary diagnostics and runtime. Raw and
baseline schedules remain unchanged. A boundary's grid resolution is not a
calibrated event error interval or measured lamp-switch time. Physical outputs
remain UNKNOWN. The cause of extension/shortening remains UNKNOWN.

Support is deliberately conservative: only positive occupancy bins with a unique
maximum fixed-template emission are returned as local history. All-zero bins
give NO_LOCAL_VEHICLE_EVIDENCE, exact tied maxima give NON_IDENTIFIABLE_PHASE_EMISSIONS,
and caller-supplied missing-input masks give EXPLICIT_INPUT_COVERAGE_GAP. No numeric
observability threshold is fitted. Silence may reflect no demand or blockage;
it identifies neither RED nor a skipped phase. These masks do not establish
camera visibility/coverage. Negative terms in a supported-bin Bernoulli emission
are still an explicit model assumption, not observations of red lamps. Missing
bins may be traversed by the prior internally; that candidate path is retained
only as a diagnostic and is not exposed as supported reconstruction.

Reconstructed core queries prefer `reconstruction_history.segments` when present,
including when it is unavailable or has gaps: there is no fallback to old raw
segments. Prepared immutable queries retain gap reasons and validate contradictory
support/abstention. Outside the history they abstain. Configured/simulated queries
continue to use explicit baseline semantics. Legacy raw estimates remain accessible
in their original schedule fields. The current local scope explicitly abstains
for existing multiple-regime discovery results instead of extending scope.

## Predeclared synthetic evidence

The independent generator uses K2, period80, fixed templates [.98,.02]/[.02,.98],
four cycles of40/40 seconds. The second cycle has hold+10, hold+30 or shortening−10.
Compensated cases retain starts160/240 by adjusting the other positive duration;
additional uncompensated holds retain naturally delayed later starts and40s
neighbor durations. The generation truth precedes decoding, tolerance is ±1s.
Tests establish no artificial global shift of earlier cycles. No-demand and
blocked-GREEN use the same unchanged plan with missing vehicle observations;
their cause is not recoverable. Explicit gaps and cropped intervals remain UNKNOWN.
Synthetic success establishes logical structural behavior, not lamp accuracy.

Initial declaration and additive support tests are sealed before any real
comparison; no hyperparameter search occurs. Logs include66 initial tests,65
regression tests,18 final decoder tests and63 final contract tests, with overlap
among selections. The current code/config is committed before the sole three-file
development run. That run reuses frozen2C predictions, so K search/fitting count is
zero and each recording receives one local decoding. No raw JSON/ZIP is reopened.

All output predictions and hashes are sealed before opening annotation files.
The unchanged evaluator sees separate hashed adapter artifacts: source
`reconstruction_history.segments` is projected into
`schedule.reconstruction_segments`, without rewriting original predictions or
baseline. Raw, baseline and new metrics include counts, ranges, missing reasons,
coverage and timing. This is a development logical-phase comparison; annotations
never enter the worker. Sparse real evidence may yield low coverage and worse
boundary recall; that is reported rather than filled by periodic assumptions.
