"""Bounded JSON/ZIP batch CLI; no annotation or experimental-history interface."""
import argparse
import json
from pathlib import Path

from app.core.archive_batch import BatchConfig, run_archive_batch, run_source_worker, render_batch_html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    worker = sub.add_parser('_worker', help=argparse.SUPPRESS)
    worker.add_argument('request', type=Path)
    run = sub.add_parser('run')
    run.add_argument('source', type=Path)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--max-jobs', type=int, default=4)
    run.add_argument('--total-seconds', type=float, default=180)
    run.add_argument('--source-seconds', type=float, default=90)
    args = parser.parse_args()
    if args.command == '_worker':
        run_source_worker(json.loads(args.request.read_text(encoding='utf-8')))
        return
    config = BatchConfig(max_jobs=args.max_jobs, total_seconds=args.total_seconds, source_seconds=args.source_seconds)
    manifest = run_archive_batch(args.source, args.out, config=config)
    (args.out/'index.html').write_text(render_batch_html(manifest, args.out), encoding='utf-8')
    print(json.dumps({'status': manifest['status'], 'attempted_jobs': manifest['attempted_jobs'],
                      'report': str(args.out/'index.html')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
