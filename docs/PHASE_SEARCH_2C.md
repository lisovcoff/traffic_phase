# Bounded universal phase-count search — 2026-10-14

Base: `36b6752a4794e482570944b22656d6cc58f0db31`. This stage changes candidate
admission/config/diagnostics, not HSMM, period estimation, timing thresholds,
event extraction/selection, semantic mapping, offsets or evaluation tolerance.

The old selector capped K at 3 whenever stream names contained four straight
canonical movements. It also capped K by occupancy column count + 1. Both caps
are removed: names do not establish geometry, and shared movements may occur
in multiple phases. No replacement geometry prior or tuned penalty is added.
The existing approximate BIC plus 5-per-extra-phase-per-cycle complexity
criterion and signature-support eligibility rule are unchanged.

`PhaseSearchConfig` defaults to K=2..6, at most five candidate calls and 60s
cooperative wall time per search. Public discover_records/discover_path accept
phase_search_config; it is propagated to final and existing hourly-local searches.
For K5..8 explicitly pass PhaseSearchConfig(kmin=5,kmax=8,max_candidates=4,...).
The range is never capped by names or column count. Defaults retain the former
requested range, not its hidden admissibility caps.

Time is checked between unchanged em_fit calls (two iterations). An in-flight fit
is not preempted; wall time may overrun and is reported. Thus the candidate-call
budget bounds work units, not a hard latency guarantee. The unchanged benchmark
worker has a hard 90s file timeout. Search timeout/fit failures/skipped candidates
are partial search, never proof of optimality. For long recordings the budget is
per local/final search, not a recording-wide aggregate; existing local-window
iteration is unchanged and ledgers are retained in regime diagnostics. A hard
per-candidate worker timeout/recording-wide orchestration is outside this change.

`PhaseCountSearch` preserves three-item tuple unpacking and exposes diagnostics:
requested range/budget, every evaluated/failed/timeout/skipped K, elapsed time,
overrun, alternatives, raw scores, signature support and assigned event counts.
Selected K is best eligible evaluated candidate. Incomplete search, exact score
ties and unsupported/no-event phases are explicit; no empirical ambiguity-margin
threshold is introduced. Score margin is an uncalibrated criterion difference,
not confidence. Even complete model-signature support is not external signal
validation. Alternatives remain available regardless of the gap.

The previous >1 unsupported-extra-phase eligibility rule is retained. Infinite
internal exclusion scores are serialized as null with eligibility_reason and the
finite pre-exclusion criterion_score; strict JSON remains valid. No-demand evidence
does not fit or fabricate K. A budget with no evaluable candidate exposes structured
PHASE_SEARCH_UNAVAILABLE, UNKNOWN and no schedule/K, with the candidate ledger.

The existing 3→2 detector is unchanged. The predeclared independent case has
three supported separate subphases plus a shared movement in every phase; it does
not collapse. Therefore no confirmed defect justified editing redundancy rules.
Any existing override remains visible alongside the raw search-selected K and
effective final selected candidate. This does not repair recording 6 by a special
rule. Template signature support and observed-event support are diagnostic
identifiability proxies, not physical phase/hardware truth.

Before benchmark, predeclared_manifest.json fixes default/recovery configs and
synthetic definitions. K4 recovery uses six 80s cycles with four separate dense
20s protected intervals; it compares only K2..4 and repeats under bijective names.
K5..8 range/budget/timeout tests replace fitting with a small stub. Shared-subphase
redundancy is checked with handcrafted observations/templates, not training.
Synthetic success is structural recovery, not real reconstruction accuracy.

One standard three-file development benchmark is run after code/config commit,
using the unchanged evaluator, seed, dt, offsets and ±2s tolerance. There is no
parameter search, retrial or post-result tuning. comparison.json contains complete
before/after metrics, counts, coverage, runtime and candidate diagnostics; timeout
means unavailable metrics. Frozen baseline artifacts remain unchanged. Event/lamp
validation remains external and open.
