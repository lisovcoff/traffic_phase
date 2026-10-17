"""One bounded remaining-review comparison, reusing the inspected annotation-free worker."""
import argparse
from dataclasses import asdict
import importlib.metadata
import json
from pathlib import Path
import subprocess

from scripts import score_contract_review as previous
from scripts.hsmm_recurrence_check import cached_bundle, save, sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'benchmarks/review_closure_20261017'
SOURCE=ROOT/'benchmarks/stage2c_20261014/predictions'
BASELINE=ROOT/'benchmarks/tied_ranks_20261017/predictions'
BASE='c414c5ef486b145cb7605017fbeabee3e68237b0'
PROTOCOL=ROOT/'docs/REVIEW_CLOSURE_PROTOCOL_20261017.md'


def freeze():
    from app.core.v9.fit import PhaseSearchConfig
    OUT.mkdir(exist_ok=False)
    inputs=[]
    for source in sorted(SOURCE.glob('*_v9.json')):
        _,bundle=cached_bundle(source)
        inputs.append(dict(file=source.name,sha256=sha(source),baseline_sha256=sha(BASELINE/source.name),
            selected_indices=bundle.diagnostics['selected_event_indices'],temporal_events=len(bundle.temporal_events)))
    assert len(inputs)==3
    save(OUT/'freeze.json',dict(base_sha=BASE,inputs=inputs,seed=0,dt=1.,
        search_config=asdict(PhaseSearchConfig()),boundary_tolerance_s=2.,
        max_control_runs=1,max_corrected_runs=3,worker_timeout_s=90,total_worker_allowance_s=360,
        protocol_sha256=sha(PROTOCOL),control_raw_K_period_schedule='EXACT',control_float_atol=1e-12,
        worker_module='scripts.score_contract_review',worker_sha256=sha(ROOT/'scripts/score_contract_review.py'),
        package_versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','scikit-learn','fastapi')},
        source='lossless_event_cache_NOT_original_ingestion',local_2D1='FAIL_DEFAULT_OFF'))


def control():
    save(OUT/'control_started.json',dict(base_sha=BASE,fit_sha256=sha(ROOT/'app/core/v9/fit.py')))
    frozen=json.loads((OUT/'freeze.json').read_text())
    entry=next(r for r in frozen['inputs'] if r['file'].startswith('19_'))
    assert sha(SOURCE/entry['file'])==entry['sha256']
    row=previous.worker(SOURCE/entry['file'],OUT/'control.json')
    if not row['reason']:
        old=json.loads((BASELINE/entry['file']).read_text())
        new=json.loads((OUT/'control.json').read_text())
        row.update(schedule_exact=old['schedule']==new['schedule'],period_exact=old['period_inference']==new['period_inference'],
            k_exact=old['schedule']['phase_count']==new['schedule']['phase_count'])
    save(OUT/'control_check.json',row)
    assert not row['reason'] and row['schedule_exact'] and row['period_exact'] and row['k_exact'], 'STOP_CONTROL_MISMATCH'
    print(json.dumps(row))


def run():
    control=json.loads((OUT/'control_check.json').read_text())
    assert not control['reason'] and all(control[k] for k in ('schedule_exact','period_exact','k_exact'))
    frozen=json.loads((OUT/'freeze.json').read_text())
    assert sha(PROTOCOL)==frozen['protocol_sha256']
    assert sha(ROOT/'scripts/score_contract_review.py')==frozen['worker_sha256']
    assert not subprocess.check_output(['git','diff','HEAD','--','app/core','scripts/review_closure.py'],cwd=ROOT).strip()
    save(OUT/'corrected_started.json',dict(code_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        fit_sha256=sha(ROOT/'app/core/v9/fit.py')))
    rows=[]
    for entry in frozen['inputs']:
        assert sha(SOURCE/entry['file'])==entry['sha256']
        assert sha(BASELINE/entry['file'])==entry['baseline_sha256']
        print('One corrected cached worker:',entry['file'],flush=True)
        rows.append(previous.worker(SOURCE/entry['file'],OUT/'predictions'/entry['file']))
    save(OUT/'predictions_sealed.json',rows)
    print('All output hashes sealed before annotations')


def evaluate():
    previous.OUT,previous.SOURCE,previous.BASELINE=OUT,SOURCE,BASELINE
    previous.evaluate()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('freeze','control','run','evaluate'))
    globals()[parser.parse_args().command]()
