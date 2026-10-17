# Commands / provenance

Canonical cwd D:/Code/PythonProjects/traffic_phase/audit_checkout, PowerShell
without profile, Python C:/Python314/python.exe. TEMP/TMP=.web_runtime/tmp on D:.
Base c414c5ef486b145cb7605017fbeabee3e68237b0; branch
fix/remaining-review-defects-20261017. Main unchanged.

```
git switch -c fix/remaining-review-defects-20261017
python -m pytest tests/test_v9_independent_review.py -k "ensemble or distinct_shared or censored_start" --runxfail -q -p no:cacheprovider
python -m scripts.review_closure freeze
python -m scripts.review_closure control
# Implement four declared fixes, no annotations.
python -m pytest tests/test_remaining_review_defects.py tests/test_v9_independent_review.py tests/test_phase_search_2c.py -q -p no:cacheprovider
python -m pytest tests/test_remaining_review_defects.py tests/test_redundancy_tied_ranks.py tests/test_fit_score_contract.py tests/test_score_review_runner.py tests/test_v9_independent_review.py tests/test_seed_flow_control.py tests/test_hsmm_duration_recurrence.py tests/test_hsmm_cached_replay.py tests/test_local_history_2d1.py tests/test_local_history_support_2d1.py tests/test_phase_search_config_2c.py tests/test_phase_search_2c.py tests/test_state_contract_2b2.py tests/test_v9_query_contract_followup.py tests/test_vehicle_temporal_evidence.py tests/test_temporal_evidence_contract_diagnostics.py tests/test_product_result.py tests/test_offline_product_html.py tests/test_v9_source_scope.py tests/v9/test_v9_api.py tests/test_offline_benchmark.py -q -p no:cacheprovider
python -m pytest tests/v9/test_v9_discovery.py tests/test_v9_merge_e2e_synthetic_benchmark.py -k "not e2e_synthetic_benchmark" -q -p no:cacheprovider
python -m pytest tests/test_v9_merge_e2e_synthetic_benchmark.py -k redundancy_detector -q -p no:cacheprovider
# Two stale assertions repaired before development evaluation; source isolation unchanged.
python -m pytest tests/v9/test_v9_discovery.py -k "direction_agnostic_stream_names or detects_local_regime_on_long_input" -q -p no:cacheprovider
python -m pytest tests/test_remaining_review_defects.py tests/test_v9_independent_review.py -q -p no:cacheprovider
# Final regression selection: same main list above, now269 PASS.
git diff --check
git commit -m "fix(v9): resolve shared support, ensemble identity and censored baseline defects"
python -m scripts.review_closure run
# All3 hashes sealed before annotations:
python -m scripts.review_closure evaluate
python evidence/review_closure_20261017/verify.py
python evidence/review_closure_20261017/seal.py
```

Actual Python invocations use the absolute path. Own stdout/stderr logs captured
with Tee-Object, only own logs/redirected JSON normalized UTF16→UTF8/LF before
sealing. No original cache/external/historical byte normalization. CPU threading
OMP/OPENBLAS/MKL=1 in final targeted/regression and corrected discovery tests;
all real workers already enforce these=1. No dependency installs. No heavy
parameter-grid tests in merge benchmark file; -k excludes its two search tests.

before_tests.log4 expected FAIL. discovery_tests.log18 PASS/2 stale FAIL retained;
corrected_discovery_tests.log2 PASS. redundancy_tests.log2 PASS. Final main
final_regression_tests.log269 PASS (no XFAIL), with previous Starlette warning.
Unique successful cases291=269+20+2; repeat runs are not added. Final targeted
43 PASS repeats included cases. test_maintenance.json explains test changes;
no old color expectation or source-scope guard relaxed. One attempted read of
the discovery log before its creation returned file-not-found; no check skipped.

Frozen code9e987c804c1880b991f5298da27f71224778d8c8; original worker/evaluator
unchanged, three output hashes sealed before evaluation. Input labels unavailable
to inference (existing cache/worker guards). One control+3 corrected workers,
no additional run/parameter search/tuning. fit_parity.json is read-only comparison
of saved output hashes/centers, no fitting or labels. verify.py verifies AST,
protected paths/input-output hashes/anchors/selection/period/UNKNOWN/main,
not evaluation or model fitting. Existing artifacts referenced, not overwritten.
