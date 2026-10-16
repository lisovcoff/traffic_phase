# HSMM recurrence arithmetic correction — predeclared scope

Base `5b84eab96966f2220d85978056b1568d2f17226a`.
Branch `fix/hsmm-predecessor-duration-20261016`. Main unchanged.

The user requests actual algorithm progress rather than more UI/calibration
scaffolding. This task corrects the optimizer of the **existing** model, not its
scientific observation assumptions. No new duration prior, decoder family,
threshold, event extraction/selection, K criterion, mapping or clock fit.
2D.1 remains FAIL/default-off. Physical states remain UNKNOWN.

Confirmed code mechanism to test: transition starts use
`max(min_d_current, t-max_d_current)`. This mistakenly imposes the current phase's
minimum duration on its predecessor's endpoint. A2→B8 has a valid predecessor at2
and own duration8, but is excluded since lo8>hi2. Correct positive predecessor
start is `max(1, t-max_d_current)`; dp already encodes predecessor feasibility.
This preserves the existing two-bin left-censored first segment and uncensored
last-segment assumptions. It does not claim those censoring assumptions are ideal.

A second numerical issue: duration penalty compares bin numbers with targets
in seconds. At dt≠1 the same physical duration is penalized incorrectly. Use
`duration_bins*dt` in that existing quadratic penalty; dt=1 formula unchanged.

Before changing code: run targeted counterexamples, retain failure log. Fixed
independent cases A2/B8, A2/B8/C3, A3/B7/C2 and exhaustive enumeration with fixed
seeds20261018/20261019, horizons16bins, dt .5/1/2, initial0/unknown. Compare the
actual optimum score to independently summed emissions+existing duration cost.
No test obtains its expected path from the decoder. Sparse observations here
test an optimizer, NOT real lamp identifiability or a new recovery acceptance gate.

After targeted tests: at most one three-record development comparison on cached
temporal events from `benchmarks/stage2c_20261014/predictions`. No raw trajectory
JSON/ZIP is reopened. First reproduce one unchanged control (record19) from its
saved event bundle; stop on unexplained schedule/selection discrepancy. Freeze
source hashes/config before any new annotation read. Use the existing selector,
infer_period and ordinary bounded K2..6 discovery, seed0, dt1, existing default
60s K budget, hard90s per worker. At most4 discovery runs (1 control+3 corrected),
total hard worker allowance360s. No tuning/retries after metrics. Existing caches
are development, not holdout. New predictions sealed before evaluator reads marks.

Compare old/new K, period, selected source, raw/baseline precision/recall±2s,
matched/truth/predicted counts, matched MAE/p95, nearest MAE, temporal coverage
and runtime. Do not attribute changed runtime solely to this correction because
the original end-to-end run included trajectory ingestion. Report decoding/fit
runtime of the cached run as its own scope. Do not conflate an arithmetic fix or
synthetic score agreement with real phase/lamp accuracy. No promise of improvement;
unimproved/regressed metrics remain visible; stop after this one comparison.
