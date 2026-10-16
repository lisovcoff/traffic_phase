# Native commands; external logs remain attributed to Astra

Canonical workspace audit_checkout; Python C:\Python314\python.exe.
Process TEMP/TMP `.web_runtime\tmp` on D; no new dependencies installed.

```powershell
git switch -c fix/review-seed-flow-20261017
git apply --check evidence/review_intake_20261017/seed_flow.patch
python -m pytest tests/test_v9_independent_review.py --runxfail -q --tb=short -p no:cacheprovider
# Local before:12 FAIL,1 PASS; all8 mechanisms reproduce.
python -m scripts.seed_flow_review freeze
python -m scripts.seed_flow_review control
# Native unchanged b767 control exact,1 discovery, original annotations not read.
git apply evidence/review_intake_20261017/seed_flow.patch
python -m pytest tests/test_v9_independent_review.py tests/test_seed_flow_control.py tests/test_hsmm_duration_recurrence.py tests/test_hsmm_cached_replay.py tests/test_local_history_2d1.py tests/test_local_history_support_2d1.py tests/test_phase_search_config_2c.py tests/test_phase_search_2c.py tests/test_state_contract_2b2.py tests/test_v9_query_contract_followup.py tests/test_vehicle_temporal_evidence.py tests/test_temporal_evidence_contract_diagnostics.py tests/test_product_result.py tests/test_offline_product_html.py tests/test_v9_source_scope.py tests/v9/test_v9_api.py tests/test_offline_benchmark.py -q -rx -p no:cacheprovider
# local_after_tests.log:208 PASS,8 strict XFAIL (seven open defects).
git commit -m "Validate external reviews and make K3 split seeds reachable"
# 35fc8fe899193bea4440b3e910e4f49782563836 before corrected run.
python -m scripts.seed_flow_review run
# Exactly3 corrected discoveries; all hashes sealed before scoring.
python -m scripts.seed_flow_review evaluate
# One full unchanged evaluator pass; original marks are available locally.
python -m evidence.review_intake_20261017.verify_native
# Read-only: AST-only relocation, source hashes, full metric/schedule invariance.
```

The original Astra runner is preserved but not executed. Its failed cross-platform
control is not overwritten or waived. Gemini original, original ZIP/patch/reports
and external manifest hashes retained. Only our native logs are normalized to
UTF8 during packaging; the supplied original byte streams are unchanged.
