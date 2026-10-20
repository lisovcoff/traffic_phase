"""Evaluator-only counterfactuals; never import this module in inference code.

Stretch one independently video-labelled green in a COPY of a real hourly JSON.
This is a signal-extension counterfactual, not a claim that a fire engine was
observed. A smooth monotone clock slows existing vehicles consistently; no
emergency category, signal label or future destination enters online packets.
"""
import os
os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time
import zipfile

from scripts.corpus_validation import ROOT, prepare_worker_environment, save
prepare_worker_environment()
from app.core.intersection_project import read_json, read_model, digest

OUT = ROOT/'evidence/incident_validation_20261020'
RUNTIME = ROOT/'.web_runtime/incident_validation_20261020'
MODEL = '44ae19132cc145758452d13b3eab55d3'
CODE = ('app/core/intersection_online.py', 'app/core/intersection_emissions.py',
        'app/core/intersection_project.py', 'app/core/observed_topology.py')


class GreenStretch:
    def __init__(self, start_ms, end_ms, extension_ms):
        if not start_ms < end_ms or extension_ms <= 0:
            raise ValueError('positive interval and extension required')
        self.start, self.end, self.extra = start_ms, end_ms, extension_ms

    def timestamp(self, millis):
        u = min(1., max(0., (millis-self.start)/(self.end-self.start)))
        return round(millis+self.extra*u*u*(3-2*u))

    def derivative(self, millis):
        u = min(1., max(0., (millis-self.start)/(self.end-self.start)))
        return 1+self.extra*6*u*(1-u)/(self.end-self.start)


def protocol():
    OUT.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    truth_path = ROOT/'evidence/accuracy_recovery_20261019/video_holdout/truth_sealed.json'
    rows = read_json(truth_path)['rows']
    green = next(r for r in rows if r['color']=='GREEN')
    onset = sum(green['clock_mapping']['json_bracket_fixed_clock_ms'])/2
    jobs = read_json(ROOT/'evidence/all_archives_synthetic_20261019/inventory.json')['jobs']
    job = next(j for j in jobs if j['id']=='0091')
    save(OUT/'protocol.json', dict(
        baseline_commit='ca6e734a147c7cab288f23f06cb617d38887aed4',
        model_id=MODEL, code_sha256={p:digest(ROOT/p) for p in CODE}, source=job,
        truth_path=str(truth_path), truth_sha256=digest(truth_path),
        warp=dict(start_ms=onset+15000, end_ms=onset+35000, extension_ms=12000),
        intent='12s longer first N green, subsequent schedule shifted by 12s',
        limitations=['Controlled time-warp of observed trajectories; not a real emergency measurement',
                     'Known development video and conditional vehicle clock, N main only',
                     'No assertion of 95% for all physical lamps or unseen dates'],
        metrics=['known N-green and yellow interior seconds, UNKNOWN counts as wrong',
                 'green persistence in added interval, transition errors, exact unchanged prefix'],
        real_red_not_scored='RED_YELLOW onsets not independently labelled; do not invent exact red intervals',
        video_input_to_engine=False, original_archive_modified=False))


def prepare():
    from scripts.archive_online_packets import prepare as packets
    p = read_json(OUT/'protocol.json'); source = p['source']; warp = GreenStretch(**p['warp'])
    original = RUNTIME/source['member']; changed = RUNTIME/'extended'/source['member']
    changed.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source['path']) as archive:
        info = archive.getinfo(source['member'])
        assert f'{info.CRC:08x}' == source['crc32']
        with original.open('xb') as dst, archive.open(info) as src:
            import shutil
            shutil.copyfileobj(src, dst)
    baseline = packets(original, RUNTIME/'baseline.sqlite3', RUNTIME/'baseline.jsonl')
    save(OUT/'baseline_packets.json', baseline)
    tracks = read_json(original); altered = 0
    for track in tracks:
        ds = track.get('detections') or []
        old = [(d['millis'], d.get('speed')) for d in ds]
        for d in ds:
            ms = d['millis']; d['millis'] = warp.timestamp(ms)
            if isinstance(d.get('speed'), (int,float)):
                d['speed'] /= warp.derivative(ms)
            altered += d['millis'] != ms
        if isinstance(track.get('millis'), (int,float)):
            track['millis'] = warp.timestamp(track['millis'])
        # Preserve vendor aggregate definitions; add only extra elapsed time in
        # each observed segment, according to that segment's original zero speed.
        for field, stopped in [('stay_duration_millis', True), ('move_duration_millis', False)]:
            if isinstance(track.get(field), (int,float)):
                extra = sum(warp.timestamp(b)-warp.timestamp(a)-(b-a)
                            for (a,s),(b,_) in zip(old,old[1:]) if (s==0)==stopped)
                track[field] += extra
        speeds = [d['speed'] for d in ds if isinstance(d.get('speed'), (int,float))]
        if speeds and 'max_speed' in track: track['max_speed'] = max(speeds)
    with changed.open('x', encoding='utf8', newline='\n') as f:
        json.dump(tracks, f, ensure_ascii=False, separators=(',',':'), allow_nan=False)
    del tracks
    modified = packets(changed, RUNTIME/'extended.sqlite3', RUNTIME/'extended.jsonl')
    save(OUT/'extended_packets.json', modified)
    package = RUNTIME/'sverdlovsky_feb27_extended_green.zip'
    with zipfile.ZipFile(package, 'x', zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        z.write(changed, source['member'])
    save(OUT/'input_receipt.json', dict(
        original_member_sha256=digest(original), changed_member_sha256=digest(changed),
        original_archive_crc_checked=True, changed_detections=altered,
        modified_zip=str(package), modified_zip_sha256=digest(package),
        unchanged_source_archive=True, aggregate_duration_update='extra observed segment duration only',
        counterfactual_not_real_emergency=True))
    print('PREPARED', package, flush=True)


def run(name):
    from app.core.intersection_online import CausalIntersection, VERSION
    from app.core import intersection_online_store as store
    from app.api.intersection_online import LivePacket
    p = read_json(OUT/'protocol.json')
    assert all(digest(ROOT/f)==sha for f,sha in p['code_sha256'].items())
    warp = GreenStretch(**p['warp']); modified = name=='extended'
    folder = ROOT/'logs/intersection_projects'/MODEL; model = read_model(folder)
    engine = CausalIntersection(model)
    stream = store.create_stream(folder)['stream_id']; home = store._home(folder,stream)
    manifest = read_json(OUT/(name+'_packets.json')); packets = Path(manifest['output'])
    assert digest(packets)==manifest['sha256']
    assert max(s['observation_end_ms'] for s in model['sessions']) < manifest['first_ms']
    rows = read_json(Path(p['truth_path']))['rows']
    spans = []
    for i in range(3):
        g,y,r = [next(row for row in rows if row['color']==c and row['index']==i)
                 for c in ('GREEN','YELLOW','RED')]
        for color,a,b in [('GREEN',g,y),('YELLOW',y,r)]:
            lo = a['clock_mapping']['json_bracket_fixed_clock_ms'][1]
            hi = b['clock_mapping']['json_bracket_fixed_clock_ms'][0]
            spans.append((warp.timestamp(lo) if modified else lo,
                          warp.timestamp(hi) if modified else hi, color))
    onset = min(s[0] for s in spans)
    first_y = next(s[0] for s in spans if s[2]=='YELLOW')
    extension = (first_y-12000,first_y) if modified else None
    stats = Counter(); previous = None; transitions = []; began = time.monotonic()
    output = RUNTIME/(name+'_issuance.jsonl')
    with sqlite3.connect(home/'stream.sqlite3') as db, packets.open(encoding='utf8') as src, output.open('x',encoding='utf8') as dst:
        for n,line in enumerate(src,1):
            packet = LivePacket.model_validate_json(line).model_dump()
            result = engine.ingest(packet); encoded = store._encode(result)
            payload = store._encode(packet)
            import hashlib
            db.execute('INSERT INTO packets VALUES (?,?,?,?,?)',
                       (packet['sequence'],packet['timestamp_ms'],hashlib.sha256(payload.encode()).hexdigest(),payload,encoded))
            now = result['timestamp_ms']; color = result['heads']['N']['main']['state']
            if color != previous and onset-10000 <= now <= max(s[1] for s in spans)+10000:
                transitions.append(dict(timestamp_ms=now,color=color))
            previous = color
            for lo,hi,expected in spans:
                if lo<now<hi:
                    stats['total'] += 1; stats['correct'] += color==expected
                    stats['unknown'] += color=='UNKNOWN'
                    stats[expected+'_total'] += 1; stats[expected+'_correct'] += color==expected
            if extension and extension[0] <= now < extension[1]:
                stats['added_green_total'] += 1; stats['added_green_correct'] += color=='GREEN'
            dst.write(json.dumps(dict(timestamp_ms=now,sequence=packet['sequence'],heads=result['heads'],
                phase=result['phase_id'],regime=result['regime_id'],evidence_count=result['evidence_count']),separators=(',',':'))+'\n')
            if n%600==0:db.commit();dst.flush();print(name,n,round(time.monotonic()-began,1),flush=True)
        db.commit(); integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
    assert all(digest(ROOT/f)==sha for f,sha in p['code_sha256'].items())
    result = dict(case=name,engine=VERSION,model_id=MODEL,stream_id=stream,
        counts=dict(stats),accuracy_on_labelled_green_yellow=stats['correct']/stats['total'],
        transitions=transitions,packets=n,runtime_s=time.monotonic()-began,sqlite_integrity=integrity,
        accelerated_replay_not_durable_latency=True, issuance_sha256=digest(output),
        url=f'http://127.0.0.1:8017/visualization?project={MODEL}&stream={stream}')
    save(OUT/(name+'_result.json'),result)
    print(json.dumps(result),flush=True)


def compare():
    p = read_json(OUT/'protocol.json'); compared=0
    with (RUNTIME/'baseline_issuance.jsonl').open() as a,(RUNTIME/'extended_issuance.jsonl').open() as b:
        for left,right in zip(a,b):
            if json.loads(left)['timestamp_ms'] > p['warp']['start_ms']: break
            assert left==right, 'unchanged prefix must issue identical results'
            compared+=1
    save(OUT/'prefix_parity.json',dict(exact_packets=compared,passed=True,
        inference_unchanged=True,truth_and_emergency_metadata_in_packets=False))
    print('EXACT_PREFIX',compared,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['seal','prepare','baseline','extended','compare'])
    action=parser.parse_args().action
    if action=='seal': protocol()
    elif action=='prepare': prepare()
    elif action=='compare': compare()
    else: run(action)
