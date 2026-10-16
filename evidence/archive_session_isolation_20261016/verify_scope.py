"""Input parity and saved-output/browser checks only; never phase fitting."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import types
from collections.abc import Mapping
from array import array

from app.core.state_contract import prepare_logical_query
from app.core.v9 import events

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = '13bc172de40c8f531ce174637e9d66aeb574aa18'


def normal(value):
    if isinstance(value, Mapping):
        return {k: normal(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, array)):
        return [normal(v) for v in value]
    return value


def seal(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def bundle_value(bundle):
    return normal(dict(packed=list(bundle), events=[e.to_dict() for e in bundle.temporal_events],
                       permission_streams=bundle.permission_streams, diagnostics=bundle.diagnostics))


old_source = subprocess.check_output(['git', 'show', f'{BASE}:app/core/v9/events.py'], cwd=ROOT).decode()
before_module = types.ModuleType('app.core.v9._source_scope_before')
before_module.__package__ = 'app.core.v9'
exec(compile(old_source, '<sealed-base-events>', 'exec'), before_module.__dict__)
source = ROOT/'evidence/seven_restart_review_20261015/selected_raw_tracks.json'
if source.stat().st_size > 2*1024*1024:
    raise ValueError('INPUT_PARITY_BYTE_BUDGET')
before = bundle_value(before_module.load_event_streams(source))
after = bundle_value(events.load_event_streams(source))
assert before == after
checks = []
for name in ['browser_results.json', 'layout_browser_results.json']:
    report = json.loads((OUT/name).read_text(encoding='utf-8'))
    prediction_name = 'layout_selected_prediction.json' if name.startswith('layout_') else 'selected_prediction.json'
    prediction = json.loads((OUT/prediction_name).read_text(encoding='utf-8'))
    query = prepare_logical_query(prediction)
    offset = (prediction['schedule_base_timestamp_ms']-prediction['recording_start_timestamp_ms'])/1000
    for row in report['queries']:
        state = query.at(row['t']-offset)
        assert row['snapshot']['phaseName'] == state.estimated_state
        assert all(h['main']['state'] == 'UNKNOWN' and not h['arrows'] for h in row['snapshot']['heads'].values())
    assert query.at(-86400-offset).estimated_state == 'UNKNOWN'
    assert report['stale_result_hidden']
    assert [r['status'] for r in report['responses']] == [409, 409, 200]
    checks.append(dict(report=name, common_queries=len(report['queries']), other_session_query='UNKNOWN',
                       phase_count=prediction['schedule']['phase_count'], period_s=prediction['schedule']['period_s']))
initial = json.loads((OUT/'selected_prediction.json').read_text(encoding='utf-8'))
replay = json.loads((OUT/'layout_selected_prediction.json').read_text(encoding='utf-8'))
for field in ['schedule', 'phase_model_selection', 'period_inference', 'input_scope']:
    assert initial[field] == replay[field], field

# No fitting function, likelihood/decoder, objective, threshold or period change.
old_model = ast.parse(subprocess.check_output(['git','show',f'{BASE}:app/core/v9/model.py'],cwd=ROOT).decode())
current_model = ast.parse((ROOT/'app/core/v9/model.py').read_text(encoding='utf-8'))
current_functions = {n.name: n for n in current_model.body if isinstance(n, ast.FunctionDef)}
for node in old_model.body:
    if isinstance(node, ast.FunctionDef) and node.name not in {'discover_path', 'discover_records'}:
        assert ast.dump(node) == ast.dump(current_functions[node.name]), node.name
protected = ['app/core/v9/fit.py','app/core/v9/decoder.py','app/core/v9/primitives.py',
             'app/core/v9/vehicle_evidence.py','app/core/state_contract.py','app/core/v10',
             'scripts/offline_benchmark.py','benchmarks','config']
assert not subprocess.check_output(['git','diff','--name-only',BASE,'--',*protected],cwd=ROOT).strip()
assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip() == 'a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
result = dict(base_sha=BASE, single_session_input_sha256=seal(after), before_sha256=seal(before),
              packed_events_selection_provenance_exact=True, source_bytes=source.stat().st_size,
              browser_core_checks=checks, saved_replay_invariants_exact=True,
              unchanged_fitting_function_asts=True, protected_files_unchanged=True, main_unchanged=True,
              phase_fits_in_this_verification=0, real_benchmarks=0)
(OUT/'invariants.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
