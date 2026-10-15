"""Small observation-contract witnesses only: no sequence inference/truth files."""
import hashlib
import json
from pathlib import Path

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.context_observation import prepare_context_observation
from app.experimental.rounded_observation import rounded_components
from app.experimental.joint_track_model import path_loglik

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/context_observation_20261016'


def main():
    model=dict(horizon_s=8,movements=['straight','turn'],rates_per_s=[[.2,.03],[.03,.2]],
        rate_source='declared contract example',latent_demand_exposure=[[1]*4]*2,
        demand_source='declared example exposure',observation_windows_s=[[0,20]],
        observation_window_source='declared example camera window',release_delay_s=[[0,1.]],
        transit_delay_s=[[2,1.]],delay_source='declared vehicle-delay example',
        release_detection_probability=1.,crossing_detection_probability=0.,
        release_method='example_release',crossing_method='example_crossing',
        clock_model='continuous_latent_rounded_marks',timestamp_resolution_ms=1,
        timestamp_rounding_origin_ms=0,timestamp_resolution_source='declared rounding clock')
    empty=build_local_evidence([],source_namespace='fixed-context-example')
    short={**model,'query_delivery_mode':'censored_reported_timestamps'}
    comp=rounded_components(empty.query(0,2000),short)
    events=[TemporalEvent(t,'RELEASE','straight',i,'example_release',.5,'MEDIUM',None,
        {'source':'example','track_fingerprint':str(i)}) for i,t in enumerate((250,2250))]
    evidence=build_local_evidence(events,source_namespace='fixed-context-example')
    context=prepare_context_observation(evidence,{**model,'release_delay_s':[[2,1.]]},
        context_origin_ms=0,target_range_ms=[3000,5000])
    output=dict(base_sha='08f82c3b382388fc201baa82a4ec37302ef8c4e4',
        scientific_sequence_inference_calls=0,real_replay_calls=0,
        short_query=dict(model_conditioned_loglik=path_loglik([0]*4,comp),
            expected_loglik=-(.2+.03)*1.9995,observation_domain=comp['observation_domain']),
        finite_context=dict(status=context['status'],reason=context['reason'],
            context_plan=context.get('context_plan'),
            selected_vehicle_ids=[t['group_id'] for t in context['components']['tracks']],
            selected_relative_release_ms=[t['release_ms'] for t in context['components']['tracks']],
            logical_phase=context['logical_phase'],physical_section=context['physical_section']),
        source_sha256_lf={name:hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
            for name in ('app/experimental/context_observation.py','app/experimental/observation_domain.py',
                'app/experimental/rounded_observation.py','app/experimental/phase_observation_bridge.py',
                'app/experimental/joint_track_model.py','scripts/check_context_observation.py')})
    assert abs(output['short_query']['model_conditioned_loglik']-output['short_query']['expected_loglik'])<1e-12
    assert output['finite_context']['selected_relative_release_ms']==[2250]
    with (OUT/'contract_examples.json').open('x',encoding='utf-8') as f:json.dump(output,f,indent=2,allow_nan=False)
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
