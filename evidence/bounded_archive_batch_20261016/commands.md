# Commands and provenance

Workspace: `D:\Code\PythonProjects\traffic_phase\audit_checkout`.
Python: `C:\Python314\python.exe`; Node: `C:\nvm4w\nodejs\node.exe`.
TEMP/TMP: task-local `.web_runtime\tmp` on D, no global environment changes.

```powershell
git switch -c feat/bounded-archive-batch-20261016
python -m pytest tests/test_archive_batch.py tests/test_v9_source_scope.py tests/test_strict_trajectory_json.py tests/test_web_archive_contract.py tests/test_vehicle_temporal_evidence.py tests/test_temporal_evidence_contract_diagnostics.py tests/test_product_result.py tests/v9/test_v9_spatial_visualizer.py tests/v9/test_v9_offline_visualizer.py tests/v9/test_v9_api.py tests/test_archive_streaming.py -q -p no:cacheprovider
# tests.log: 249 passed
python -m pytest tests/test_offline_product_html.py tests/test_state_contract_2b2.py tests/test_v9_query_contract_followup.py tests/v9/test_v9_signal_renderer.py tests/test_phase_search_config_2c.py -q -p no:cacheprovider
# contract_tests.log: 68 passed
START_WEB.cmd --check
python -m uvicorn app.main:app --host 127.0.0.1 --port 8021
# Own isolated headless Edge, own .web_runtime profile, CDP 9241; no user's profile.
node scripts/qa_archive_batch.mjs
# Exactly one ordinary batch, three synthetic sessions; browser_results.json.
# Stop only recorded/verified own server process.
python -m scripts.serve_saved_batch_qa
node scripts/qa_archive_batch.mjs --saved
# Two UI-only replays total; final layout_* files, no new fitting.
python -m evidence.bounded_archive_batch_20261016.verify_results
git diff --check
```

No in-app Browser available: skill runtime selector failed, troubleshooting read,
read-only browser list returned []; isolated headless Edge fallback used.
Initial automatic browser PASS did not establish full query-metadata correctness
or useful nested mobile height. These were found during visual/full-contract
review and fixed. Initial artifacts retained; final screenshots/layout_* reviewed.

The first contract test run exposed a pre-existing obsolete tuple stub in the K
config test. Strengthening the JS test also required JSON normalization of Python
tuples. The actual multipart test exposed 400 instead of intended413; fixed with
HTTPException, no retry/tuning of phase inference. Final logs are the passing runs.
Post-smoke code edits are UI query metadata/layout, upload error semantics, extra
code provenance metadata and tests/docs. No model/extractor settings changed.
