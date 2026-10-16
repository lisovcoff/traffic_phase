import copy
import json
import re
import shutil
import subprocess
import sys

import pytest

from app.core.offline_product_report import build_report_payload
from app.core.state_contract import prepare_logical_query
from scripts import v9_offline_visualizer as visualizer


def result():
    return dict(schedule_base_timestamp_ms=1000, trajectory_count=10, event_count=5,
        schedule=dict(phase_count=2, phase_names=['A','B'], period_s=20,
            raw_hsmm_segments=[[0,10,0],[12,20,1]], baseline_segments=[[0,10,0],[10,20,1]],
            stream_activity_by_phase=[{'stream':'N->S','event_probability_by_phase':{'A':.9,'B':.01}}]))


def test_reconstructed_html_does_not_synthesize_colors_from_activity_or_transitions():
    data=result();data['physical_signal_plan']={'stages':[{'main':'GREEN'}]}
    page=visualizer.render_html(data,yellow_duration_seconds=3,red_yellow_duration_seconds=2,activity_threshold=.05)
    assert 'Логическая фаза' in page and 'UNKNOWN' in page
    assert 'currentGreen' not in page and 'MODELLED_TRANSITION' not in page
    assert '"main":"GREEN"' not in page
    assert '"movement":"N-\\u003eS"' in page and 'Activity score' in page


def test_legacy_threshold_and_transition_arguments_cannot_change_reconstructed_page():
    one=visualizer.render_html(result(),yellow_duration_seconds=0,red_yellow_duration_seconds=0,activity_threshold=.01)
    two=visualizer.render_html(result(),yellow_duration_seconds=30,red_yellow_duration_seconds=20,activity_threshold=.99)
    assert one==two


def test_overlap_is_not_repaired_and_payload_is_detached():
    data=result();data['schedule']['raw_hsmm_segments']=[[0,10,0],[5,15,1]]
    frozen=copy.deepcopy(data);payload=build_report_payload(data)
    assert data==frozen and payload['intervals']==[]
    assert payload['fallback_logical_phase']['abstention_reason']=='INVALID_PHASE_HISTORY'


def test_explicit_experimental_gap_reason_preserved():
    data=result()
    data['reconstruction_history']=dict(status='available',segments=[[0,5,0]],
        abstention_intervals=[[5,10,'NO_EVENT_IDENTIFIABILITY']])
    payload=build_report_payload(data,history_source='experimental')
    assert payload['intervals'][1]['logical_phase']['abstention_reason']=='NO_EVENT_IDENTIFIABILITY'
    assert build_report_payload(data)['intervals'][0]['end']==10


def test_script_injection_escaped_and_no_html_interpolation_of_labels():
    data=result()
    data['schedule']['stream_activity_by_phase'][0]['stream']='</script><script>alert(1)</script>->x'
    page=visualizer.render_html(data)
    assert page.count('</script>')==1 and '\\u003c/script\\u003e' in page
    assert '.innerHTML' not in page


def test_saved_prediction_cli_never_calls_discovery(tmp_path,monkeypatch):
    source=tmp_path/'saved.json';output=tmp_path/'report.html'
    raw=json.dumps(result()).encode();source.write_bytes(raw)
    def forbidden(*a,**k):raise AssertionError('discovery called for saved prediction')
    monkeypatch.setattr(visualizer,'discover_path',forbidden)
    monkeypatch.setattr(sys,'argv',['report',str(source),'--prediction','--output',str(output)])
    assert visualizer.main()==0 and source.read_bytes()==raw and output.exists()


@pytest.mark.parametrize('suffix',['json','zip'])
def test_raw_entrypoint_routes_to_existing_discover_without_parameter_change(tmp_path,monkeypatch,suffix):
    source=tmp_path/('raw.'+suffix);output=tmp_path/'report.html';source.write_text('[]');calls=[]
    def discover(path,**kw):calls.append((path,kw));return result()
    monkeypatch.setattr(visualizer,'discover_path',discover)
    monkeypatch.setattr(sys,'argv',['report',str(source),'--output',str(output),'--dt','1'])
    assert visualizer.main()==0 and calls==[(source,{'dt':1.0})]


@pytest.mark.skipif(not shutil.which('node'),reason='Node required for local JS execution, not browser QA')
def test_javascript_queries_dom_and_controls_agree_with_common_contract():
    data=result();page=visualizer.render_html(data)
    script=re.search(r'<script>(.*?)</script>',page,re.S).group(1)
    times=[-1,0,9.9,10,11,12,19.9,20,40];query=prepare_logical_query(data)
    expected=json.loads(json.dumps([query.at(t).to_dict() for t in times]))
    # Minimal DOM for JS/control tests, NOT a browser render.
    harness=r'''
const vm=require('node:vm'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
class El {constructor(){this.style={};this.value='1';this.children=[];this.textContent='';this.events={};}
append(...a){this.children.push(...a)} replaceChildren(...a){this.children=a}
addEventListener(k,f){this.events[k]=f}}
const elements={};const doc={getElementById:id=>(elements[id]??=new El()),createElement:()=>new El()};
const context=vm.createContext({document:doc,setInterval:()=>1,clearInterval:()=>{}});
vm.runInContext(input.script,context);
const answers=input.times.map(t=>vm.runInContext(`stateAt(${t})`,context));
elements.timeInput.value='11';elements.seek.events.click();
if(!elements.phaseTitle.textContent.includes('UNKNOWN'))throw Error('gap not rendered');
if(elements.lampState.textContent!=='UNKNOWN')throw Error('fabricated physical state');
elements.slider.events.input({target:{value:'12'}});
if(!elements.phaseTitle.textContent.includes('B'))throw Error('slider did not select B');
process.stdout.write(JSON.stringify(answers));
'''
    run=subprocess.run([shutil.which('node'),'-e',harness],input=json.dumps({'script':script,'times':times}),
                       capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)==expected
