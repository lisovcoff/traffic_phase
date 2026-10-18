"""Run the independent count model on a real JSON/ZIP and save its HTML."""
import argparse
import json
from pathlib import Path

from app.core.count_phase import discover_bundle
from app.core.count_alignment import aligned_event_channels
from app.core.v9.events import load_event_streams,load_tracks
from app.core.v9.source_scope import choose_source,choose_session,input_sessions,attach_input_scope,ScopeChoiceRequired
from app.core.v9.spatial import build_spatial_projection,compact_trajectories
from app.core.v10.estimated_signals import build_estimated_signals
from scripts.v9_spatial_visualizer import render_html


def run(path,out,*,aligned=False,first_scope=False,source_member=None,session_id=None):
    out.mkdir(parents=True,exist_ok=False)
    try:member,sources=choose_source(path,source_member)
    except ScopeChoiceRequired as exc:
        if not first_scope or exc.kind!='source':raise
        member=sorted(exc.choices,key=lambda c:c['source_member'])[0]['source_member']
        member,sources=choose_source(path,member)
    bundle=load_event_streams(path,source_member=member)
    sessions=input_sessions(bundle,member)
    if first_scope and session_id is None and sessions:session_id=sessions[0].metadata['session_id']
    scoped,selected,choices=choose_session(bundle,member,session_id)
    result=discover_bundle(scoped,input_name=str(path),
        observation_builder=aligned_event_channels if aligned else None)
    attach_input_scope(result,member,selected,choices,source_count=len(sources))
    result['estimated_signals']=build_estimated_signals(result,input_name=path.name)
    kwargs={'source_member':member}
    if len(sessions)>1:kwargs.update(start_timestamp_ms=selected['observation_start_ms'],end_timestamp_ms=selected['observation_end_ms'])
    tracks=load_tracks(path,**kwargs)
    projection=build_spatial_projection(tracks)
    base=result['analysis_base_timestamp_ms'];display=result['recording_start_timestamp_ms']
    compact=compact_trajectories(tracks,analysis_base_timestamp_ms=base,
        display_base_timestamp_ms=display,projection=projection)
    page=render_html(result,projection,compact,time_offset_s=(base-display)/1000,
        display_duration_s=result['recording_duration_s']+(base-display)/1000,
        display_base_timestamp_ms=display)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'viewer.html').write_text(page,encoding='utf8')
    print(json.dumps(dict(status='PASS',input=str(path),source_member=member,
        session=selected,other_sources_analysed=False,other_sessions_analysed=False,
        tracks=len(tracks),phase_count=result['schedule']['phase_count'],
        period_s=result['schedule']['period_s'],html=str(out/'viewer.html'),
        interpretation='integration only; no independent lamp truth'),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--aligned',action='store_true');parser.add_argument('--first-scope',action='store_true')
    parser.add_argument('--source-member');parser.add_argument('--session-id')
    args=parser.parse_args()
    run(args.input,args.output,aligned=args.aligned,first_scope=args.first_scope,
        source_member=args.source_member,session_id=args.session_id)
