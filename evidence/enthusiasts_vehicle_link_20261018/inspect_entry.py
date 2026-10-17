"""One bounded raw ZIP member inspection; no event extraction or phase model."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CACHE = ROOT / '.web_runtime' / OUT.name


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    source = json.loads((ROOT / 'evidence/enthusiasts_video_20261017/source.json').read_text(encoding='utf-8'))
    plan = json.loads((OUT / 'plan.json').read_text(encoding='utf-8'))
    archive = (ROOT / source['archive_path']).resolve()
    with ZipFile(archive) as z:
        info = z.getinfo(plan['new_archive_entry_full_scan'])
        if info.file_size > plan['max_full_entry_bytes']:
            raise ValueError('entry exceeds frozen byte budget')
        raw = z.read(info)  # Complete member read also checks ZIP CRC.
    tracks = json.loads(raw)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / 'first_entry.json'
    if cached.exists():
        raise ValueError('fresh cache required; do not overwrite prior scan')
    cached.write_bytes(raw)
    ds = [d for t in tracks for d in t.get('detections', [])]
    times = [d['millis'] for d in ds]
    categories = Counter(t.get('category_name') for t in tracks)
    summaries = []
    for index, t in enumerate(tracks):
        dets = t.get('detections', [])
        summaries.append(dict(source_index=index, id=t['id'], category=t.get('category_name'),
            movement=[t.get('zone_in'), t.get('zone_out')], detections=len(dets),
            first_ms=dets[0]['millis'] if dets else None, last_ms=dets[-1]['millis'] if dets else None,
            first_bbox=[dets[0][k] for k in ('x1','y1','x2','y2')] if dets else None,
            last_bbox=[dets[-1][k] for k in ('x1','y1','x2','y2')] if dets else None))
    report = dict(entry=info.filename, entry_bytes=len(raw), entry_sha256=digest(raw),
        zip_crc32=f'{info.CRC:08x}', full_entry_crc_checked=True, input_scan_count=1,
        raw_cache=str(cached.relative_to(ROOT)), tracks=len(tracks), detections=len(ds),
        categories=dict(categories), detection_extent_ms=[min(times),max(times)],
        detection_extent_local_assuming_unix_ms=[datetime.fromtimestamp(x/1000, timezone(timedelta(hours=5))).isoformat() for x in (min(times),max(times))],
        bbox_coordinate_extent={k:[min(d[k] for d in ds),max(d[k] for d in ds)] for k in ('x1','y1','x2','y2')},
        explicit_frame_or_pts_keys=sorted({k for d in ds for k in d if any(s in k.lower() for s in ('frame','pts','exposure'))}),
        inference_runs=0, sync='UNVERIFIED', source_order_not_assumed_chronological=True)
    save(OUT/'entry_summary.json', report)
    save(OUT/'track_inventory.json', summaries)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Distinctive non-car records:', json.dumps([s for s in summaries if s['category']!='car'], ensure_ascii=False))


if __name__ == '__main__':
    main()
