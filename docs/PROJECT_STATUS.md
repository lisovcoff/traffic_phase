# Project status — 2D.1, 2026-10-14

Stages 1 and 2A are accepted as audit/planning and a reproducible offline baseline.
Stage 2B.1 is accepted as an engineering improvement in temporal evidence,
provenance and per-stream selection. Its event timing and lamp semantics have
not been independently validated. Accepted A–D and event-level recording-6
diagnostics are preserved; they were not repeated for 2B.2.

2B.2 adds conservative result semantics and abstention; it does not improve or
retrain phase discovery. Physical UNKNOWN is reported separately from model
history coverage. External vehicle-event and lamp validation remain open.
Known regressions (including recording 6 K 2→3 and degraded boundary results
after changed evidence ingestion) remain in the unchanged
`benchmarks/stage2b1_20261013/comparison.json`. No parameters were selected to
repair these results.

Production base: `afcfaa2b38e106201d7e819570425acfc4c5487f`.
Only uncertainty/structured-abstention code and its tests were taken from
`1207344bdcbc46edbf19bace65382ee0252d1f4d`; diagnostic runners/artifacts were
not used as the production base. Main remains unchanged.

Top-level `millis`: according to the supplied description from `Инфо.docx`,
this is the time when the vehicle left the intersection. This is provided field
semantics, not a measured stop-line crossing. Camera/controller synchronization,
endpoint timing accuracy and the relation to the stop line remain unverified.
The historical `millis - move_duration_millis` calculation remains a proxy.

The canonical V9 core renderer now delegates to the shared state contract.
Prepared immutable history supports repeated queries without repeated validation.
Malformed histories give UNKNOWN/INVALID_PHASE_HISTORY; valid gaps/out-of-range
queries give UNKNOWN/NO_TEMPORAL_COVERAGE. Explicit configured/simulated modes
remain distinct from reconstructed physical states. Follow-up base:
`8bb7ca1a9d8137001028f2c6b6e8e6af98d42201`.

2B.2 including canonical V9 query follow-up is accepted. 2C completed:
universal candidate admission and bounded, transparent phase-count comparison.
Base: `36b6752a4794e482570944b22656d6cc58f0db31`. Prior baseline/regressions remain
preserved; any new development metrics do not close independent event/lamp
validation.

2D.1 is the current limited stage: a single fixed-model local duration decoding,
separate from recurring-plan discovery. Raw/baseline fields are preserved.
No-demand/missing local evidence remains UNKNOWN; camera coverage and lamp
switch timing are not inferred. External validation and known development
regressions remain open. Base `b248b4c7bac27def4a131ba61301f2678cd0b05a`.
No 2D.2, skip/reorder, multiple-regime extension or online work is authorized.

2D.1 is **FAIL / NOT ACCEPTED**. Its supported real history has0/34 matched
boundaries; its diagnostic candidate has7/34, versus accepted raw19/34. Removing
the UNKNOWN mask does not fix the candidate failure. Historical results remain
unchanged. Local reconstruction is now explicitly opt-in/default-off; accepted
2C discovery/query behavior is restored. Experimental queries require explicit
source selection and abstain in gaps/unavailable results without raw fallback.

A single predeclared sparse-event review also failed its per-case recovery gate
(7/16 core cases fail) and publishing/identifiability gate. No real replay was
allowed or performed. The conditional-mark candidate is diagnostic only; no
replacement history is approved. A justified observation/demand/exposure model
and interval-uncertainty/support method are required before further publication.
See SPARSE_OBSERVATION_2D1_REVIEW.md. External event/lamp validation remains open;
no2D.2/online work is started. Await further instruction.

An isolated event-time feasible-set prototype (2026-10-14) was evaluated once
on 18 new synthetic cases with two preregistered priors, outside production.
All 12 correctly specified truth paths are feasible, but sets remain broad and
transition counts ambiguous. The unchanged per-case point-recovery criterion
fails for both priors (4/10 and 1/10 core cases). Historical 2D.1 remains FAIL;
default/production, old gates, results and evaluator are unchanged. No real
replay, fitting, K search or 2D.2 work occurred. See EVENT_TIME_PROTOTYPE_2D1.md.
