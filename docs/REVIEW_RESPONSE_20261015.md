# Independent review: verified response and query contract fix

Base `c0e89461c0bc28f2d7fd9609b07a591a50195bbf`.
Branch `fix/query-observation-completeness-20261015`. Received review is preserved
verbatim in EXTERNAL_REVIEW_RECEIVED_20261015.md; its claims of80 tests/93024
likelihood checks are the reviewer's results, not a rerun performed here.

## Findings disposition

1. **Confirmed/fixed query completeness.** Before fix: truncated RELEASE6250/
   CROSSING8250 with query[0,8000) returned unsupported pattern; complete query
   [0,20000) was ready. Empty query[0,2000) with camera[0,8000) was ready and
   contributed log-likelihood−1.84. Saved before.json reproduces both claims.
   Now both truncated cases give QUERY_DOMAIN_INCOMPLETE and no likelihood.
   Full query still ready. No fitting/decoding needed for this counterexample.
2. **Confirmed finite-population limit, open.** Event250ms with supplied vehicle
   delay2s requires latent time−1.75s; wide query does not solve it. Targeted test
   preserves explicit unsupported-pattern result. Stationary initial phase age
   does not create latent vehicles before0. Real-window application requires a
   consistent latent prehistory/context model or an explicitly unpublished edge
   region; this patch does neither and does not claim real-window readiness.
3. **Confirmed scalability failure.** Cheap integer recursion independently
   reproduces review path counts34/36/38/60/64s, without enumerating/fitting paths.
   At64s K2=7048870,K3=10573305. Enumeration stays small-input reference.
   The unchanged4..48s duration support is a separate hold limit.
4. **Confirmed assumption limits, not arithmetic bugs.** Detection independence
   yields.75 any detection for pr=pc=.5, unlike.5 for all-or-none visibility.
   The rate×exposure confounding and conditional Poisson/delay assumptions remain;
   no nuisance parameters estimated from known development labels.
5. **Confirmed output-policy gap.** Saved core exact-count9/12 flat,8/12 soft
   independently counted. Conditional-on-truth-count intervals do not certify
   MAP/count. Published states remain UNKNOWN; old FAIL is retained.

## Implemented contract

New shared `observation_domain.require_complete_query` is used by BOTH finite
and rounded observation components, including direct callers. Bridge v2 translates
query range and event timestamps to the same explicitly supplied origin.
It rejects unavailable/malformed query range and events outside it.

Conservative policy: reject a query if it omits any possible reported mark under
the supplied finite-population model. No partial-window kernel approximation,
camera-window clipping or compensator reinterpretation was introduced. For each
nonzero detection channel, delay atoms and camera windows determine reachable
mark times. Finite clock uses exact clock points. Rounded clock includes every
clock centre whose rounding cell intersects reachable true detection times with
positive measure. A half-open query must include the rightmost centre itself.
This guards rounding near window edges, including centres outside the true-time
interval. Irrelevant camera tail beyond reachable delays need not be delivered.

This proves query-bound coverage **relative to a supplied event index/model**,
not upstream raw-source completeness, calibrated detection, camera exposure,
demand, or vehicle population. Upstream completeness remains an explicit model
assumption in diagnostic metadata. An index built from a selected cohort cannot
become an intersection-wide complete sample just by widening its query.

Some historical finite-horizon rounded inputs query exactly[0,h): they omit a
possible rounded mark at h. They now legitimately require a context query that
includes that clock centre. Historical artifacts are not rewritten/replayed.
Tests of historical source seals now read the frozen Git revision recorded in
each manifest, rather than demanding current corrected code equal old code.
Protocol/input/output hashes are still checked; seals were not regenerated.

108 target tests passed, plus16 historical artifact/adapter tests. Complete-input
joint likelihood is unchanged in finite/rounded closed-form counterexamples.
Initial new
test found nonfinite query metadata reached JSON hashing before validation;
validation was moved before hashing. Failure log retained. No full benchmark,
K search, real replay, scientific sequence suite, or parameter changes. Existing
bounded inference unit counterexamples were run as part of targeted tests.

## Corrected next step

Keep full enumeration as oracle. Build scalable fixed-K/order inference only
with an explicit factorization: compensator per cell, a vehicle factor closed
at its last nonzero q cell, and enough phase history for all unfinished factors.
Local kernel case can use semi-Markov DP; general joint log-sum factor cannot
be replaced by a scalar ordinary HSMM score without proof. Wide-kernel beam,
if needed, must report truncation and uncertified mass, not exact posterior.

In parallel, define latent prehistory/context and input-completeness contract for
the real pilot. Existing video/H1/operator mapping is development material;
independent calibration/validation, synchronization uncertainty and observable
signal reference remain needed. The review's20cycles/50transitions, quality,
UNKNOWN/runtime thresholds are proposals to freeze before new validation, not
achieved metrics or automatically accepted requirements. No fresh search for
previously missing media or another calibration of the same8 cars was performed.

2D.1 FAIL/default-off;2C/protective state/query contract accepted; main/core,
production default, old K/period/predictions/evaluator unchanged. No lamp accuracy
claimed. Artifacts in evidence/query_observation_completeness_20261015/.
