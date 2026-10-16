"""Read-only preservation check; no event extraction or model fitting."""
from contextlib import closing
from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from app.core.v9.events import _iter_json_records, _iter_source_records
from app.core.preprocessing import iter_trajectory_payload_stream

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = '1a4e0c656baf004f09a6632abf91922772e6b2b4'


def seal(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


rows = []
for name, reader in [('v9', _iter_json_records), ('legacy_stream', iter_trajectory_payload_stream)]:
    for payload in ['[]', '[]\n', '[{}]', '[{},]]', '[],{}]', '[{},]']:
        try:
            list(reader(BytesIO(payload.encode()), chunk_size=2))
            status, error = 'accepted', None
        except ValueError as exc:
            status, error = 'rejected', str(exc)
        rows.append(dict(reader=name, payload=payload, status=status, error=error))
(OUT/'after.json').write_text(json.dumps(rows, indent=2)+'\n', encoding='utf-8')

source = ROOT/'evidence/seven_restart_review_20261015/selected_raw_tracks.json'
if source.stat().st_size > 2*1024*1024:
    raise ValueError('SOURCE_BYTE_BUDGET')
raw = source.read_bytes()
expected = json.loads(raw)
parsed = list(_iter_json_records(BytesIO(raw)))
assert parsed == expected
with TemporaryDirectory(dir=ROOT/'.web_runtime/tmp', prefix='strict_json_invariant_') as tmp:
    path = Path(tmp)/'raw.zip'
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('nested/raw.json', raw)
    zipped = []
    with closing(_iter_source_records(path)) as sources:
        for _, records in sources:
            zipped.extend(records)
    assert zipped == expected

# Reuse the small historical seals instead of parsing the 5-12MB predictions.
seal_path = ROOT/'evidence/offline_product_html_20261016/manifest.json'
seal_bytes = seal_path.read_bytes()
assert seal_bytes == subprocess.check_output(
    ['git', 'show', f'{BASE}:{seal_path.relative_to(ROOT).as_posix()}'], cwd=ROOT)
predictions = []
for saved in json.loads(seal_bytes)['runs']:
    path = ROOT/saved['input']
    subprocess.run(['git', 'diff', '--exit-code', BASE, '--', saved['input']], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    predictions.append(dict(path=saved['input'], size_bytes=path.stat().st_size,
                            historical_sha256=saved['input_sha256'],
                            phase_count=saved['phase_count'], period_s=saved['period_s'],
                            invariant_sha256=saved['invariant_sha256'],
                            verification='Git unchanged vs base; historical seals reused, JSON not reparsed'))
assert len(predictions) == 3
assert subprocess.check_output(['git','rev-parse','main'], cwd=ROOT, text=True).strip() == 'a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
result = dict(base_sha=BASE, source=source.relative_to(ROOT).as_posix(),
              source_bytes=len(raw), source_sha256=hashlib.sha256(raw).hexdigest(),
              tracks=len(parsed), detections=sum(len(r['detections']) for r in parsed),
              stdlib_json_equal=True, zip_records_equal=True, parsed_records_sha256=seal(parsed),
              saved_predictions=predictions, fitting_calls=0, benchmark_runs=0, event_extractions=0,
              main_unchanged=True)
(OUT/'input_invariants.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print(json.dumps(result, indent=2))
