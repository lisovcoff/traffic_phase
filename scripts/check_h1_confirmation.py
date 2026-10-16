"""Check saved frame/anchor provenance; no new frames, fitting or phase labels."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.experimental.h1_confirmation import assess_confirmation


def main():
    folder=ROOT/'evidence/h1_confirmation_20261016'
    paths=dict(readouts='evidence/h1_confirmation_20261016/overlay_readouts.json',
        frames='evidence/local_vehicle_registration_20261015/new_frames.json',
        model='evidence/local_vehicle_registration_20261015/local_model.json',
        validation='evidence/local_vehicle_registration_20261015/validation_result.json',
        mapping='evidence/video_calibration_intake_20261015/h1_operator_mapping.json',
        raw_anchors='evidence/seven_restart_review_20261015/selected_raw_tracks.json',
        timestamp_definitions='evidence/h1_confirmation_20261016/timestamp_definition_excerpt.json')
    sources={};seals={};total=0
    for key,name in paths.items():
        path=ROOT/name
        if path.stat().st_size>4*1024*1024:raise ValueError('INPUT_BYTE_BUDGET_EXCEEDED')
        raw=path.read_bytes();total+=len(raw)
        if total>8*1024*1024:raise ValueError('TOTAL_INPUT_BYTE_BUDGET_EXCEEDED')
        sources[key]=json.loads(raw)
        seals[key]=dict(path=name,sha256_lf=hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest())
    if sources['model'].get('source_sample_sha256')!=seals['raw_anchors']['sha256_lf']:
        raise ValueError('RAW_ANCHORS_NOT_FROM_SAVED_MODEL_SOURCE')
    definition_path=(ROOT/sources['timestamp_definitions']['source_path']).resolve()
    if not definition_path.is_relative_to(ROOT.parent) or definition_path.stat().st_size>1024*1024:
        raise ValueError('SUPPLIER_DEFINITION_PATH_OR_BYTE_BUDGET')
    definition_raw=definition_path.read_bytes();total+=len(definition_raw)
    if hashlib.sha256(definition_raw).hexdigest()!=sources['timestamp_definitions']['source_sha256']:
        raise ValueError('SUPPLIER_DEFINITION_HASH_MISMATCH')
    verified=[];image_bytes=0
    for row in sources['readouts']:
        path=(ROOT/row['source_path']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('LOCAL_FRAME_REQUIRED')
        if image_bytes+path.stat().st_size>32*1024*1024:raise ValueError('FRAME_BYTE_BUDGET_EXCEEDED')
        raw=path.read_bytes();image_bytes+=len(raw)
        digest=hashlib.sha256(raw).hexdigest()
        if digest!=row['frame_sha256']:raise ValueError('SOURCE_FRAME_HASH_MISMATCH')
        verified.append(dict(path=row['source_path'],sha256=digest))
    raw_zones={str(row['id']):dict(zone_in=row.get('zone_in'),zone_out=row.get('zone_out')) for row in sources['raw_anchors']}
    result=assess_confirmation(sources['readouts'],sources['frames'],sources['model'],sources['validation'],sources['mapping'],raw_zones,sources['timestamp_definitions'])
    result['source_catalog']=seals
    def write(name,value):
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    write('confirmation.json',result)
    write('manifest.json',dict(base_sha='7bfa6361dd20a16c460b5a6f6300397cf19b3174',source_seals=seals,
        verified_frames=verified,input_bytes_read=total,image_bytes_read=image_bytes,
        fit_calls=0,new_video_frames=0,large_archive_reads=0,
        confirmation_sha256=hashlib.sha256((folder/'confirmation.json').read_bytes()).hexdigest(),
        code_sha256_lf={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in
                       ['app/experimental/h1_confirmation.py','scripts/check_h1_confirmation.py']}))
    print(json.dumps(dict(overlay_frames=len(verified),withheld_track_anchors=len(result['local_raw_zone_anchors']),
        clock_certified=False,raw_mapping_independently_certified=False,fit_calls=0)))


if __name__=='__main__':main()
