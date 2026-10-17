# D7 commands and logs

Canonical cwd D:/Code/PythonProjects/traffic_phase/audit_checkout.
PowerShell no profile; Python C:/Python314/python.exe. TEMP/TMP=.web_runtime/tmp
on D:. Base b84e08b1d141e07da8e524080176c64f205233cc; branch
fix/tie-invariant-redundancy-20261017. Main unchanged.

```
git switch -c fix/tie-invariant-redundancy-20261017
python -m pytest tests/test_v9_independent_review.py -k "redundancy_rank or redundancy_decision" --runxfail -q -p no:cacheprovider
python -m scripts.tied_rank_review freeze
python -m scripts.tied_rank_review control
# Replace ranking only, then:
python -m pytest tests/test_redundancy_tied_ranks.py tests/test_fit_score_contract.py tests/test_score_review_runner.py tests/test_v9_independent_review.py tests/test_seed_flow_control.py tests/test_hsmm_duration_recurrence.py tests/test_hsmm_cached_replay.py tests/test_local_history_2d1.py tests/test_local_history_support_2d1.py tests/test_phase_search_config_2c.py tests/test_phase_search_2c.py tests/test_state_contract_2b2.py tests/test_v9_query_contract_followup.py tests/test_vehicle_temporal_evidence.py tests/test_temporal_evidence_contract_diagnostics.py tests/test_product_result.py tests/test_offline_product_html.py tests/test_v9_source_scope.py tests/v9/test_v9_api.py tests/test_offline_benchmark.py -q -rx -p no:cacheprovider
python -m pytest tests/v9/test_v9_discovery.py tests/test_v9_merge_e2e_synthetic_benchmark.py -k "candidate_metrics or phase_selector or redundancy_detector" -q -p no:cacheprovider
git diff --check
git commit -m "fix(v9): make tied redundancy ranks invariant to movement order"
python -m scripts.tied_rank_review run
# All3 hashes sealed before annotations:
python -m scripts.tied_rank_review evaluate
python evidence/tied_ranks_20261017/verify.py
python evidence/tied_ranks_20261017/seal.py
```

Original invocations use absolute Python. Own console logs captured through
Tee-Object; only these logs and redirected verification.json normalized from
PowerShell UTF16 to UTF8/LF before sealing. No historical/input normalization.
before_tests.log: expected2 FAIL. regression_tests.log:235 PASS/4 strict XFAIL;
callsite_tests.log:5 disjoint PASS. Total240 unique PASS. No old color expectation
changed; Starlette/httpx warning retained. No dependencies installed.

The worker is the unchanged scripts.score_contract_review infer function; it
receives no annotations. The wrapper changes only output/baseline directory for
the already inspected evaluator orchestration. One control plus3 corrected
workers, no retries/search/tuning beyond unchanged bounded K2..6 discovery.
Code before corrected workers: a57ae53f7b9e1f336ee0293a1425ac79264ee2a1.
verify.py is read-only: source AST, protected paths, per-K fits/scores, anchors,
selection, output/input hashes, UNKNOWN/default and main. No fitting or scoring.
Prior review/score artifacts retained and referenced, not repackaged.
