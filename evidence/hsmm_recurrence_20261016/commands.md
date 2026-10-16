# Commands

Run from canonical audit_checkout, Python C:\Python314\python.exe.
TEMP/TMP `.web_runtime\tmp` on D, local process only.

```powershell
python -m pytest tests/test_hsmm_duration_recurrence.py -q -p no:cacheprovider
# before_tests.log:12 failed,5 passed (before correction).
python -m scripts.hsmm_recurrence_check freeze
python -m scripts.hsmm_recurrence_check control
# Exact control before changing decoder; stopped if mismatch.
python -m pytest tests/test_hsmm_duration_recurrence.py tests/test_local_history_2d1.py tests/test_local_history_support_2d1.py tests/test_phase_search_config_2c.py tests/test_state_contract_2b2.py tests/test_v9_query_contract_followup.py -q -p no:cacheprovider
# target_tests.log:93 passed
python -m pytest tests/test_phase_search_2c.py tests/test_vehicle_temporal_evidence.py tests/test_temporal_evidence_contract_diagnostics.py tests/test_product_result.py tests/test_offline_product_html.py tests/test_v9_source_scope.py tests/v9/test_v9_api.py tests/test_offline_benchmark.py -q -p no:cacheprovider
# regression_tests.log:102 passed
python -m pytest tests/test_hsmm_cached_replay.py tests/test_hsmm_duration_recurrence.py -q -p no:cacheprovider
# cache_tests.log:21 passed (17 repeated from target suite;199 unique total).
git commit -m "Fix HSMM predecessor feasibility and duration penalty time units"
# 98446c4d94a4a38a9a291d7ff53aab6ec569b7cc before corrected run.
python -m scripts.hsmm_recurrence_check run
# Exactly3 corrected cached discoveries; no raw JSON or new starts.
python -m scripts.hsmm_recurrence_check evaluate
# Exactlyone evaluator pass after predictions_sealed.json.
python -m evidence.hsmm_recurrence_20261016.verify_results
# Read-only, no evaluation rerun or inference.
```

No UI/browser work, new offset, thresholds, demand assumption, delay model or
geometry. Code correction changes optimizer results on some candidates, but all
three selected schedules and final metrics are unchanged. Historical outputs
not overwritten. New predictions omit duplicated temporal_events payload and
reference the original immutable event cache by path+SHA; all selected indices
and provenance in that referenced cache are retained. No calibration/lamps claim.
