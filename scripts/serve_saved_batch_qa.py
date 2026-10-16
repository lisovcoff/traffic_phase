"""Isolated UI QA: sealed batch predictions only, no extraction or fitting."""
import json
from pathlib import Path
import zipfile

import uvicorn
from app.main import app
from app.api import archive_batch as api
from app.core.archive_batch import render_batch_html, sha256_file
from app.core.offline_product_report import render_product_html


def main():
    root = Path(__file__).resolve().parents[1]
    sealed = root/'evidence/bounded_archive_batch_20261016/download.zip'
    freeze = json.loads((sealed.parent/'freeze.json').read_text(encoding='utf-8'))

    def saved_only(source, output):
        if sha256_file(source) != freeze['input_sha256']:
            raise ValueError('QA_REPLAY_INPUT_DIFFERS_FROM_SEALED_BATCH')
        output.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(sealed) as archive:
            for info in archive.infolist():
                member = Path(info.filename)
                if member.is_absolute() or '..' in member.parts or info.is_dir():
                    raise ValueError('INVALID_QA_ARTIFACT_PATH')
                target = output/member
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        manifest = json.loads((output/'manifest.json').read_text(encoding='utf-8'))
        for source in manifest['sources_processed']:
            for job in source['jobs']:
                folder = output/source['artifact_directory']
                value = json.loads((folder/job['prediction']).read_text(encoding='utf-8'))
                report = folder/job['report']
                report.write_text(render_product_html(value), encoding='utf-8')
                job['report_sha256'] = sha256_file(report)
        (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        page = render_batch_html(manifest, output)
        (output/'index.html').write_text(page, encoding='utf-8')
        with zipfile.ZipFile(output/'results.zip', 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(output.rglob('*')):
                if path.is_file() and path.name != 'results.zip':
                    zipped.write(path, path.relative_to(output).as_posix())
        print('[QA_SAVED_BATCH] no extraction or phase fitting', flush=True)
        return page

    api._build_batch = saved_only
    uvicorn.run(app, host='127.0.0.1', port=8021)


if __name__ == '__main__':
    main()
