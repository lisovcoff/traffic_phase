"""Regression-only re-projection of96 already-revealed frozen numerical fits."""
import argparse
import gzip
import json
from pathlib import Path

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(out):
    import numpy as np
    from scripts.accuracy_recovery import OUT,RUNTIME,OLD
    from scripts.verify_recovery_release import prediction_path
    from scripts.realistic_traffic_benchmark import production_main_head_scores
    from app.core.observed_topology import project_observed_topology
    from app.core.intersection_project import operating_template
    out=Path(out);out.mkdir(parents=True,exist_ok=False);rows=[]
    for suite,path in [('development',OUT/'development_suite.json'),('revealed_reserved',OUT/'holdout/suite.json')]:
        for config in json.loads(path.read_text())['cases']:
            key=config['id'];parent=RUNTIME/'holdout'/key if suite=='revealed_reserved' else OLD/'synthetic'/key
            with gzip.open(parent/'truth.json.gz','rt',encoding='utf8') as f:truth=json.load(f)
            with gzip.open(prediction_path(key),'rt',encoding='utf8') as f:original=json.load(f)
            projected=project_observed_topology(original,['N','S','E','W'],repair_missing_phases=True)
            times=np.arange(0,float(config['duration_s']),.25)
            before=production_main_head_scores(original,truth,times);after=production_main_head_scores(projected,truth,times)
            error=lambda score:float(np.mean([h['error_fraction'] for h in score['heads'].values()]))
            row=dict(id=key,suite=suite,expected_k=config['k'],latent_k=original['schedule']['phase_count'],
                working_k_before=operating_template(original)['schedule']['phase_count'],
                working_k_after=operating_template(projected)['schedule']['phase_count'],
                main_error_before=error(before),main_error_after=error(after),duration_s=config['duration_s'],
                repaired_phases=projected.get('physical_signal_plan',{}).get('projection_repair',{}))
            rows.append(row);save(out/(key+'.json'),row)
    summaries=[]
    for suite in ('development','revealed_reserved'):
        selected=[r for r in rows if r['suite']==suite];weights=[r['duration_s'] for r in selected]
        summaries.append(dict(suite=suite,cases=len(selected),
            working_k_correct_before=sum(r['working_k_before']==r['expected_k'] for r in selected),
            working_k_correct_after=sum(r['working_k_after']==r['expected_k'] for r in selected),
            main_error_before=float(np.average([r['main_error_before'] for r in selected],weights=weights)),
            main_error_after=float(np.average([r['main_error_after'] for r in selected],weights=weights)),
            regressed_cases=[r['id'] for r in selected if r['main_error_after']>r['main_error_before']+1e-9]))
    save(out/'receipt.json',dict(status='COMPLETED',summaries=summaries,numerical_refits=False,
        scope='already-revealed regression data; same original four-head assumption, not independent validation or geometry certification'))
    print(summaries,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);main(p.parse_args().out)
