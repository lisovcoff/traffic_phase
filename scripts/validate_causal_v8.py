"""Reproduce automatic offline training and eight independent SUMO replays.

SUMO is an optional validation dependency. Generated truth is read only by the
scorer, never the estimator. Existing output directories are never overwritten.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

TRAINING=[('k2',2,4,20261020),('k3',3,4,202610212),
          ('t3',3,3,202610214),('k4',4,4,2026102174)]


def cases():
    rows=[]
    for name,k,a,seed,extra in [
        ('k2_normal',2,4,2026102421,{}),
        ('k2_extension',2,4,2026102421,dict(extension_s=12)),
        ('k2_regime',2,4,2026102421,dict(regime_change=True)),
        ('k2_blocked',2,4,2026102421,dict(downstream_stop_s=180)),
        ('k3_normal',3,4,2026102422,{}),('t3_normal',3,3,2026102423,{}),
        ('k4_normal',4,4,2026102424,{}),
        ('k2_two_changes',2,4,2026102425,dict(program_changes=[
            dict(at_s=315,period_s=115),dict(at_s=630,period_s=90)]))]:
        config=dict(seed=seed,k=k,approaches=a,duration_s=900,period_s=100,
                    extension_s=0,regime_change=False,downstream_stop_s=0)
        config.update(extra)
        rows.append((name,'t3' if a==3 else 'k'+str(k),config))
    return rows


def comparison(baseline,candidate):
    def false_green(row):
        return sum(n for pair,n in row['confusion'].items()
                   if pair.endswith('->GREEN') and not pair.startswith('GREEN->'))
    a,b=baseline['counts'],candidate['counts']
    if a['total']!=b['total']:raise ValueError('Different scoring denominators')
    return dict(aggregate_nondecreasing=b['correct']>=a['correct'],
        green_recall_nondecreasing=b['GREEN_correct']>=a['GREEN_correct'],
        false_green_nonincreasing=false_green(candidate)<=false_green(baseline),
        all_color_recalls_nondecreasing=all(b.get(c+'_correct',0)>=a.get(c+'_correct',0)
            for c in ('RED','GREEN','YELLOW','RED_YELLOW')),
        baseline_false_green=false_green(baseline),candidate_false_green=false_green(candidate))


def run(output,sumo_home):
    os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    from scripts.corpus_validation import ROOT,prepare_worker_environment
    prepare_worker_environment()
    from scripts.sumo_validation import run as simulate
    from scripts.score_sumo_validation import score
    from app.core.intersection_project import run_project
    from app.core.intersection_engine import AdaptiveIntersection
    output.mkdir(parents=True,exist_ok=False)
    protocol=dict(training=TRAINING,cases=cases(),fresh_when_first_run='2026-10-20; now revealed',
        scope='Controlled SUMO scenarios; not six-archive real accuracy',
        code_sha256={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted((ROOT/'app').rglob('*.py'))},
        strict_gate='Every case: aggregate/GREEN/color recall nondecreasing; false GREEN nonincreasing')
    (output/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8',newline='\n')
    models={}
    for kind,k,a,seed in TRAINING:
        source=output/(kind+'_training')
        config=dict(seed=seed,k=k,approaches=a,duration_s=900,period_s=100,
                    extension_s=0,regime_change=False)
        if kind=='k4':config['downstream_stop_s']=0
        audit=simulate(config,source,sumo_home)
        if audit['physics_status']!='PASS':raise ValueError('Training physics gate failed')
        folder=output/(kind+'_model');run_project(source/'vehicles.json',folder)
        models[kind]=folder/'model.json'
    results=[]
    for name,kind,config in cases():
        folder=output/name;audit=simulate(config,folder,sumo_home)
        if audit['physics_status']!='PASS':raise ValueError('Replay physics gate failed')
        baseline=score(models[kind],folder,folder/'baseline.json')
        candidate=score(models[kind],folder,folder/'candidate.json',engine_factory=AdaptiveIntersection)
        results.append(dict(case=name,comparison=comparison(baseline,candidate),
            baseline=baseline,candidate=candidate))
    strict=all(all(r['comparison'][key] for key in (
        'aggregate_nondecreasing','green_recall_nondecreasing',
        'false_green_nonincreasing','all_color_recalls_nondecreasing')) for r in results)
    receipt=dict(strict_acceptance='PASS' if strict else 'FAIL',results=results,
                 video_or_lamp_truth_to_inference=False)
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf8',newline='\n')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--sumo-home',required=True,type=Path)
    parser.add_argument('--require-acceptance',action='store_true')
    args=parser.parse_args();receipt=run(args.output,args.sumo_home)
    print(json.dumps(dict(strict_acceptance=receipt['strict_acceptance'],cases=len(receipt['results']))))
    if args.require_acceptance and receipt['strict_acceptance']!='PASS':raise SystemExit(2)
