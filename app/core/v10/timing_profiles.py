"""Source-scoped deployment of independently clock-linked timing calibration."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]


def resolve_timing_profile(path,member,model_id):
    profiles=json.loads((ROOT/'config/signal_timing_profiles.json').read_text(encoding='utf8'))['profiles']
    candidates=[r for r in profiles if r['model_id']==model_id and r['source_member']==member]
    if not candidates:return None
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    digest=h.hexdigest()
    return next((r['calibration'] for r in candidates if digest in r['input_sha256']),None)
