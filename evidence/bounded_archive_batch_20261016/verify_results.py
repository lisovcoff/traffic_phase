"""Verify saved outputs only. No fitting, real data, annotations or new metrics."""
import json
import argparse
from pathlib import Path
import subprocess
import zipfile

from app.core.archive_batch import sha256_file
from app.core.state_contract import prepare_logical_query

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = '519e6ea94610d12f5c814721d993ca02f2015b29'
MAIN = 'a005a2521f62ce3b2c9f9d52f9f0d73913754e01'


def differences(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        return [p for key in sorted(a.keys() | b.keys()) for p in differences(a.get(key), b.get(key), path+'/'+key)]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [p for i, (x, y) in enumerate(zip(a, b)) for p in differences(x, y, path+'/'+str(i))]
    return [] if a == b else [path]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='create summary before sealing; default verifies read-only')
    args = parser.parse_args()
    freeze = json.loads((OUT/'freeze.json').read_text(encoding='utf-8'))
    assert sha256_file(ROOT/freeze['input']) == freeze['input_sha256']
    old = json.loads((ROOT/'evidence/archive_session_isolation_20261016/server_prediction.json').read_text(encoding='utf-8'))
    archives = {}
    for name in ('download.zip', 'layout_download.zip'):
        with zipfile.ZipFile(OUT/name) as archive:
            assert archive.testzip() is None
            manifest = json.loads(archive.read('manifest.json'))
            assert manifest['config'] == freeze['config']
            assert manifest['input_sha256'] == freeze['input_sha256']
            assert manifest['attempted_jobs'] == 3
            assert manifest['status'] == 'COMPLETE_ESTIMATES'
            assert [len(s['jobs']) for s in manifest['sources_processed']] == [1, 2]
            predictions = []
            for source in manifest['sources_processed']:
                for job in source['jobs']:
                    path = source['artifact_directory']+'/'+job['prediction']
                    value = json.loads(archive.read(path))
                    import hashlib
                    assert hashlib.sha256(archive.read(path)).hexdigest() == job['prediction_sha256']
                    report = source['artifact_directory']+'/'+job['report']
                    assert hashlib.sha256(archive.read(report)).hexdigest() == job['report_sha256']
                    assert value['input_scope']['selected_session'] == job['session']
                    assert value['trajectory_count'] == value['event_count'] == 40
                    assert value['schedule'] == old['schedule']
                    assert value['period_inference'] == old['period_inference']
                    assert not value.get('reconstruction_history')
                    predictions.append(value)
            archives[name] = dict(manifest=manifest, predictions=predictions)
    for a, b in zip(archives['download.zip']['predictions'], archives['layout_download.zip']['predictions']):
        assert a == b
    selected = archives['download.zip']['predictions'][-1]
    assert selected['event_extraction'] == old['event_extraction']
    assert selected['phase_evidence'] == old['phase_evidence']
    changed_selection_fields = differences(old['phase_model_selection'], selected['phase_model_selection'])
    # The unchanged solver records timings; these are not selection scores.
    assert all(p.endswith(('/runtime_s', '/elapsed_s')) for p in changed_selection_fields)
    checks = []
    for name in ('browser_results.json', 'layout_browser_results.json'):
        browser = json.loads((OUT/name).read_text(encoding='utf-8'))
        assert browser['status'] == 'PASS' and not browser['errors']
        queries = 0
        initial_query_metadata_mismatches = []
        for prediction, report in zip(archives['download.zip']['predictions'], browser['session_reports']):
            query = prepare_logical_query(prediction)
            for row in report['queries']:
                expected = json.loads(json.dumps(query.at(row['t']).to_dict()))
                if name.startswith('layout_'):
                    assert expected == row['state']
                else:
                    paths = differences(expected, row['state'])
                    assert all(p in ('/observation_support/timestamp_s', '/observation_support/query_position_s') for p in paths)
                    initial_query_metadata_mismatches.extend(paths)
                queries += 1
            assert report['lamp'] == report['physical']['estimated_state'] == 'UNKNOWN'
            assert report['physical']['calibrated_lamp_probability'] is None
        checks.append(dict(browser=name, queries=queries, physical_state='UNKNOWN',
                           initial_query_metadata_mismatches=len(initial_query_metadata_mismatches)))
    protected = ['app/core/v9', 'app/core/state_contract.py', 'app/core/temporal_evidence.py',
                 'app/core/trajectory_events.py', 'app/core/v10', 'scripts/offline_benchmark.py',
                 'benchmarks', 'config']
    assert not subprocess.check_output(['git', 'diff', '--name-only', BASE, '--', *protected], cwd=ROOT).strip()
    assert subprocess.check_output(['git', 'rev-parse', 'main'], cwd=ROOT, text=True).strip() == MAIN
    output = dict(base_sha=BASE, main_unchanged=MAIN, protected_files_unchanged=True,
        ordinary_synthetic_batches=1, fitted_sessions=3, real_replays=0,
        selected_schedule_period_exact_previous_prediction=True,
        selected_event_extraction_selection_exact_previous_prediction=True,
        selection_difference_paths=changed_selection_fields,
        replay_predictions_exact=True, browser_core=checks,
        source_runtime_s=archives['download.zip']['manifest']['runtime_s'],
        note='Technical invariance, not independent K/phase/lamp accuracy. Existing 2D.1 FAIL retained.')
    if args.write:
        (OUT/'invariants.json').write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    else:
        saved = json.loads((OUT/'invariants.json').read_text(encoding='utf-8'))
        assert output == saved
        manifest = json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
        for name, expected in manifest['outputs_sha256_raw'].items():
            assert sha256_file(OUT/name) == expected, name
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
