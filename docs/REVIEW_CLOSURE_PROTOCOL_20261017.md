# Remaining confirmed review defects — frozen scope, 2026-10-17

Base c414c5ef486b145cb7605017fbeabee3e68237b0.
Branch fix/remaining-review-defects-20261017. Main unchanged.
User authorizes fixing all remaining confirmed review defects together. Existing
D1-D3/D7 and recurrence fixes remain. Scope D4/D5/D6/D8; not an unvalidated
replacement architecture, lamp estimator or acceptance of failed 2D.1.

Predeclared rules, independent of development phase labels:

* D4: retain seed group stream membership. Match release/entry groups by maximum
  shared-membership count, requiring unique one-to-one assignment, positive
  overlap in every matched group and compatible cyclic order. Use existing
  scipy assignment solver with forbidden-edge alternative checks (bounded O(K^4),
  no factorial search). Unknown/tied assignment or antipodal midpoints abstain
  from creating ensemble. Compute shortest-arc circular midpoint, then sort
  paired groups together. Preserve the existing minimum onset spacing guard.
* D5: all seed sources compete by the existing model_quality, including pure
  release/entry. Remove privileged ensemble exclusion and its .002 override;
  exact ties use first retained candidate in declared release/entry/ensemble/
  equal/split order. Keep the existing within-seed refinement .0001 rule.
* D6: retain activity .08/selectivity1.15 thresholds, but compare joint phase
  signatures pairwise instead of demanding a globally exclusive stream. Active
  phases must differ from EVERY other phase on at least one active coordinate
  by the existing ratio, in either direction. No arbitrarily small float-row
  inequality is sufficient. Keep legacy exclusive counts separately; report
  joint witnesses and exact model-support semantics. This is heuristic fitted
  signature support, NOT physical identification or a calibrated confidence.
  Pairwise absence contrast is conditional on the retained occupancy model;
  it is not a real red observation or a known-demand assertion.
* D8: onset evidence requires an observed contiguous change of phase. First
  segment, gaps and same-phase continuation do not supply a boundary. With any
  phase lacking an onset, invalid history or undefined circular mean, return
  empty baseline plus structured unavailable diagnostics, not raw substitution
  or zero/fabricated onset. Preserve raw history. Default two-item helper API
  stays; canonical model requests explicit diagnostics/known K. Configured queries
  abstain when baseline absent. No fixed lamp transitions are reconstructed.

Tests before corrected comparison: four independent review failures reproduced;
new independent membership/unique/tied/missing/antipodal/order and time-origin
tests, common quality selection/ties, AB/AC/BC and duplicate/near-equal/inactive
signature cases, renamed columns, censored first/last/gap/no-onset histories,
actual query UNKNOWN and old decoder/search/contract/consumer regressions.
Keep extraction/selection, period inference, HSMM, K range/budget/complexity,
offset calibration, physical mapping, uncertainty and evaluator unchanged.

Freeze only3 existing stage2c lossless event caches and last tied_ranks native
baseline. One unchanged recording19 control must reproduce exact schedule/K/
period before production edits. Then tests and code/config commit before ONE
corrected cached discovery per input: dt1,seed0,K2..6/max5/cooperative60s,
hard90s/worker,total360s control+3. No raw archives or parameter search. All
prediction hashes before one unchanged evaluator pass, +/-2s. No tuning/retries
after results. Report each raw/baseline M/T/P, precision/recall, matched MAE/p95,
nearest MAE, coverage, period error, K, runtime, candidates and timeouts.
Report regressions/unsupported results. This combined run cannot isolate an
individual fix's causal contribution; use structural tests for those mechanisms.

Development benefit is empirical, not required to prove code defects. Historical
artifacts/gates stay. 2D.1 FAIL/default-off, UNKNOWN and independent validation
limitations remain. No perfect-algorithm or lamp-accuracy claim.
