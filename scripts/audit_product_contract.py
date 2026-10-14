"""Read-only product audit probes. No discovery, fitting or trajectory replay."""
import hashlib
import json
from pathlib import Path
import subprocess
from app.core.v9.signal_renderer import build_signal_model, signal_state_at

ROOT=Path(__file__).resolve().parents[1]


def main():
    source=ROOT/'scripts/v9_spatial_visualizer.py'
    text=source.read_text(encoding='utf-8')
    # Execute the existing JS functions directly, without changing their logic.
    probability=text[text.index('function probability('):text.index('function physicalSectionState(')]
    section=text[text.index('function physicalSectionState('):text.index('function physicalHeadInfo(')]
    movement=text[text.index('function movementState('):text.index('function headInfo(')]
    prediction={'schedule':{'phase_count':2,'phase_names':['A','B'],'period_s':60,
        'raw_hsmm_segments':[[0,30,0],[30,60,1]],'baseline_segments':[[0,30,0],[30,60,1]],
        'stream_activity_by_phase':[{'stream':'N->S','event_probability_by_phase':{'A':.9,'B':.01}}]}}
    model=build_signal_model(prediction)
    js='const SIGNAL_MODEL='+json.dumps(dict(model))+';\n'+'''
const PHYSICAL={enabled:false};
const ACTIVITY_THRESHOLD=0.05, YELLOW_S=3, RED_YELLOW_S=2;
let tGlobal=10;
function adjacentPhase(){return 1;}
'''+probability+section+movement+'''
const seg={start:0,end:30,phase:0,index:0};
const inside=movementState("N->S",seg);
tGlobal=29; const end=movementState("N->S",seg);
const unknown=physicalSectionState("UNKNOWN","UNKNOWN","UNKNOWN",10,10);
console.log(JSON.stringify({inside,near_end:end,unknown_input_section:unknown}));
'''
    js_result=json.loads(subprocess.check_output(['node','-e',js],text=True))
    core={str(t):signal_state_at(model,t)['streams'][0]['state'] for t in [10,29,61]}
    output={'base_sha':'fc3f5f51c8c9d4c0aa7f83d5b7d67d17df290190',
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'no_fitting':True,'core_reconstructed_states':core,'existing_html_functions':js_result,
            'finding':'HTML activity color/transition path does not enforce shared reconstructed UNKNOWN contract'}
    assert core=={'10':'UNKNOWN','29':'UNKNOWN','61':'UNKNOWN'}
    assert js_result['inside']['state']=='GREEN'
    assert js_result['near_end']['state']=='YELLOW'
    assert js_result['unknown_input_section']=='RED'
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
