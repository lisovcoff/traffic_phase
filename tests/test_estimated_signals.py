from copy import deepcopy
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess

from app.core.v10.estimated_signals import build_estimated_signals, resolve_profile


def prediction():
    groups = [{'E->W','W->E'},{'N->S','N->E','E->N'},{'N->S','S->N'}]
    names = ['x','y','z']
    return dict(schedule_base_timestamp_ms=1000, recording_start_timestamp_ms=0,
        schedule=dict(phase_count=3,phase_names=names,period_s=30,
            raw_hsmm_segments=[[0,10,0],[10,20,1],[20,30,2]],
            stream_activity_by_phase=[dict(stream=movement,event_probability_by_phase={
                name:.8 if movement in group else .01 for name,group in zip(names,groups)})
                for movement in sorted(set.union(*groups)|{'W->N'})]))


def test_confirmed_hardware_has_exactly_n_e_arrows_in_every_operating_state():
    value=prediction();before=deepcopy(value)
    # A permissive/uncontrolled turn must not manufacture another hardware arrow.
    value['schedule']['stream_activity_by_phase'][-1]['event_probability_by_phase']={'x':.99,'y':.01,'z':.01}
    result=build_estimated_signals(value,profile_id='lenina_sverdlovsky')
    assert result['available'] and result['operating_phase_count']==3
    for state in result['states']:
        assert state['heads']['W']['arrows']==state['heads']['S']['arrows']==[]
        assert [v['movement'] for v in state['heads']['N']['arrows']]==['N->E']
        assert [v['movement'] for v in state['heads']['E']['arrows']]==['E->N']
    turn=next(row for row in result['states'] if row['name']=='N_E_ARROW')
    assert turn['heads']['N']['main']['state']=='GREEN'
    assert turn['heads']['E']['main']['state']=='RED'
    assert turn['heads']['N']['arrows'][0]['state']==turn['heads']['E']['arrows'][0]['state']=='GREEN'
    assert result['observed_physical_state']=='UNKNOWN' and result['marks_used'] is False
    assert value['schedule']['raw_hsmm_segments']==before['schedule']['raw_hsmm_segments']


def test_catalog_assignment_is_invariant_to_anonymous_names_and_indices():
    original=prediction()
    for perm in itertools.permutations(range(3)):
        value=deepcopy(original)
        value['schedule']['phase_names']=[original['schedule']['phase_names'][i] for i in perm]
        for row in value['schedule']['raw_hsmm_segments']:
            row[2]=perm.index(row[2])
        result=build_estimated_signals(value,profile_id='lenina_sverdlovsky')
        assert [result['operating_states'][row[2]]['name'] for row in result['operating_segments']]==['EW','N_E_ARROW','NS']


def test_no_discriminating_evidence_does_not_force_a_catalog_answer():
    value=prediction()
    for row in value['schedule']['stream_activity_by_phase']:
        row['event_probability_by_phase']={name:.01 for name in ['x','y','z']}
    result=build_estimated_signals(value,profile_id='lenina_sverdlovsky')
    assert not result['available'] and not result['segments']


def test_macro_resolution_merges_equal_configurations_but_preserves_gaps():
    value=prediction()
    value['physical_signal_plan']=dict(enabled=True,
        topology={'N':{'main':'N->S','arrows':[]},'S':{'main':'S->N','arrows':[]}},
        phases=[{'name':'NS','green_movements':['N->S','S->N']}],
        mapping={'x':'NS','y':'NS','z':'NS'})
    value['schedule']['raw_hsmm_segments']=[[0,10,0],[10,20,1],[22,30,2]]
    result=build_estimated_signals(value,profile_id='none')
    assert result['operating_phase_count']==1
    assert result['segments']==[[0.,20.,0],[22.,30.,0]]
    assert value['schedule']['phase_count']==3


def test_topology_alone_does_not_invent_a_missing_operating_phase():
    value=prediction();value['schedule']['phase_count']=2
    value['schedule']['phase_names']=['x','z']
    value['schedule']['raw_hsmm_segments']=[[0,10,0],[10,20,1]]
    for row in value['schedule']['stream_activity_by_phase']:
        row['event_probability_by_phase'].pop('y')
    result=build_estimated_signals(value,profile_id='lenina_sverdlovsky')
    assert result['operating_phase_count']==2
    assert 'N_E_ARROW' in result['unrepresented_configured_groups']


def test_profile_identity_is_explicit_and_does_not_apply_to_other_sites():
    assert resolve_profile('Ленина-Свердловский 27.02.25.zip')[0]=='lenina_sverdlovsky'
    assert resolve_profile('17_2025_2_19_10.json')[0]=='lenina_sverdlovsky'
    assert resolve_profile('19_2025_2_24_16.json')[0] is None
    assert resolve_profile('anything.zip','none')[0] is None


def test_lenina_reference_plan_has_no_w_or_s_additional_section():
    path=Path(__file__).parent/'fixtures/lenina_physical_signal_plan.json'
    plan=json.loads(path.read_text(encoding='utf-8'))
    additional={m for row in plan['stages'] for m in row['additional_movements']}
    assert additional=={'N->E','E->N'}
    groups={row['name']:set(row['active_movements']) for row in plan['stages']}
    assert groups=={'A':{'N->S','S->N'},'B':{'E->W','W->E'},'C':{'N->S','N->E','E->N'}}


def test_actual_viewer_js_keeps_main_and_arrows_distinct_and_never_wraps_history():
    from scripts.v9_spatial_visualizer import render_html
    if not shutil.which('node'):
        import pytest
        pytest.skip('Node required for actual viewer JS contract')
    page=render_html(prediction(),{},[],intersection_profile='lenina_sverdlovsky')
    script=re.search(r'<script>(.*?)</script>',page,re.S).group(1).split('window.addEventListener("resize",resizeCanvas);')[0]
    harness='''const vm=require('node:vm'),fs=require('node:fs'),script=fs.readFileSync(0,'utf8');
const c={document:{getElementById:()=>({value:'signals'})}};vm.createContext(c);vm.runInContext(script,c);
process.stdout.write(JSON.stringify([6,16,26,31].map(t=>vm.runInContext(`({estimate:estimatedSnapshot(${t}),physical:signalSnapshot(${t})})`,c))));'''
    run=subprocess.run([shutil.which('node'),'-e',harness],input=script,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert run.returncode==0,run.stderr
    ew,turn,ns,outside=json.loads(run.stdout)
    assert ew['estimate']['phaseName']=='EW'
    assert turn['estimate']['phaseName']=='N_E_ARROW'
    assert ns['estimate']['phaseName']=='NS'
    assert ew['estimate']['heads']['N']['arrows'][0]['state']=='OFF'
    assert turn['estimate']['heads']['N']['arrows'][0]['state']=='GREEN'
    assert turn['estimate']['heads']['E']['main']['state']=='RED'
    assert ns['estimate']['heads']['N']['main']['state']=='GREEN'
    assert outside['estimate']['phaseName']=='UNKNOWN'
    for row in (ew,turn,ns,outside):
        assert all(head['main']['state']=='UNKNOWN' for head in row['physical']['heads'].values())
        assert len(row['physical']['heads']['N']['arrows'])==1
        assert row['physical']['heads']['S']['arrows']==row['physical']['heads']['W']['arrows']==[]


def test_explicit_viewer_profile_overrides_cached_automatic_projection():
    from scripts.v9_spatial_visualizer import render_html
    value=prediction()
    value['estimated_signals']={'available':False,'reason':'STALE_GENERIC_PROPOSAL'}
    page=render_html(value,{},[],intersection_profile='lenina_sverdlovsky')
    embedded=json.loads(re.search(r'^const ESTIMATED_SIGNALS = (.*);$',page,re.M).group(1))
    assert embedded['hardware_confirmed'] and embedded['available']
    assert embedded['profile_id']=='lenina_sverdlovsky'
