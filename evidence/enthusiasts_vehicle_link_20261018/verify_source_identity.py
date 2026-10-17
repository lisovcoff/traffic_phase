"""Read-only complete local media hash against supplier-linked public metadata."""
import hashlib
import json
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
plan=json.loads((OUT/'source_identity_plan.json').read_text(encoding='utf-8'))
public=json.loads((OUT/'public_video_metadata.json').read_text(encoding='utf-8'))['resource']
source=json.loads((ROOT/'evidence/enthusiasts_video_20261017/source.json').read_text(encoding='utf-8'))
video=Path(source['path'])
before=video.stat()
if before.st_size!=public['size'] or before.st_size>plan['max_local_video_hash_bytes']:
    raise ValueError('source size mismatch or hash byte budget exceeded')
result_path=OUT/'source_identity_result.json'
if result_path.exists():raise ValueError('fresh output required')
sha=hashlib.sha256();md5=hashlib.md5(usedforsecurity=False);count=0;start=time.monotonic()
with video.open('rb') as f:
    while chunk:=f.read(8*1024*1024):
        if time.monotonic()-start>plan['max_local_video_hash_wall_seconds']:
            raise ValueError('full media hash wall budget exceeded')
        count+=len(chunk);sha.update(chunk);md5.update(chunk)
after=video.stat()
if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
    raise ValueError('source changed during hash')
result=dict(local_file=str(video),remote_file_name=public['name'],bytes_read=count,
    local_sha256=sha.hexdigest(),remote_sha256=public['sha256'],local_md5=md5.hexdigest(),remote_md5=public['md5'],
    full_hash_match=(sha.hexdigest()==public['sha256'] and md5.hexdigest()==public['md5']),
    supplier_archive_reference='Ленина-Энтузиастов 05.10.24.zip',supplier_paragraph_index=19,
    supplier_public_resource=plan['public_resource'],runtime_s=time.monotonic()-start,
    source_pair_provenance='supplier_document_link_plus_exact_media_byte_identity',
    frame_detection_time_link='UNVERIFIED',accepted_clock_transform=None,phase_fitting_runs=0)
result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
if not result['full_hash_match']:raise ValueError('local media does not match supplier-linked file')
