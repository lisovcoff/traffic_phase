"""Two separately frozen observation hypotheses, no manual labels in inference."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.isolated_phase_check import ROOT,SOURCE,sha,save

VARIANTS=('positive_onsets','silent_censoring')


def positive_boundary_evidence(by_stream,period,resolution_s=.5,smooth_s=2.5):
    import numpy as np
    from scipy.ndimage import gaussian_filter1d
    if not by_stream or period<=0:return None,None
    n=max(64,int(round(period/max(.1,resolution_s))))
    profiles=[]
    for ts in by_stream.values():
        if len(ts)<4:continue
        h=np.zeros(n,dtype=float)
        for t in ts:h[int(float(t)%period/period*n)%n]+=1.
        h=gaussian_filter1d(h,max(.8,smooth_s/(period/n)),mode='wrap')
        d=gaussian_filter1d(np.roll(h,-1)-np.roll(h,1),.8,mode='wrap')
        profiles.append(np.maximum(d,0.)/(float(np.std(d))+1e-6))
    if not profiles:return None,None
    evidence=np.mean(np.asarray(profiles),axis=0)
    evidence-=float(np.min(evidence))
    peak=float(np.max(evidence))
    if peak>1e-9:evidence/=peak
    return np.arange(n,dtype=float)*period/n,evidence


def install(variant):
    import numpy as np
    from app.core.v9 import fit,primitives
    if variant=='positive_onsets':
        fit._periodic_boundary_evidence=positive_boundary_evidence
        return
    if variant!='silent_censoring':raise ValueError(variant)
    original_template=fit.fit_bernoulli_templates
    original_likelihood=fit._pointwise_loglik
    original_decode=fit.decode_cyclic_hsmm
    original_metrics=fit.candidate_metrics
    original_quality=fit._fit_quality
    observed_count=[0]
    def mask(x):return np.any(x>0,axis=1)
    def templates(x,labels,k):
        observed=mask(x);observed_count[0]=int(np.sum(observed))
        return original_template(x[observed],np.asarray(labels)[observed],k)
    def likelihood(x,probs,labels):
        observed=mask(x)
        return original_likelihood(x[observed],probs,np.asarray(labels)[observed])
    def decode(x,probs,period,k,**kwargs):
        kwargs['observation_mask']=mask(x)
        return original_decode(x,probs,period,k,**kwargs)
    def metrics(value,shape):
        return original_metrics(value,(observed_count[0],shape[1]))
    def quality(value,shape,evidence_weight=.05):
        return original_quality(value,(observed_count[0],shape[1]),evidence_weight=evidence_weight)
    fit.fit_bernoulli_templates=primitives.fit_bernoulli_templates=templates
    fit._pointwise_loglik=primitives._pointwise_loglik=likelihood
    fit.decode_cyclic_hsmm=decode
    fit.candidate_metrics=metrics
    fit._fit_quality=quality


def folder(variant):return ROOT/'benchmarks'/('observation_'+variant+'_20261018')


def infer(variant,source,target):
    import numpy as np
    np.random.seed(0)
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.v9.model import _discover_bundle
    old,bundle=cached_bundle(source)
    install(variant)
    result=_discover_bundle(bundle,input_name=old['input'],dt=1.,marks_path=None,
        evidence_policy='permission_per_stream',source_files=old['archive']['source_files'],
        experimental_local_history=False)
    result['event_extraction'].pop('temporal_events')
    result['event_extraction']['temporal_events_ref']={'file':source.relative_to(ROOT).as_posix(),'sha256':sha(source)}
    result['observation_candidate']={'variant':variant,'unchanged_selection':True,
        'labels_used':False,'dt':1.,'seed':0,'timeline_unchanged':True}
    save(target,result)


def freeze():
    for variant in VARIANTS:
        out=folder(variant);out.mkdir(exist_ok=False)
        save(out/'freeze.json',dict(variant=variant,worker_sha256=sha(Path(__file__)),
            helper_sha256=sha(ROOT/'scripts/isolated_phase_check.py'),
            code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            fit_sha256=sha(ROOT/'app/core/v9/fit.py'),
            inputs=[dict(name=p.name,sha256=sha(p)) for p in sorted(SOURCE.glob('*.json'))],
            dt=1,seed=0,timeout_s=90,max_workers=3,max_total_worker_s=270,parameter_search=False))


def run(variant):
    out=folder(variant);plan=json.loads((out/'freeze.json').read_text(encoding='utf8'))
    assert sha(Path(__file__))==plan['worker_sha256']
    assert sha(ROOT/'scripts/isolated_phase_check.py')==plan['helper_sha256']
    assert sha(ROOT/'app/core/v9/fit.py')==plan['fit_sha256']
    ledger=[]
    for entry in plan['inputs']:
        source=SOURCE/entry['name'];assert sha(source)==entry['sha256']
        target=out/'predictions'/source.name
        print(variant,source.name,flush=True)
        started=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-m','scripts.observation_phase_check','infer',variant,
                str(source),str(target)],cwd=ROOT,timeout=90,capture_output=True,text=True,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if proc.returncode==0 else proc.stderr[-2500:]
        except subprocess.TimeoutExpired:reason='TIMEOUT_90S'
        ledger.append(dict(file=source.name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(out/'predictions_sealed.json',ledger)
    print(json.dumps(ledger,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['freeze','run','infer']);parser.add_argument('values',nargs='*')
    args=parser.parse_args()
    if args.command=='freeze':freeze()
    elif args.command=='run':run(*args.values)
    else:infer(args.values[0],Path(args.values[1]),Path(args.values[2]))
