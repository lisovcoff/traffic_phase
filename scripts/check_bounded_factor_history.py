"""One technical64s delayed-pair example; no recovery truth or real replay."""
import hashlib
import json
from pathlib import Path
import subprocess

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.bounded_factor_sequence import infer_bounded_context

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/bounded_factor_history_20261016'


def write(name,value):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,allow_nan=False)


def main():
    spec=dict(horizon_s=64,movements=['m0','m1','m2'],cyclic_order=[2,0,1],
        rates_per_s=[[.2,.03,.03],[.03,.2,.03],[.03,.03,.2]],rate_source='declared technical rates',
        latent_demand_exposure=[[1]*32]*3,demand_source='supplied technical exposure',
        observation_windows_s=[[0,64]],observation_window_source='supplied technical camera window',
        release_delay_s=[[0,.5],[4,.5]],transit_delay_s=[[2,1.]],delay_source='supplied technical delay atoms',
        release_detection_probability=1.,crossing_detection_probability=.5,
        release_method='technical_release',crossing_method='technical_crossing',
        clock_model='continuous_latent_rounded_marks',timestamp_resolution_ms=1,
        timestamp_rounding_origin_ms=0,timestamp_resolution_source='supplied 1ms clock')
    events=[]
    for i,r in enumerate((8250,16250,28250,44250,58250)):
        for t,kind,method in ((r,'RELEASE','technical_release'),(r+2000,'CROSSING_PROXY','technical_crossing')):
            events.append(TemporalEvent(t,kind,f'm{i%3}',i,method,.5,'MEDIUM',None,
                {'source':'technical_example','track_fingerprint':str(i),'eligible_proxy':True}))
    inputs=dict(spec=spec,events=[e.to_dict() for e in events],context_origin_ms=0,target_range_ms=[10000,56000])
    write('inputs.json',inputs)
    sources=['app/experimental/bounded_factor_sequence.py','app/experimental/context_observation.py',
        'app/experimental/rounded_observation.py','app/experimental/observation_domain.py',
        'app/experimental/phase_observation_bridge.py','app/experimental/joint_track_model.py',
        'app/experimental/unanchored_sequence.py','app/experimental/local_factor_sequence.py',
        'scripts/check_bounded_factor_history.py']
    limits=dict(max_kernel_span_cells=3,max_states_per_layer=4096,
        max_total_states=100000,max_memory_bytes=32*1024*1024,max_seconds=5.)
    write('manifest.json',dict(base_sha='9cfec60b8b7f1d9cef9d442f2c838be953a11d8c',
        code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        purpose='technical exact-message scaling; no recovery truth',
        input_sha256=hashlib.sha256((OUT/'inputs.json').read_bytes()).hexdigest(),
        source_sha256_lf={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sources},
        max_calls=1,limits=limits))
    output=infer_bounded_context(build_local_evidence(events,source_namespace='technical_delayed_pairs'),spec,
        context_origin_ms=0,target_range_ms=[10000,56000],**limits)
    write('prediction.json',output)
    write('output_sealed.json',dict(prediction_sha256=hashlib.sha256((OUT/'prediction.json').read_bytes()).hexdigest(),
        technical_inference_calls=1,recovery_truth_files=0,real_replays=0))
    print(json.dumps({k:output.get(k) for k in ('status','reason','observed_max_kernel_span_cells',
        'max_states_in_layer','max_retained_states','declared_state_allowance_bytes','cpu_s','wall_s')},indent=2))


if __name__=='__main__':main()
