"""Read saved QA outputs, create query expectations; never runs inference."""
from pathlib import Path
import json
import hashlib
from app.core.state_contract import prepare_logical_query
from scripts.v9_spatial_visualizer import render_html

folder=Path('evidence/web_archive_qa_20261016')
fixture=dict(schedule_base_timestamp_ms=6000,analysis_base_timestamp_ms=6000,
    recording_start_timestamp_ms=1000,recording_duration_s=30,
    schedule=dict(phase_names=['A','B'],phase_count=2,period_s=20,
        raw_hsmm_segments=[[0,10,0],[12,20,1]],baseline_segments=[[0,10,0],[10,20,1]],
        stream_activity_by_phase=[{'stream':'N->E','event_probability_by_phase':{'A':.9,'B':.1}}]))
(folder/'gap_counterexample.html').write_text(render_html(fixture,{},[]),encoding='utf-8')
rows=[]
for run in sorted((folder/'server_runs').iterdir()):
    source=run/'v9_result.json'
    result=json.loads(source.read_text(encoding='utf-8'))
    query=prepare_logical_query(result)
    offset=(result['schedule_base_timestamp_ms']-result['recording_start_timestamp_ms'])/1000
    duration=result['recording_duration_s']
    times=[-1,0,10,duration/2,duration,duration+1]
    times=sorted(set(times+[v+offset+d for seg in query.segments for v in seg[:2] for d in [-.01,0,.01]]))
    rows.append(dict(name=run.name,url='http://127.0.0.1:8017/qa/web_archive_qa_20261016/server_runs/'+run.name+'/viewer.html',
        points=[dict(t=t,expected=query.at(t-offset).estimated_state) for t in times],
        source_prediction_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        phase_count=result['schedule']['phase_count'],period_s=result['schedule']['period_s'],
        event_count=result['event_count'],trajectory_count=result['trajectory_count']))
query=prepare_logical_query(fixture)
rows.append(dict(name='gap_counterexample',url='http://127.0.0.1:8017/qa/web_archive_qa_20261016/gap_counterexample.html',
    points=[dict(t=t,expected=query.at(t-5).estimated_state) for t in [-1,0,4.9,5,14.9,15,16,17,24.9,25,31]]))
(folder/'browser_expectations.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
print([(r['name'],len(r['points'])) for r in rows])
