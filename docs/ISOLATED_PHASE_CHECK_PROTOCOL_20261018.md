# Isolated phase checks after selector result, 18.10.2026

Explicit user authorization continues. Candidate1 per-track selector returned
4/17,1/8,2/9 strict matches versus15/17,1/8,3/9, so it is NOT promoted.
Negative predictions remain preserved. The following two hypotheses are frozen
before either is run or scored. Both use the original movement selector and
exact original lossless event caches, with old-selection equality checked.

Candidate2 `equal_durations`: give K2 the same0.25..1.75 duration multipliers
as K3, leaving K3..6, seeds, likelihood, evidence and all scoring unchanged.
Hypothesis: unequal feasible duration search constrains K2 unfairly.

Candidate3 `likelihood_only`: `_fit_quality` evidence_weight becomes0 instead
of0.05 for choosing initial/refined paths within each K. Data likelihood and
BIC across K remain unchanged. Hypothesis: the signed-derivative boundary
coherence heuristic can favour a periodic seed over a better local fit.
No forced HSMM, known K, physical-mapper K override, fixed time shift, marks,
0.15 silent-bin multiplier or combination of candidates is introduced.

One run/three cached sources per candidate,dt1,seed0,K2..6,90s/file,270s/candidate,
540s total. Freeze source hashes and script hash before runs. Seal all three
predictions before evaluation. Unchanged +/-2s and separate[mark-3s,mark]
evaluation, raw and resolved histories. No parameter search/retries after scores.
Original baseline is the comparison, not candidate1. Promotion requires no
per-file matched-boundary reduction or false-extra increase and no K-count
regression against baseline. Otherwise preserve as experimental/default-off.
