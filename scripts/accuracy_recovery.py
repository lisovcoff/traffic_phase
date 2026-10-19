"""Offline recovery experiments; candidate prediction never receives truth."""
from __future__ import annotations
import argparse
from array import array
from collections import defaultdict
from dataclasses import asdict
import gzip
import json
import hashlib
import pickle
from pathlib import Path
import time

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
import numpy as np

OUT=ROOT/'evidence/accuracy_recovery_20261019'
RUNTIME=ROOT/'.web_runtime/accuracy_recovery_20261019'
OLD=ROOT/'.web_runtime/all_archives_synthetic_20261019'


def cached_bundle(key,*,motion=False):
    from app.core.temporal_evidence import TemporalEvent
    from app.core.v9.events import _pack_temporal_events,load_event_streams
    if motion:
        cache=RUNTIME/'motion_event_cache'/(key+'.json.gz')
    elif key.startswith('real_'):
        cache=OLD/(key[5:]+'_events.json.gz')
    else:
        cache=RUNTIME/'event_cache'/(key+'.json.gz')
    if cache.exists():
        with gzip.open(cache,'rt',encoding='utf8') as f:r=json.load(f)
        return _pack_temporal_events([TemporalEvent(**e) for e in r['events']],r['files'],r['trajectories'],r['recording_start'],r.get('stats',{}))
    kwargs={}
    if motion:
        from app.experimental.motion_restart import extract_motion_evidence
        kwargs['_event_extractor']=extract_motion_evidence
    if key.startswith('real_'):
        jobs=json.loads((ROOT/'evidence/all_archives_synthetic_20261019/inventory.json').read_text(encoding='utf8'))['jobs']
        job=next(j for j in jobs if j['id']==key[5:]);source=Path(job['path']);kwargs['source_member']=job['member']
    else:source=(RUNTIME/'holdout'/key/'input.zip') if key.startswith('holdout_') else OLD/'synthetic'/key/'input.zip'
    bundle=load_event_streams(source,**kwargs)
    cache.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(cache,'xt',encoding='utf8') as f:
        json.dump(dict(events=[asdict(e) for e in bundle.temporal_events],files=bundle[5],
            trajectories=bundle[8],recording_start=bundle[6],stats={}),f)
    return bundle


def predict_candidate(bundle,mode):
    """Disposable-worker prototype. Never use monkeypatching in an API server."""
    import app.core.v9.model as model
    from app.core.v9.fit import PhaseCountSearch
    from app.core.v9.vehicle_evidence import select_permission_events_per_track
    from app.core.v9.events import _pack_temporal_events
    from app.core.temporal_evidence import EventStreamBundle
    original_search,original_period,original_regime=model.discover_phase_count,model.infer_period,model._local_regime_selection
    hybrid='hybrid' in mode
    if mode.startswith('tracks'):
        selected,_=select_permission_events_per_track(bundle.temporal_events)
        streams=defaultdict(list)
        for e in selected:streams[e.movement].append((e.timestamp_ms-bundle[7])/1000)
        bundle=EventStreamBundle(tuple(bundle),temporal_events=bundle.temporal_events,
            permission_streams={k:array('d',v) for k,v in streams.items()},diagnostics=bundle.diagnostics)
    def search(*args,**kwargs):
        # Cache numerical fits by observations/period, never by answer/source.
        x=args[0];signature=hashlib.sha256(x.tobytes()+repr(args[1:]).encode()+repr(sorted(kwargs.items())).encode()).hexdigest()
        cache=RUNTIME/'fit_cache'/(signature+'.pkl');cache.parent.mkdir(parents=True,exist_ok=True)
        if cache.exists():
            with cache.open('rb') as f:payload=pickle.load(f)
            result=PhaseCountSearch(payload[0],payload[1],payload[2],payload[3])
        else:
            result=original_search(*args,**kwargs)
            with cache.open('xb') as f:pickle.dump((*result,result.diagnostics),f)
        selected,candidates,fits=result
        supported=[]
        for c in candidates:
            probs=np.asarray(fits[c['k']]['probs'])
            # Relative movement support is invariant to traffic volume. A
            # Bernoulli floor alone cannot establish another phase.
            high=np.maximum(.03 if mode in ('active','permission','tracks') else .010001,.25*probs.max(axis=0))
            active=np.any(probs>high[None,:],axis=1)
            c['recovery_quiet_components']=int(np.sum(~active))
            if mode.startswith('tracks_marks') or hybrid:
                labels=np.asarray(fits[c['k']]['labels'])
                counts=np.array([x[labels==z].sum(axis=0) for z in range(c['k'])])
                den=np.maximum(counts.sum(axis=1,keepdims=True),1e-12)
                ll=float(np.sum(counts*np.log(np.maximum(counts/den,1e-15))))
                c['recovery_mark_bic']=float(-2*ll+(c['k']*x.shape[1]-1)*np.log(max(2.,counts.sum())))
            criterion=c.get('recovery_mark_bic',c['criterion_score'] if mode=='tracks_relative' else c['selection_score'])
            if np.all(active) and np.isfinite(criterion):supported.append(c)
        winner=min(supported,key=lambda c:c.get('recovery_mark_bic',c['criterion_score'] if mode=='tracks_relative' else c['selection_score']))['k'] if supported else selected
        if hybrid:
            from app.experimental.trajectory_phase_recovery import rate_equivalent_mapping
            base=[c for c in candidates if not c['recovery_quiet_components'] and np.isfinite(c['selection_score'])]
            if base:
                original=min(base,key=lambda c:c['selection_score'])
                cosine=0. if 'signature' in mode else .95
                original_groups=len(set(rate_equivalent_mapping(fits[original['k']]['probs'],cosine_min=cosine)[0].values()))
                new_groups=len(set(rate_equivalent_mapping(fits[winner]['probs'],cosine_min=cosine)[0].values()))
                if not original['unsupported_phase_count'] or new_groups<=original_groups:
                    winner=original['k']
        diagnostics={**result.diagnostics,'selected_k':winner,'recovery_no_quiet_phase':True,
            'original_selected_k':selected,'supported_candidate_count':len(supported)}
        return PhaseCountSearch(winner,candidates,fits,diagnostics)
    try:
        model.discover_phase_count=search
        if mode=='permission' or mode.startswith('tracks'):
            def infer(demand):
                period,info=original_period(bundle.permission_streams)
                if 'front' in mode:
                    from app.experimental.front_period import refine_front_period
                    period,diagnostic=refine_front_period(bundle.temporal_events,bundle[7],period,
                        max(max(v) for v in bundle.permission_streams.values()))
                    info={**info,'front_refinement':diagnostic}
                return period,info
            model.infer_period=infer
        model._local_regime_selection=lambda *args,**kwargs:None
        result=model._discover_bundle(bundle,input_name='trajectory-only recovery',dt=1.,marks_path=None,
            evidence_policy='permission_per_stream',experimental_local_history=False)
        result['recovery_candidate']=dict(mode=mode,video_used=False,truth_received=False,
            full_recording=True,prototype='disposable worker only')
        if mode in ('tracks_low','tracks_relative') or hybrid or mode.startswith('tracks_marks'):
            from app.experimental.trajectory_phase_recovery import merge_rate_equivalent_phases
            result=merge_rate_equivalent_phases(result,cosine_min=0. if 'signature' in mode else .95)
        if 'clock' in mode:
            from app.experimental.phase_clock import regularize_phase_clock
            result=regularize_phase_clock(result,bundle.temporal_events,boundary_sigma_s=.75 if 'clock075' in mode else 1.5)
        return result
    finally:
        model.discover_phase_count,model.infer_period,model._local_regime_selection=original_search,original_period,original_regime


def worker(key,modes):
    import traceback
    bundle=cached_bundle(key,motion='motion' in modes)
    for mode in modes.split(','):
        dest=OUT/'pilot'/mode/(key+'.json')
        if dest.exists():continue
        start=time.monotonic()
        try:
            result=predict_candidate(bundle,mode)
            product=RUNTIME/'predictions'/mode/(key+'.json.gz');product.parent.mkdir(parents=True,exist_ok=True)
            with gzip.open(product,'xt',encoding='utf8') as f:json.dump(result,f)
            row=dict(status='predicted',key=key,mode=mode,k=result['schedule']['phase_count'],period=result['schedule']['period_s'])
            if not key.startswith('real_'):
                from scripts.realistic_traffic_benchmark import score_prediction
                truth_path=RUNTIME/'holdout'/key/'truth.json.gz' if key.startswith('holdout_') else OLD/'synthetic'/key/'truth.json.gz'
                with gzip.open(truth_path,'rt',encoding='utf8') as f:truth=json.load(f)
                from scripts.validation_report import without_samples
                row['score']=without_samples(score_prediction(result,truth))
        except Exception as exc:row=dict(status='failed',key=key,mode=mode,error=str(exc),traceback=traceback.format_exc())
        row['runtime_s']=time.monotonic()-start;save(dest,row)
        print(key,mode,row['status'],row.get('k'),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--key',required=True)
    p.add_argument('--modes',default='active,permission,tracks');a=p.parse_args();worker(a.key,a.modes)


if __name__=='__main__':main()
