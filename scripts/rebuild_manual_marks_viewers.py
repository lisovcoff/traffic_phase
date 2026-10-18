"""Build reviewable viewers from sealed predictions, without running inference."""
import base64
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re

from app.core.v9.spatial import build_spatial_projection, compact_trajectories
from app.core.v9.events import load_tracks
from app.core.v10.estimated_signals import build_estimated_signals
from scripts.v9_spatial_visualizer import render_html

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.web_runtime/manual_marks_20261018/viewers'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUT)
    OUT=parser.parse_args().output.resolve()
    OUT.mkdir(parents=True,exist_ok=False)
    manifest={}
    for name,run in [('real','20261018_072637_838919_-_27.02.25'),
                     ('synthetic','20261018_072827_826749_synthetic_spatial_demo'),
                     ('manual17',None)]:
        if run:
            folder=ROOT/'logs'/run
            source=folder/'v9_result.json'
            old=(folder/'viewer.html').read_text(encoding='utf-8')
            def const(key):
                return json.loads(re.search(r'^const '+key+r' = (.*);$',old,re.M).group(1))
            projection=const('PROJECTION')
            compact=json.loads(gzip.decompress(base64.b64decode(const('PACKED_DATA'))))
            physical=const('PHYSICAL')
            kwargs={k:physical[k] for k in ('time_offset_s','display_duration_s','display_base_timestamp_ms') if k in physical}
            result=read(source)
        else:
            source=ROOT/'benchmarks/manual_marks_20261018_baseline/predictions/17_2025_2_19_10_v9.json'
            result=read(source)
            row=read(ROOT/'benchmarks/manual_marks_20261018_baseline/baseline_metrics.json')['rows'][0]
            tracks=load_tracks(Path(row['source_path']))
            projection=build_spatial_projection(tracks)
            analysis=result['analysis_base_timestamp_ms']
            display=result['recording_start_timestamp_ms']
            compact=compact_trajectories(tracks,analysis_base_timestamp_ms=analysis,
                display_base_timestamp_ms=display,projection=projection)
            kwargs=dict(time_offset_s=(analysis-display)/1000,
                display_duration_s=result['recording_duration_s'],display_base_timestamp_ms=display)
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        profile='lenina_sverdlovsky' if name in {'real','manual17'} else 'none'
        result['estimated_signals']=build_estimated_signals(result,profile_id=profile)
        page=render_html(result,projection,compact,intersection_profile=profile,**kwargs)
        with (OUT/(name+'_viewer.html')).open('x',encoding='utf-8') as stream:
            stream.write(page)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
        manifest[name]=dict(source=str(source.relative_to(ROOT)),source_sha256=digest,
            profile=profile,states=[s['name'] for s in result['estimated_signals']['states']],
            tracks=len(compact),phase_inference_runs=0,source_unchanged=True,
            page_sha256=hashlib.sha256((OUT/(name+'_viewer.html')).read_bytes()).hexdigest())
        print(name,manifest[name],flush=True)
    with (OUT/'rebuild.json').open('x',encoding='utf-8') as stream:
        json.dump(manifest,stream,indent=2)


if __name__=='__main__':
    main()
