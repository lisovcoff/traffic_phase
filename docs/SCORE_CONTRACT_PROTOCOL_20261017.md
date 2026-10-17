# Coherent fit score — frozen protocol, 2026-10-17

Base: e41c075d7c9cef7c6eb512cfadf7d29d435cafba.
Branch: fix/coherent-fit-score-20261017. Main stays unchanged.

Scope is external-review D2+D3 only, not a new decoder or observation model.
The existing Bernoulli occupancy model is retained without asserting calibrated
physical-signal likelihood. No real labels are inference inputs.

Before corrected development results, define the contract:

* `data_loglik` equals the Bernoulli sum for the returned labels AND probabilities;
  `pointwise_loglik` remains its compatibility alias.
* Private refinement `score` is the penalized objective for those SAME parameters.
  Correct it by decoder_input_score + new_data_loglik - decoder_input_data_loglik.
  Durations/transitions and first-segment censoring are unchanged. Choose the
  best refinement snapshot by this corrected objective; retain the old decoder
  input objective separately. No additional decode is performed for rescoring.
* Public `em_fit.score` becomes an explicitly labelled alias of `data_loglik`,
  for both seed and refined fits. `penalized_objective` is separate, null for
  unrefined seeds; no artificial duration prior is imposed on those seed paths.
* K candidate objective is always returned-model data likelihood, never the
  mixed old `score`. Approximate BIC is -2*data_loglik + K*S*log(max(2,N*S)).
  This changes the score BASIS of the existing approximate criterion explicitly.
  It is not exact marginal evidence, calibrated confidence or a lamp probability.
  Keep the existing complexity coefficient, per-cycle penalty, support gate,
  3->2 redundancy, initialization quality/coherence and ensemble preference.
  A legacy fit with only `pointwise_loglik` remains accepted; a score-only fit
  must be rejected rather than guessing its semantics.

Acceptance before real comparison: independent D2/D3 counterexamples pass;
same returned path/params has same K objective regardless of initializer;
corrected snapshot equals an independent objective sum at dt=.5/1/2 and K2/K3;
best-iterate selection uses corrected scores even when stale scores rank the
iterations differently. No redundant decode, no mutation of saved inputs.
Existing structural K4/budget, decoder oracle and query/UNKNOWN checks pass.
Remaining strict xfails stay visible; do not repair D4-D8 in this task.

Use only three immutable stage2c lossless event caches (not large trajectories),
exact event/selection/anchor equality checked by existing cached_bundle.
Baseline is the last D1 native prediction set, benchmarks/seed_flow_20261017.
Freeze file/config/package/protocol hashes first. One unchanged native control
on recording19 must reproduce its schedule/K/period before code edits. Stop on
unexplained mismatch. Control diagnostic floats permit atol1e-12, rtol0;
raw segments and K are exact. This is not evaluator boundary tolerance.

After tests, commit code/config BEFORE one corrected cached run of three files.
dt=1, seed=0, K2..6, 5 candidates, cooperative60s; hard worker90s, total control
plus corrected wall allowance360s. No new hyperparameter search or retries.
All output hashes sealed before original phase annotations are opened by a
single unchanged evaluator pass, tolerance +/-2s. Report raw/baseline separately:
K, period error, matched/truth/predicted counts, precision/recall, matched MAE/p95,
nearest MAE, coverage, runtime/candidate count and timeouts. All three are
development data. Benefit is measured, not required to justify proven defects;
report FAIL_NO_GAIN/regressions without post-result parameter changes.

2D.1 stays FAIL/default-off. Physical states UNKNOWN. No UI/mapping/offset/
event selection/period inference/evaluator changes. Keep historical artifacts.
