"""Raw JSON/ZIP -> frozen calibrated model -> shared spatial viewer."""
import hashlib
import json
from pathlib import Path

from app.core.learned_phase import predict_profile
from app.core.v9.events import load_event_streams,load_tracks
from app.core.v9.primitives import infer_period
from app.core.v9.source_scope import choose_source,choose_session,input_sessions,attach_input_scope,ScopeChoiceRequired
from app.core.v9.spatial import build_spatial_projection,compact_trajectories
from app.core.v10.estimated_signals import build_estimated_signals
from scripts.v9_spatial_visualizer import render_html

ROOT=Path(__file__).resolve().parents[2]
SITES={'lenina_sverdlovsky':'Ленина — Свердловский','chicherina_40let':'Чичерина — 40 лет Победы',
       'lenina_entuziastov':'Ленина — Энтузиастов'}


def build_learned_visualization(path,*,model_id,source_member=None,session_id=None,first_scope=False):
    path=Path(path)
    if model_id not in SITES:raise ValueError('unknown calibrated intersection model')
    model_path=ROOT/'config/learned_profiles'/(model_id+'.json')
    model=json.loads(model_path.read_text(encoding='utf8'))
    try:member,sources=choose_source(path,source_member)
    except ScopeChoiceRequired as exc:
        if not first_scope or exc.kind!='source':raise
        member=sorted(exc.choices,key=lambda c:c['source_member'])[0]['source_member']
        member,sources=choose_source(path,member)
    known={'17_':'lenina_sverdlovsky','19_':'chicherina_40let','6_':'lenina_entuziastov'}
    for prefix,site in known.items():
        if Path(member).name.startswith(prefix) and site!=model_id:
            raise ValueError('selected model does not match the known camera source')
    bundle=load_event_streams(path,source_member=member)
    sessions=input_sessions(bundle,member)
    if first_scope and session_id is None:session_id=sessions[0].metadata['session_id']
    scoped,selected,choices=choose_session(bundle,member,session_id)
    period,period_info=infer_period(scoped[1])
    start=selected['observation_start_ms'];end=selected['observation_end_ms']
    result=predict_profile(scoped.temporal_events,model,start_ms=start,end_ms=end,period_s=period)
    result.update(input=str(path),trajectory_count=int(scoped[8]),
        movement_stream_count=len(scoped[0]),period_inference={'period_s':period,**period_info},
        archive={'source_files':[member]},anomaly_detection={'status':'not_evaluated','temporary_phase_deviations':[],'cause':'unknown'})
    result['learned_phase'].update(site_id=model_id,site_name=SITES[model_id],
        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest())
    attach_input_scope(result,member,selected,choices,source_count=len(sources))
    profile='lenina_sverdlovsky' if model_id=='lenina_sverdlovsky' else 'none'
    result['estimated_signals']=build_estimated_signals(result,profile_id=profile)
    kwargs={'source_member':member}
    if len(sessions)>1:kwargs.update(start_timestamp_ms=start,end_timestamp_ms=end)
    tracks=load_tracks(path,**kwargs)
    projection=build_spatial_projection(tracks)
    compact=compact_trajectories(tracks,analysis_base_timestamp_ms=start,
        display_base_timestamp_ms=start,projection=projection)
    page=render_html(result,projection,compact,time_offset_s=0.,display_duration_s=(end-start)/1000,
        display_base_timestamp_ms=start,intersection_profile=profile)
    from html import escape
    banner="<div style='padding:12px;color:#edf2f7;background:#263144'>Обученная модель: "+escape(SITES[model_id])+". Число фаз и временная привязка обучены по отметкам оператора; это оценка, не наблюдение ламп. Источник: "+escape(member)+"; сеанс "+str(selected['session_number'])+" / "+str(len(sessions))+". Остальные источники и сеансы не анализировались.</div>"
    page=page.replace('<body>','<body>'+banner,1)
    return dict(html=page,result=result,physical_plan=result['physical_signal_plan'],projection=projection,
        rendered_trajectory_count=len(compact),trajectory_count=len(tracks))
