"""Fixed small T-structure regression suite; not an independent accuracy holdout."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time
import uuid
import zipfile

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(out):
    from scripts import realistic_traffic_benchmark as sim
    from app.core.intersection_project import run_project,read_json
    from app.api.intersection_projects import PROJECT_ROOT
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    configs=[]
    for k in (2,3):
        for rotation in range(4):
            configs.append(dict(name=f'k{k}_rotation{rotation}',rotation=rotation,
                config=dict(seed=2026101901,k=k,duration_s=1200,period_s=90,
                    arrival_rate_s=.07,cycle_jitter=.01,realistic_turns=True)))
    save(out/'protocol.json',dict(scope='development T-structure regression; no parameter tuning, no independent accuracy claim',
        configs=configs,criteria='observed approaches equal generated approaches; one family with expected working K',
        evaluation_truth_not_passed_to_application=True))
    environment=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    original=deepcopy(sim.GROUPS);order='NESW';results=[]
    # Seal every case before fitting any of them.
    for case in configs:
        k=case['config']['k'];rotation=case['rotation'];mapping={a:order[(i+rotation)%4] for i,a in enumerate(order)}
        groups=[['N->_S','S->_N'],['E->_N','N->_E']] if k==2 else [['N->_S','S->_N'],['N->_E'],['E->_N']]
        sim.GROUPS[k]=[['->'.join(mapping[p.replace('_','')] for p in m.split('->')) for m in group] for group in groups]
        try:tracks,truth=sim.generate(case['config'],environment)
        finally:sim.GROUPS=deepcopy(original)
        folder=PROJECT_ROOT/uuid.uuid4().hex;folder.mkdir(parents=True)
        source=folder/'input.zip'
        with zipfile.ZipFile(source,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('anonymous.json',json.dumps(tracks,separators=(',',':')))
        save(out/(case['name']+'_truth.json'),truth)
        case.update(folder=str(folder),source=str(source),expected_approaches=sorted(mapping[a] for a in ['N','S','E']))
    save(out/'sealed_inputs.json',configs)
    for case in configs:
        started=time.monotonic();model=run_project(case['source'],case['folder'])
        counts=[r['phase_count'] for r in model['regimes']]
        passed=counts==[case['config']['k']] and sorted(model['approaches'])==case['expected_approaches']
        row=dict(case=case['name'],status='PASS' if passed else 'FAIL',expected_k=case['config']['k'],
            working_k=counts,approaches=model['approaches'],expected_approaches=case['expected_approaches'],
            model_id=model['model_id'],runtime_s=time.monotonic()-started)
        results.append(row);save(out/(case['name']+'_receipt.json'),row);print(row,flush=True)
    save(out/'receipt.json',dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'FAIL',
        cases=results,passed=sum(r['status']=='PASS' for r in results),total=len(results),
        scope='development regression, not independent timing/color accuracy'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    main(parser.parse_args().out)
