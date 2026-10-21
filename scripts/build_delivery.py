"""Create and verify a source delivery from a clean, tracked working tree.

Includes hydrated Git LFS files, tests and public results; excludes local
untracked media and runtime folders. Does not alter tracked source files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'DELIVERY_MANIFEST.json'


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def verify(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate archive entries')
        for name in names:
            member = PurePosixPath(name)
            if member.is_absolute() or '..' in member.parts or '\\' in name:
                raise ValueError(f'unsafe archive name: {name}')
        manifest = json.loads(archive.read(MANIFEST))
        if set(names) != set(manifest['files']) | {MANIFEST}:
            raise ValueError('manifest/archive membership mismatch')
        for name, expected in manifest['files'].items():
            data = archive.read(name)
            if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError(f'delivery hash mismatch: {name}')
    with path.open('rb') as stream:
        archive_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'status': 'PASS', 'commit': manifest['commit'], 'files': len(manifest['files']),
            'archive_bytes': path.stat().st_size,
            'archive_sha256': archive_hash}


def build(path: Path) -> dict:
    if git('status', '--porcelain', '--untracked-files=normal').strip():
        raise ValueError('commit source changes first; delivery requires a clean tree')
    if path.exists():
        raise FileExistsError(path)
    files = sorted(name for name in git('ls-files', '-z').decode('utf-8').split('\0') if name)
    manifest = {'format': 1, 'commit': git('rev-parse', 'HEAD').decode().strip(),
        'branch': git('branch', '--show-current').decode().strip(),
        'scope': 'tracked working files including hydrated LFS; no local media or runtime',
        'acceptance': 'See GUIDE.md and results/README.md; tests are not independent accuracy proof',
        'files': {}}
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves any existing delivery, even if another process creates it.
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in files:
            data = (ROOT/name).read_bytes()
            if data.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                raise ValueError(f'unhydrated LFS pointer: {name}')
            manifest['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            archive.writestr(name, data)
        archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return verify(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path, help='new ZIP path (never overwritten)')
    group.add_argument('--verify', type=Path, help='verify an existing delivery ZIP')
    args = parser.parse_args()
    print(json.dumps(verify(args.verify) if args.verify else build(args.output), indent=2))


if __name__ == '__main__':
    main()
