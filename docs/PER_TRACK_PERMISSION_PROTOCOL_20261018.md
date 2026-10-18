# Per-track permission candidate, 18.10.2026

Explicit user authorization: «делай бро!» after GEMINI_REVIEW_ASSESSMENT.
Baseline9f26c17. Main and original data/results remain intact. This is a
development comparison on familiar files, not a new holdout.

Candidate1 changes only event selection: prefer a non-LOW RELEASE for each
(source,track_fingerprint,movement); otherwise use an eligible CROSSING_PROXY.
Keep one chosen observation per vehicle, deterministic earliest timestamp with
stable tie-break. No ENTRY substitution. Missing fingerprint abstains rather
than merging unknown cars. Preserve quality exclusions and temporal uncertainty.
Do not double count release plus crossing of the same vehicle. Identical tracks
in different sources remain separate. No K, duration, empty-bin, topology,
time-anchor or scoring change. Existing default selector remains intact until
comparison, worker opts in locally.

Three frozen baseline temporal-event caches from manual_marks_20261018_baseline,
verify old lossless selection before the opt-in, then explicitly repack the same
events. Demand streams, anchors, original events and entry count must stay exact.
dt1,seed0,defaultK2..6,one worker per file,90s/file,270s total. Predictions and
hashes sealed for all files before scoring. No retries/parameter search after
results. Old +/-2s absolute one-to-one scorer unchanged; separate reaction
interval[mark-3s,mark], complete denominators, misses/extras, raw and resolved
histories, known-site conditional mapping separate. All negative results retained.

Promotion requires no reduction in matched boundaries on any file or increase
in false extra boundaries, plus no raw K-count regression; otherwise keep the
candidate experimental/default-off. Structural counterexample tests alone do
not justify promoting a candidate with worse real timing. Later isolated
duration/history experiments require their own hypothesis and frozen plan.
