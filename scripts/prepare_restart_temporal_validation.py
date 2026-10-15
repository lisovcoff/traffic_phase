"""One new-hour-entry scan and frozen event-only inference, before video review."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.experimental.temporal_validation_sample import select_review_windows
from app.experimental.restart_localization import localize_restart
from app.core.v9.vehicle_evidence import extract_vehicle_evidence,select_permission_events

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/restart_multicycle_validation_20261015'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name,value):
    path=OUT/name
    with path.open('x',encoding='utf8') as f:
        json.dump(value,f,indent=2,ensure_ascii=False,allow_nan=False)
    return sha(path)


def main():
    if (OUT/'scan_manifest.json').exists():
        raise ValueError('FRESH_OUTPUT_REQUIRED_NO_REPEAT_SCAN')
    plan=json.loads((OUT/'plan.json').read_text(encoding='utf8'))
    assert sha(OUT/'plan.json')==(OUT/'plan.sha256').read_text().strip()
    for name,digest in plan['frozen_code_canonical_lf_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest,name
    exclusions=json.loads((OUT/'exclusion_registry.json').read_text())
    assert sha(OUT/'exclusion_registry.json')==plan['exclusion_registry_sha256']
    resolution=json.loads((OUT/'archive_path_resolution.json').read_text(encoding='utf8'))
    assert resolution['declared_path']==plan['archive']['path']
    archive_path=Path(resolution['resolved_path'])
    assert archive_path.stat().st_size==resolution['archive_bytes']
    with ZipFile(archive_path) as archive:
        info=archive.getinfo(plan['archive']['entry'])
        assert info.file_size==plan['archive']['entry_bytes']
        assert f'{info.CRC:08x}'==plan['archive']['crc32']
        with archive.open(info) as stream:
            records,scan=select_review_windows(stream,plan['windows'],set(exclusions['excluded_ids']),
                max_bytes=plan['limits']['entry_bytes'],max_seconds=plan['limits']['scan_seconds'],
                max_tracks=plan['limits']['raw_tracks'],max_output_bytes=plan['limits']['raw_output_bytes'])
    assert scan['complete_entry_sha256']==plan['archive']['complete_entry_sha256']
    scan.update(archive_entry=plan['archive']['entry'],entries_decoded=[plan['archive']['entry']],
                lineage=[r['lineage'] for r in records])
    save('scan_manifest.json',scan)
    start=time.perf_counter();cohorts=[];selected_tracks=[];outputs=[]
    all_stats=[]
    for i,window in enumerate(plan['windows']):
        entries=[r for r in records if r['lineage']['window_indices']==[i]]
        events=[]
        for row in entries:
            ev,stats=extract_vehicle_evidence(row['record'])
            events.extend(ev);all_stats.append(dict(track_id=row['record']['id'],stats=stats))
        selected,methods=select_permission_events(events)
        a,b=window['json_range_ms']
        eligible=sorted([e for e in selected if e.event_type=='RELEASE' and a<=e.timestamp_ms<b],
                        key=lambda e:(e.timestamp_ms,str(e.source_track_id)))
        chosen=eligible[:plan['limits']['cohort_per_window']]
        cohorts.append(dict(window=window['name'],candidate_records=len(entries),
            event_counts={kind:sum(e.event_type==kind for e in events)
                          for kind in sorted({e.event_type for e in events})},selected_methods=methods,
            eligible=[e.to_dict() for e in eligible],chosen_track_ids=[e.source_track_id for e in chosen],
            budget_excluded_track_ids=[e.source_track_id for e in eligible[len(chosen):]],
            selection='first4 chronological existing permission RELEASEs; before any video review'))
        for event in chosen:
            row=next(r for r in entries if r['record']['id']==event.source_track_id)
            selected_tracks.append(dict(window=window['name'],**row))
            outputs.append(dict(window=window['name'],track_id=event.source_track_id,
                                result=localize_restart(row['record'],event)))
    save('cohort_manifest.json',cohorts)
    save('selected_raw_tracks.json',selected_tracks)
    save('extraction_stats.json',all_stats)
    save('frozen_event_outputs.json',dict(rows=outputs,runtime_s=time.perf_counter()-start,
        camera_clock_fits=0,phase_fits=0,production_default_changed=False))
    save('output_seal.json',dict(plan_sha256=sha(OUT/'plan.json'),
        input_sha256=sha(OUT/'selected_raw_tracks.json'),cohort_sha256=sha(OUT/'cohort_manifest.json'),
        output_sha256=sha(OUT/'frozen_event_outputs.json'),
        annotations_or_video_loaded=False,entry_scans=1))
    print('Complete entry scan',scan['input_bytes_read'],'bytes',round(scan['runtime_s'],3),'s')
    for row in cohorts:
        print('Block',row['window'],'eligible',len(row['eligible']),'chosen',row['chosen_track_ids'],
              'budget excluded',len(row['budget_excluded_track_ids']))
    print('All event outputs sealed BEFORE video sampling/review; no values tuned')


if __name__=='__main__':
    main()
