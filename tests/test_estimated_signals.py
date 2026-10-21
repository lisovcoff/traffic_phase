import json
from pathlib import Path

from app.core.v10.estimated_signals import build_estimated_signals


def prediction():
    groups = [{'E->W','W->E'},{'N->S','N->E','E->N'},{'N->S','S->N'}]
    names = ['x','y','z']
    return dict(schedule_base_timestamp_ms=1000, recording_start_timestamp_ms=0,
        schedule=dict(phase_count=3,phase_names=names,period_s=30,
            raw_hsmm_segments=[[0,10,0],[10,20,1],[20,30,2]],
            stream_activity_by_phase=[dict(stream=movement,event_probability_by_phase={
                name:.8 if movement in group else .01 for name,group in zip(names,groups)})
                for movement in sorted(set.union(*groups)|{'W->N'})]))


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


def test_lenina_reference_plan_has_no_w_or_s_additional_section():
    path=Path(__file__).parent/'fixtures/lenina_physical_signal_plan.json'
    plan=json.loads(path.read_text(encoding='utf-8'))
    additional={m for row in plan['stages'] for m in row['additional_movements']}
    assert additional=={'N->E','E->N'}
    groups={row['name']:set(row['active_movements']) for row in plan['stages']}
    assert groups=={'A':{'N->S','S->N'},'B':{'E->W','W->E'},'C':{'N->S','N->E','E->N'}}
