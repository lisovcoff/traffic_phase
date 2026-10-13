# V9 query contract follow-up — 2026-10-14

Base: `8bb7ca1a9d8137001028f2c6b6e8e6af98d42201`. Separate fix branch;
main, fitting, detector/selection, thresholds, mapping objective and saved
predictions are unchanged. No trajectory reads or recording-6 diagnostics.

Confirmed defects: canonical `app/core/v9/signal_renderer.py` translated event
activity into lamp colors, manufactured fixed-duration transitions, and its
`_find_segment` fell back to first/last segments outside coverage or in gaps.
Shared `logical_phase_at` chose the first match in contradictory overlap.

## Shared history validation

`prepare_logical_query` produces an immutable `LogicalPhaseQuery` snapshot.
Construction validates the whole history once in O(n); `.at()` uses binary search
in O(log n). No automatic cache or mutation tracking is introduced. One-off
`logical_phase_at(result,t)` remains convenient; bulk callers must prepare once
and reuse `logical_phase_at(query,t)` or `query.at(t)`.

Any overlap (even identical phase indices), unsorted input, invalid boundaries,
end<=start, negative starts, malformed rows or invalid indices invalidates the
whole snapshot. It is never repaired or silently sorted. Queries return
UNKNOWN/`INVALID_PHASE_HISTORY` with specific `history_validation_error` in
observation_support, even if the malformed row lies outside the queried time.
Valid gaps, negative/nonfinite query timestamps and out-of-range times return
UNKNOWN/`NO_TEMPORAL_COVERAGE`. Intervals are half-open. Invalid configured
period also produces INVALID_PHASE_HISTORY. Invalid mode is a caller error.

## Canonical V9 and immediate core caller

`build_signal_model(result)` delegates to `prepare_logical_query` and returns
JSON-compatible `SignalQueryModel` with the immutable snapshot as an attribute.
`signal_state_at(model,t)` reuses it; ordinary result inputs are prepared for
one-off queries. Mutable display metadata cannot override snapshot mode/history.
Serialization includes metadata but not the internal query object; rebuild from
the original result when restoring a model. Missing phase names cannot establish
phase-index meaning; unnamed streams remain present with unavailable scores.

Reconstructed snapshots expose separately labelled activity scores, anonymous
logical phases and physical UNKNOWN through shared StateEstimate/physical_estimate.
Legacy probability-as-lamp fields are removed; use `activity.activity_score`.
Fixed transitions are not generated in reconstructed mode. Mode must explicitly
be configured/simulated to use the previous threshold as a labelled plan proxy.
Only these explicit modes assume cyclic baseline repetition. Their colors do not
claim independently established hardware mapping or lamp probability.

V10's immediate core query also uses the shared validated history; bulk callers
can pass `query_model`. Invalid/gap history propagates the same abstention to
physical results in every mode. Repository core search found no additional
V9-renderer callers inside app/core. API and visualizer import the canonical
function but their source files were deliberately not modified. Their unqualified
calls now receive conservative core output; UI compatibility/migration is outside
this task.

## Concrete old expectation changes

The old V9 renderer test labelled activity=.90 GREEN and .01 RED. GREEN without
demand can yield zero occupancy; permissive movement or unblock under RED can
yield high occupancy. Both are physical UNKNOWN in reconstructed mode. Existing
color/3s-yellow/2s-red-yellow tests now select configured mode explicitly. The
offline evaluator's synthetic no-demand test now expects UNKNOWN and preserves
its zero activity score; evaluator implementation/truth files are unchanged.
The overlap example [[0,10,0],[5,15,1]] at t=7 now returns INVALID_PHASE_HISTORY,
not A. New tests also cover overlaps with identical indices, malformed rows,
half-open boundaries, gaps, out-of-range and nonfinite timestamps, immutable
snapshot reuse, explicit transitions, arbitrary movement names and V10 linkage.

## Verification and limits

Targeted tests and the frozen-prediction query verifier run without fitting.
The verifier checks all segment starts and midpoints plus outside-history times
on each of the same three predictions. Schedule, selection and period dictionaries
and raw/baseline segment hashes are preserved exactly. Logical coverage and
physical UNKNOWN are reported separately; neither measures lamp accuracy.
Logs, code diff, source/prediction hashes and the updated ZIP are in
`evidence/stage2b2_v9_query_followup/`.

PROJECT_STATUS records the supplied meaning of top-level millis: the time when
the vehicle left the intersection, from the provided description of Инфо.docx.
Clock synchronization, endpoint accuracy and stop-line relationship remain
unverified. No document search or spatial inference was needed.
