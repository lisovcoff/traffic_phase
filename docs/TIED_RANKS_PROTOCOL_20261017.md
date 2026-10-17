# D7: tied ranks in redundancy — preregistered scope, 2026-10-17

Base b84e08b1d141e07da8e524080176c64f205233cc.
Branch fix/tie-invariant-redundancy-20261017. Main unchanged.

The existing _rank_correlation assigns different ranks to equal values using
argsort(argsort), so a mere permutation of movement columns can change the
3->2 redundancy decision. Independent review supplies two reproducing tests.
Replace this ranking ONLY with average ranks for exact ties (standard Spearman
definition), using existing scipy. Keep the existing small/constant-vector
guards and all thresholds, weights, pair sorting and redundancy logic. No fuzzy
tie threshold, new observation model, D6 support fix or score criterion change.

Before development results: both original counterexamples must pass; compare
the correlation against an independent counting-based rank oracle on fixed
untied/tied/constant examples, check all6 permutations of the three-element
counterexample and all120 column permutations of the supplied five-column full
redundancy witness (no fitting). Preserve no-tie behavior, constant guard,
no-input-mutation and existing handcrafted merge/distinct-phase tests. Structural
invariance does not validate the heuristic merge policy or infer physical lamps.

Use existing stage2c lossless event caches and last score_contract_20261017
predictions as baseline. Freeze cache/selection/baseline/config/package/protocol
hashes before any corrected development run. One unchanged recording19 control
before production edits: schedule/K/period exact, diagnostic float atol1e-12
rtol0 permitted only for portability. Stop on unexplained mismatch.

After targeted tests, commit code/config before one cached run of3 files:
dt1,seed0,default K2..6/max5/cooperative60s,hard worker90s,total maximum360s
including control. Reuse inspected score-review inference worker and unchanged
evaluator; workers have no annotations and local experimental reconstruction is
off. Seal all predictions before one evaluator pass at +/-2s. No reruns/tuning.

Report selected K, period, raw/baseline M/T/P, precision/recall, matched MAE/p95,
nearest MAE, temporal coverage, runtime, candidates and timeouts. Retain rank
features/merge decisions before/after and all regressions. A gain is not required
to establish this code defect; no gain must be stated. These recordings are
development, not holdout. 2D.1 FAIL/default-off and physical UNKNOWN remain.
