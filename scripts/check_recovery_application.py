"""Actual multipart upload of byte-identical real ZIP members to the default API."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import zipfile

from scripts.corpus_validation import ROOT, prepare_worker_environment, save, source_stream
prepare_worker_environment()
from scripts.accuracy_recovery import OUT, RUNTIME


def check(key):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import visualization as api
    from scripts.verify_recovery_release import prediction_path
    jobs = json.loads((ROOT/'evidence/all_archives_synthetic_20261019/inventory.json').read_text(encoding='utf8'))['jobs']
    job = next(j for j in jobs if 'real_'+j['id'] == key)
    folder = OUT/'application_checks'/job['site']
    folder.mkdir(parents=True, exist_ok=False)
    bundle = RUNTIME/'application_inputs'/(job['site']+'.zip')
    bundle.parent.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    with source_stream(job) as raw, zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        with archive.open(job['source_name'], 'w') as sink:
            while chunk := raw.read(4*1024*1024):
                sink.write(chunk)
        digest, size = raw.hash.hexdigest(), raw.bytes
    baseline = json.loads((ROOT/'evidence/all_archives_synthetic_20261019/ingest'/(job['id']+'.json')).read_text(encoding='utf8'))
    assert digest == baseline['sha256'] and size == baseline['bytes_read']
    save(folder/'input_receipt.json', dict(job=job, derived_zip=str(bundle.relative_to(ROOT)),
        source_bytes_identical=True, source_sha256=digest, bytes=size,
        zip_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest()))
    api.LOG_ROOT = folder/'logs'
    with TestClient(app) as client, bundle.open('rb') as stream:
        response = client.post('/visualization/analyze', files={'file':(bundle.name, stream, 'application/zip')},
                               data={'intersection_profile':'lenina_sverdlovsky' if job['site']=='lenina_sverdlovsky' else 'none'})
    assert response.status_code == 200, response.text[:3000]
    (folder/'viewer.html').write_bytes(response.content)
    run = Path(response.headers['X-Traffic-Phase-Logs'])
    result = json.loads((run/'v9_result.json').read_text(encoding='utf8'))
    with gzip.open(prediction_path(key), 'rt', encoding='utf8') as stream:
        expected = json.load(stream)
    a, b = result['schedule'].copy(), expected['schedule'].copy()
    a.pop('model'); b.pop('model')
    assert a == b, 'cold default API differs from sealed candidate'
    assert result['recovery_model']['version'] == 'trajectory_recovery_v1'
    assert result['recovery_model']['reference_video_bias_applied'] is False
    assert result['estimated_signals']['transition_timing']['phase_boundary_calibration'] is None
    (folder/'result.json').write_bytes((run/'v9_result.json').read_bytes())
    save(folder/'receipt.json', dict(status='PASS', key=key, endpoint='/visualization/analyze',
        actual_multipart_upload=True, fresh_raw_extraction=True, numerical_fit_cache=False,
        sealed_schedule_identical=True, k=result['schedule']['phase_count'],
        rendered_html_bytes=len(response.content), runtime_s=time.monotonic()-begin,
        viewer_sha256=hashlib.sha256(response.content).hexdigest(),
        input_scope=result['input_scope'], recovery_model=result['recovery_model']))
    print(job['site'], 'PASS', 'seconds', time.monotonic()-begin, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key', required=True)
    check(parser.parse_args().key)
