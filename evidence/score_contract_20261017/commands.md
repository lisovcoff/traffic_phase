# Commands and provenance

Canonical cwd: D:/Code/PythonProjects/traffic_phase/audit_checkout.
PowerShell without profile. Python C:/Python314/python.exe. TEMP/TMP point to
`.web_runtime/tmp` on D:; no dependencies installed or user data deleted.
Base e41c075d7c9cef7c6eb512cfadf7d29d435cafba. Branch
fix/coherent-fit-score-20261017. Code before corrected comparison
787c9776e47675ab9dede456330b65850f0ef799. Main unchanged.

Order (no corrected run/evaluation repeats):

```
git switch -c fix/coherent-fit-score-20261017
python -m pytest tests/test_v9_independent_review.py -k "refinement_score or same_path_and_templates" --runxfail -q -p no:cacheprovider
python -m scripts.score_contract_review freeze
python -m scripts.score_contract_review control
# Implement D2+D3 only. Control precedes production edits.
python -m pytest tests/test_fit_score_contract.py tests/test_v9_independent_review.py tests/test_phase_search_2c.py -q -rx -p no:cacheprovider
python -m pytest tests/test_fit_score_contract.py tests/test_score_review_runner.py tests/test_v9_independent_review.py tests/test_seed_flow_control.py tests/test_hsmm_duration_recurrence.py tests/test_hsmm_cached_replay.py tests/test_local_history_2d1.py tests/test_local_history_support_2d1.py tests/test_phase_search_config_2c.py tests/test_phase_search_2c.py tests/test_state_contract_2b2.py tests/test_v9_query_contract_followup.py tests/test_vehicle_temporal_evidence.py tests/test_temporal_evidence_contract_diagnostics.py tests/test_product_result.py tests/test_offline_product_html.py tests/test_v9_source_scope.py tests/v9/test_v9_api.py tests/test_offline_benchmark.py -q -rx -p no:cacheprovider
python -m pytest tests/v9/test_v9_discovery.py -k "candidate_metrics or phase_selector" -q -p no:cacheprovider
git diff --check
git commit -m "fix(v9): align fitted parameter snapshots and phase selection likelihood"
python -m scripts.score_contract_review run
# All3 predictions_sealed.json hashes exist before the next command.
python -m scripts.score_contract_review evaluate
python evidence/score_contract_20261017/verify.py
python evidence/score_contract_20261017/seal.py
```

Original commands use the absolute Python path; own console output captured
with Tee-Object. Before sealing, only own logs/redirected JSON are normalized
from PowerShell UTF16 to UTF8/LF. Raw input/cache/external/historical artifacts
are never normalized. `before_tests.log`: expected2 FAIL. `targeted_tests.log`:
26 PASS/6 XFAIL. `regression_tests.log`:222 PASS/6 XFAIL; `callsite_tests.log`:3 PASS.
The latter two selections are disjoint,225 unique PASS; targeted repeats not
added. Six strict xfails remain for5 known independent defects, not a clean
all-quality gate. Existing Starlette/httpx deprecation warning retained.

`verify.py` is read-only, no fitting/labels/evaluation; output in verification.json.
`seal.py` packages code diff/logs/frozen predictions/comparison, no inference.
Received external reviews stay at evidence/review_intake_20261017 with their
original hashes; no second copy. Input predictions are referenced by SHA/file,
not duplicated large temporal-event arrays. No raw JSON/archive/video reads.
