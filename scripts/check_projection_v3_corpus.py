"""Revealed 96-case working-K regression; fitted numerical outputs stay sealed."""
import gzip
import json
from collections import Counter

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,digest,operating_template
from app.core.observed_topology import project_observed_topology
from scripts.verify_recovery_release import prediction_path,MODE,RUNTIME
from scripts.check_regime_observations import OUT


def main():
    manifest=read_json(ROOT/'evidence/accuracy_recovery_20261019/release_manifest.json')
    sealed={r['path']:r for r in manifest['local_reproduction_files']}
    keys=sorted(p.stem.removesuffix('.json') for p in (RUNTIME/'predictions'/MODE).glob('*.json.gz') if not p.name.startswith('real_'))
    assert len(keys)==96,len(keys)
    rows=[];counts=Counter()
    for key in keys:
        path=prediction_path(key);record=sealed[path.relative_to(ROOT).as_posix()]
        assert digest(path)==record['sha256']
        with gzip.open(path,'rt',encoding='utf8') as stream:result=json.load(stream)
        result.get('event_extraction',{}).pop('temporal_events',None)
        old=operating_template(project_observed_topology(result,['N','S','E','W'],repair_missing_phases=True))
        new=operating_template(project_observed_topology(result,['N','S','E','W'],repair_missing_phases='selective'))
        # Expected K is evaluator-only and is read after both predictions.
        expected=int(key.split('k',1)[1].split('_',1)[0]);partition='old_holdout' if key.startswith('holdout_') else 'old_development'
        before=old['schedule']['phase_count'];after=new['schedule']['phase_count']
        rows.append(dict(key=key,expected_K=expected,old_working_K=before,new_working_K=after,latent_K=result['schedule']['phase_count'],prediction_sha256=record['sha256']))
        counts[partition+'_n']+=1;counts[partition+'_before']+=before==expected;counts[partition+'_after']+=after==expected
    save(OUT/'projection_v3_regression.json',dict(scope='96 previously revealed synthetic cases; no new independent accuracy claim; current projection on unchanged sealed solver outputs',counts=dict(counts),rows=rows))
    print('PROJECTION_REGRESSION',dict(counts),flush=True)


if __name__=='__main__':main()
