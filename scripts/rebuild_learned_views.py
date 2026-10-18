"""Rerender raw ZIP results with current UI; no fitting or trajectory reread."""
import base64
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import re
from app.core.v10.estimated_signals import build_estimated_signals
from app.core.learned_visualization import SITES
from scripts.v9_spatial_visualizer import render_html

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'deliverables/traffic_phase_learned_20261018'


def main():
    OUT.mkdir(exist_ok=False)
    manifest=[]
    for index,site in [(1,'lenina_sverdlovsky'),(2,'lenina_entuziastov')]:
        source=ROOT/'evidence/learned_archive_integration_20261018'/f'archive_{index}'
        raw=(source/'result.json').read_bytes();result=json.loads(raw)
        old_names=result['schedule']['phase_names']
        new_names=['PHASE_'+label for label in result['learned_phase']['phase_labels']]
        for row in result['schedule']['stream_activity_by_phase']:
            values=row['event_probability_by_phase']
            row['event_probability_by_phase']={new:values[old] for new,old in zip(new_names,old_names)}
        result['schedule']['phase_names']=new_names
        result['anomaly_detection']['status']='not_evaluated'
        profile='lenina_sverdlovsky' if index==1 else 'none'
        result['estimated_signals']=build_estimated_signals(result,profile_id=profile)
        old_html=(source/'viewer.html').read_text(encoding='utf8')
        packed=json.loads(re.search(r'^const PACKED_DATA = (.*);$',old_html,re.M).group(1))
        tracks=json.loads(gzip.decompress(base64.b64decode(packed)))
        projection=json.loads((source/'projection.json').read_text(encoding='utf8'))
        page=render_html(result,projection,tracks,time_offset_s=0.,
            display_duration_s=result['recording_duration_s'],
            display_base_timestamp_ms=result['recording_start_timestamp_ms'],intersection_profile=profile)
        scope=result['input_scope']
        banner="<div style='padding:12px;color:#edf2f7;background:#263144'>Обученная модель: "+escape(SITES[site])+". Число фаз и временная привязка обучены по отметкам оператора; это оценка, не наблюдение ламп. Источник: "+escape(scope['source_member'])+"; выбран один сеанс. Остальные JSON архива не анализировались.</div>"
        page=page.replace('<body>','<body>'+banner,1)
        path=OUT/(site+'.html')
        with path.open('x',encoding='utf8',newline='\n') as stream:stream.write(page)
        assert (source/'result.json').read_bytes()==raw
        manifest.append(dict(site=site,file=path.name,source_result_sha256=hashlib.sha256(raw).hexdigest(),
            file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),phase_fit_runs=0,
            phase_timestamps_unchanged=True,semantic_phase_names_now_match_training_labels=True))
    with (OUT/'viewers.json').open('x',encoding='utf8',newline='\n') as stream:json.dump(manifest,stream,indent=2)
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
