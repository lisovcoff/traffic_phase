"""Technical local-kernel DP/context witnesses, not a recovery benchmark."""
import hashlib
import json
from pathlib import Path

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.local_factor_sequence import infer_local_context

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/context_observation_20261016'


def main():
    model=dict(horizon_s=8,movements=['m0','m1'],cyclic_order=[0,1],
        rates_per_s=[[.2,.03],[.03,.2]],rate_source='technical witness',
        latent_demand_exposure=[[1]*4]*2,demand_source='supplied technical exposure',
        observation_windows_s=[[0,8]],observation_window_source='supplied camera window',
        release_delay_s=[[0,1.]],transit_delay_s=[[0,1.]],delay_source='supplied vehicle delay',
        release_detection_probability=1.,crossing_detection_probability=0.,
        release_method='witness',crossing_method='unused',clock_model='continuous_latent_rounded_marks',
        timestamp_resolution_ms=1,timestamp_rounding_origin_ms=0,timestamp_resolution_source='supplied 1ms clock')
    event=TemporalEvent(4250,'RELEASE','m0',1,'witness',.5,'MEDIUM',None,
        {'source':'technical_witness','track_fingerprint':'one'})
    evidence=build_local_evidence([event],source_namespace='technical_context')
    short=infer_local_context(evidence,model,context_origin_ms=0,target_range_ms=[3000,5000])
    long_model={**model,'horizon_s':64,'movements':['m0','m1','m2'],'cyclic_order':[2,0,1],
        'rates_per_s':[[.2,.03,.03],[.03,.2,.03],[.03,.03,.2]],
        'latent_demand_exposure':[[0]*32]*3,'observation_windows_s':[[0,64]]}
    long=infer_local_context(build_local_evidence([],source_namespace='no_demand'),long_model,
        context_origin_ms=0,target_range_ms=[4000,60000])
    assert short['complete'] and long['complete'] and long['likelihood_constant_over_phase_paths']
    output=dict(base_sha='08f82c3b382388fc201baa82a4ec37302ef8c4e4',
        purpose='technical equivalence/scaling, no recovery truth or real replay',
        short_context=short,long64s_zero_demand=long,
        source_sha256_lf={name:hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
            for name in ('app/experimental/local_factor_sequence.py','app/experimental/context_observation.py',
                'app/experimental/rounded_observation.py','app/experimental/observation_domain.py',
                'app/experimental/phase_observation_bridge.py','app/experimental/joint_track_model.py',
                'scripts/check_local_factor_sequence.py')})
    with (OUT/'dp_examples.json').open('x',encoding='utf-8') as f:json.dump(output,f,indent=2,allow_nan=False)
    for name,r in [('short',short),('long64s_zero_demand',long)]:
        print(name,r['status'],'wall_s=',r['wall_s'],'allowance_bytes=',r['declared_array_allowance_bytes'])


if __name__=='__main__':main()
