"""Read-only evidence admission/budget checks; --seal creates a fresh manifest.

No source video decode, full video rehash, alignment, or phase model call.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
BASE='504103d8b3729287294c83a139c251fe5cf17ccf'


def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main(seal=False):
    plan=read(OUT/'plan.json'); identity=read(OUT/'source_identity_result.json')
    public=read(OUT/'public_video_metadata.json')['resource']
    assert identity['full_hash_match'] and identity['bytes_read']==public['size']==6792283598
    assert identity['local_sha256']==identity['remote_sha256']==public['sha256']
    assert identity['local_md5']==identity['remote_md5']==public['md5']
    assert identity['accepted_clock_transform'] is None
    doc=read(OUT/'supplier_document_review.json')
    assert sha(Path(doc['source']))==doc['source_sha256']
    assert len(doc['paragraphs'])==28 and not doc['docx_edited']
    assert 'Ленина-Энтузиастов 05.10.24.zip' in doc['paragraphs'][19]['text']
    assert any(r['Id']=='rId10' and r['Target']==identity['supplier_public_resource'] for r in doc['external_links'])
    assert sha(OUT/doc['embedded_image']['file'])==doc['embedded_image']['sha256']
    summary=read(OUT/'entry_summary.json');raw_path=ROOT/summary['raw_cache']
    assert raw_path.stat().st_size==summary['entry_bytes']<=plan['max_full_entry_bytes']
    assert sha(raw_path)==summary['entry_sha256'] and summary['full_entry_crc_checked']
    tracks=read(raw_path)
    assert len(tracks)==summary['tracks']==245
    assert sum(len(t['detections']) for t in tracks)==summary['detections']==39215
    frames=[];decode_wall=0
    names=('context_selection.json','coarse_manifest.json','refinement_manifest.json')
    for name in names:
        manifest=read(OUT/name); decode_wall+=manifest['decode_wall_s']
        for r in manifest['frames']:
            path=ROOT/r['native_file'] if 'native_file' in r else OUT/r['file']
            assert sha(path)==r['sha256']
            assert isinstance(r['actual_pts_ticks'],int) and not isinstance(r['actual_pts_ticks'],bool)
            assert abs(r['actual_pts_s']-r['actual_pts_ticks']/90000)<1e-12
            assert r['requested_s']<=r['actual_pts_s']<=r['requested_s']+.2
            assert 'showinfo' in r['command'][r['command'].index('-vf')+1]
            with Image.open(path) as im:
                assert im.size==(2688,1520) if 'native_file' in r else im.width==1024
            frames.append(r)
    assert len(frames)==38 and decode_wall<plan['max_total_decode_wall_seconds']
    assert len(read(OUT/names[0])['frames'])+len(read(OUT/names[1])['frames'])<=plan['max_new_video_context_frames']
    assert len(read(OUT/names[2])['frames'])<=plan['max_new_video_refinement_frames']
    review=read(OUT/'candidate_review.json')
    assert len(review['candidates'])==3 and not review['accepted_associations']
    assert review['confirmed_car_associations']==review['clock_image_fit_calls']==review['paired_metric_denominator']==0
    assert review['accepted_clock_transform'] is review['calibrated_sync_uncertainty_ms'] is review['drift_estimate'] is None
    subset=read(OUT/'candidate_raw_tracks.json')
    for candidate in review['candidates']:
        assert not candidate['use_for_calibration'] and not candidate['identity_independently_verified']
        record=next(t for t in tracks if t['id']==candidate['source_track_id'])
        assert record==next(t for t in subset if t['id']==candidate['source_track_id'])
        canonical=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        assert hashlib.sha256(canonical).hexdigest()==candidate['source_raw_record_canonical_sha256']
    for request in read(OUT/'producer_request_records.json')['records']:
        t=next(t for t in tracks if t['id']==request['track_id'])
        assert t['category_name']=='car'
        d=next(d for d in t['detections'] if d['millis']==request['detection_timestamp_ms'])
        assert {k:d[k] for k in ('x1','y1','x2','y2')}==request['bbox_normalized']
        assert request['requested_video_pts_ticks'] is None
    check=read(OUT/'frame_clock_check.json')
    assert check['status']=='UNAVAILABLE_NO_FRAME_LINKS' and check['row_count']==0 and not check['production_usable']
    protected=subprocess.check_output(['git','diff',BASE,'--name-only','--','app','scripts','tests','config','benchmarks'],cwd=ROOT,text=True)
    assert not protected.strip()
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    for p in OUT.glob('*.py'):compile(p.read_text(encoding='utf-8'),str(p),'exec')
    cache=ROOT/'.web_runtime'/OUT.name
    generated=sum(p.stat().st_size for root in (OUT,cache) for p in root.rglob('*') if p.is_file())
    assert generated+1024*1024<plan['max_new_output_bytes']
    manifest_path=OUT/'manifest.json'
    if seal:
        if manifest_path.exists():raise ValueError('fresh manifest required')
        excluded={'manifest.json','verification.log'}
        files={p.relative_to(OUT).as_posix():sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in excluded}
        manifest_path.write_text(json.dumps(dict(base_commit=BASE,files=files,frames=38,decode_wall_s=decode_wall,
            generated_bytes_before_seal=generated,source_pair=review['source_pair_status'],
            clock_status=review['clock_status'],phase_fitting_runs=0),indent=2)+'\n',encoding='utf-8')
    manifest=read(manifest_path)
    for name,digest in manifest['files'].items():assert sha(OUT/name)==digest,name
    print(json.dumps(dict(source_pair=review['source_pair_status'],clock=review['clock_status'],
        source_tracks=245,source_detections=39215,new_frames_verified=38,decode_wall_s=decode_wall,
        generated_bytes=generated,evidence_files_verified=len(manifest['files']),
        accepted_clock_transform=None,protected_code_and_main_unchanged=True,phase_fitting_runs=0)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seal',action='store_true')
    main(p.parse_args().seal)
