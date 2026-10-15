"""Reproduce external-review P1 without phase inference or annotations."""
import argparse
import json
from pathlib import Path

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.phase_observation_bridge import prepare_joint_observation
from app.experimental.joint_track_model import path_loglik

OUT=Path(__file__).resolve().parents[1]/'evidence/query_observation_completeness_20261015'


def inputs():
    events=[]
    for ts,kind,method in ((6250,'RELEASE','test_release'),(8250,'CROSSING_PROXY','test_crossing')):
        events.append(TemporalEvent(ts,kind,'m0',1,method,.5,'MEDIUM',None,
            {'source':'review_counterexample','track_fingerprint':'one','eligible_proxy':True}))
    index=build_local_evidence(events,source_namespace='review')
    spec=dict(horizon_s=8,movements=['m0','m1'],rates_per_s=[[.2,.03],[.03,.2]],
        rate_source='review witness',latent_demand_exposure=[[1]*4]*2,demand_source='review witness',
        observation_windows_s=[[0,20]],observation_window_source='review witness',
        release_delay_s=[[0,1.]],transit_delay_s=[[2,1.]],delay_source='review witness',
        release_detection_probability=1.,crossing_detection_probability=1.,
        release_method='test_release',crossing_method='test_crossing')
    return index,spec


def probe():
    index,spec=inputs();results={}
    for name,end in (('truncated_pair',8000),('complete_pair',20000)):
        r=prepare_joint_observation(index.query(0,end),spec,origin_ms=0)
        results[name]=dict(status=r['status'],reason=r['reason'])
    empty=build_local_evidence([],source_namespace='empty').query(0,2000)
    spec['observation_windows_s']=[[0,8]];spec['crossing_detection_probability']=0.
    r=prepare_joint_observation(empty,spec,origin_ms=0)
    results['empty_short_query']=dict(status=r['status'],reason=r['reason'],
        log_likelihood=path_loglik([0]*4,r['components']) if r['components'] is not None else None)
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['before','after']);args=p.parse_args()
    result=probe()
    with (OUT/(args.stage+'.json')).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
