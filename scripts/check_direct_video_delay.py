"""Fit apparent camera-clock onset biases on one window; score the fixed second."""
import argparse
import hashlib
import json
from pathlib import Path
from app.experimental.video_onset_bias import head_onsets,fit_constant_bias,evaluate_bias
from scripts.video_truth_inventory import ROOT,OUT,save

TARGET=OUT/'conditional_onset_calibration'
PRED=ROOT/'evidence/learned_archive_integration_20261018/archive_1/result.json'
SOURCES={'green':OUT/'sverdlovsky/video_only_truth_sealed.json',
         'red':OUT/'sverdlovsky/video_red_truth_sealed.json'}


def read(path):return json.loads(path.read_text(encoding='utf8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def material():
    clock=next(r for r in read(OUT/'clock_readouts.json') if r['site']=='sverdlovsky')
    result=read(PRED);estimate=result['estimated_signals']
    off=(estimate['schedule_base_timestamp_ms']-clock['nominal_base_ms'])/1000
    onsets={color:[t+off for t in head_onsets(estimate,'N',color.upper())] for color in SOURCES}
    return clock,onsets


def fit():
    TARGET.mkdir(exist_ok=False)
    clock,onsets=material();candidates={}
    for color,path in SOURCES.items():
        window=next(w for w in read(path)['windows'] if w['window']=='calibration')
        predicted=[t for t in onsets[color] if 900<=t<1500]
        candidates[color]=fit_constant_bias(predicted,window['transitions'])
    save(TARGET/'frozen_candidates.json',dict(
        source_prediction_sha256=sha(PRED),truth_sha256={c:sha(p) for c,p in SOURCES.items()},
        fitting_scope_video_pts_s=[900,1500],test_scope_video_pts_s=[2700,3300],
        candidates=candidates,nominal_video_epoch_ms=clock['nominal_base_ms'],
        assumptions=['visible H1 corresponds to N main based on previous local movement review',
                     'JSON clock equals camera overlay epoch plus media PTS; NOT independently verified',
                     'constant onset-specific bias transfers across this recording'],
        prior_diagnostics='Baseline green and red test-window errors were printed before candidate serialization; no test-dependent fitting rule or parameter change.',
        production_enabled=False,physical_lamp_accuracy_proven=False))
    print(json.dumps({c:v['bias_s'] for c,v in candidates.items()}),flush=True)


def evaluate():
    frozen=read(TARGET/'frozen_candidates.json')
    assert sha(PRED)==frozen['source_prediction_sha256']
    clock,onsets=material();results={}
    for color,path in SOURCES.items():
        assert sha(path)==frozen['truth_sha256'][color]
        window=next(w for w in read(path)['windows'] if w['window']=='validation')
        predicted=[t for t in onsets[color] if 2700<=t<3300]
        results[color]=dict(before=evaluate_bias(predicted,window['transitions']),
            after=evaluate_bias(predicted,window['transitions'],frozen['candidates'][color]['bias_s']),
            expected_video_cycles=6,unresolved_video_truth=6-len(window['transitions']))
    save(TARGET/'evaluation.json',dict(conditional_only=True,json_video_clock_verified=False,
        physical_lamp_accuracy_proven=False,other_heads_evaluated=False,results=results,
        red_unpaired_prediction_interpretation='one missing video label; cannot call it a false prediction',
        separate_onset_biases_do_not_define_a_complete_validated_intersection_phase_plan=True))
    print(json.dumps({color:{name:{k:v for k,v in data.items() if k!='pairs'} for name,data in row.items() if name in ('before','after')} for color,row in results.items()},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['fit','evaluate'])
    globals()[p.parse_args().command]()
