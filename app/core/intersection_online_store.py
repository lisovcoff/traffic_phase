"""Transactional packet journal and deterministic causal-state restoration."""
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import pickle
import sqlite3
import sys
from threading import RLock
import uuid
import zlib
import numpy as np

from app.core.intersection_project import read_model,read_json,write_json
from app.core.intersection_engine import create_engine,recommended_version,SUPPORTED_VERSIONS

_lock=RLock();_cache=OrderedDict()
CHECKPOINT_INTERVAL=60


@lru_cache(maxsize=1)
def _checkpoint_code():
    """Internal cache compatibility; an update falls back to exact journal replay."""
    root=Path(__file__).resolve().parents[1];value=hashlib.sha256()
    value.update(str(sys.version_info[:2]).encode())
    value.update(np.__version__.encode())
    for home in ('core','timing'):
        for path in sorted((root/home).rglob('*.py')):
            value.update(path.relative_to(root).as_posix().encode());value.update(path.read_bytes())
    return value.hexdigest()


def _checkpoint_table(db):
    db.execute('CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK (id=1), sequence INTEGER NOT NULL, compatibility TEXT NOT NULL, response_digest TEXT NOT NULL, state_digest TEXT NOT NULL, state BLOB NOT NULL)')


def _restore_checkpoint(db,manifest):
    row=db.execute('SELECT sequence,compatibility,response_digest,state_digest,state FROM checkpoint WHERE id=1').fetchone()
    if row is None or row[1]!=_checkpoint_code():return None
    last=db.execute('SELECT timestamp_ms,response FROM packets WHERE sequence=?',(row[0],)).fetchone()
    if last is None or hashlib.sha256(last[1].encode()).hexdigest()!=row[2]:return None
    if hashlib.sha256(row[4]).hexdigest()!=row[3]:return None
    try:
        # Only our own private SQLite state is deserialized. No API accepts
        # pickle/checkpoint uploads; this is a trusted internal disposable cache.
        engine=pickle.loads(zlib.decompress(row[4]))
        model=engine.model if hasattr(engine,'model') else engine.source.motion.model
        schema=getattr(engine,'VERSION',None) or 'causal-intersection-v7'
        if (model['fingerprint']!=manifest['model_fingerprint']
                or schema!=manifest['engine'] or engine.last_ms!=last[0]):return None
        return row[0],engine
    except (ValueError,TypeError,KeyError,AttributeError,ImportError,EOFError,pickle.UnpicklingError,zlib.error):
        return None


def _save_checkpoint(db,engine,sequence,response_text):
    state=zlib.compress(pickle.dumps(engine,protocol=pickle.HIGHEST_PROTOCOL),level=1)
    db.execute('INSERT OR REPLACE INTO checkpoint VALUES (1,?,?,?,?,?)',
        (sequence,_checkpoint_code(),hashlib.sha256(response_text.encode()).hexdigest(),
         hashlib.sha256(state).hexdigest(),state))


def create_stream(folder):
    folder=Path(folder)
    if not (folder/'model.json').is_file():raise ValueError('offline model is not ready')
    model=read_model(folder);identifier=uuid.uuid4().hex
    home=folder/'online'/identifier;home.mkdir(parents=True)
    manifest=dict(stream_id=identifier,model_id=model['model_id'],model_fingerprint=model['fingerprint'],engine=recommended_version(model))
    write_json(home/'stream.json',manifest)
    with sqlite3.connect(home/'stream.sqlite3') as db:
        db.execute('CREATE TABLE packets (sequence INTEGER PRIMARY KEY, timestamp_ms INTEGER NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, response TEXT NOT NULL)')
        db.execute('CREATE INDEX packet_time ON packets(timestamp_ms)')
    return manifest


def _home(folder,identifier):
    if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise KeyError('unknown online stream')
    home=Path(folder)/'online'/identifier
    if not (home/'stream.json').is_file():raise KeyError('unknown online stream')
    return home


def _encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def accept_packet(folder,identifier,packet):
    with _lock:
        home=_home(folder,identifier);manifest=read_json(home/'stream.json');model=read_model(folder)
        if manifest['model_fingerprint']!=model['fingerprint'] or manifest['engine'] not in SUPPORTED_VERSIONS:raise ValueError('stream model/engine changed; start a new stream')
        payload=_encode(packet);digest=hashlib.sha256(payload.encode()).hexdigest();key=str(home.resolve())
        with sqlite3.connect(home/'stream.sqlite3') as db:
            db.execute('BEGIN IMMEDIATE')
            _checkpoint_table(db)
            row=db.execute('SELECT digest,response FROM packets WHERE sequence=?',(packet['sequence'],)).fetchone()
            if row:
                if row[0]!=digest:raise ValueError('sequence already used for a different packet')
                return json.loads(row[1])
            previous=db.execute('SELECT sequence FROM packets ORDER BY sequence DESC LIMIT 1').fetchone()
            if previous and packet['sequence']<=previous[0]:raise ValueError('sequence must increase')
            if key in _cache and previous and _cache[key][0]==previous[0]:engine=deepcopy(_cache[key][1])
            else:
                restored_state=_restore_checkpoint(db,manifest)
                start,engine=restored_state if restored_state is not None else (-1,create_engine(model,manifest['engine']))
                for payload_text,response_text in db.execute('SELECT payload,response FROM packets WHERE sequence>? ORDER BY sequence',(start,)):
                    restored=engine.ingest(json.loads(payload_text))
                    if _encode(restored)!=response_text:raise ValueError('journal replay mismatch; history preserved, start a new stream')
            base=engine.ingest(packet)
            response_text=_encode(base)
            db.execute('INSERT INTO packets VALUES (?,?,?,?,?)',(packet['sequence'],packet['timestamp_ms'],digest,payload,response_text))
            checkpoint=db.execute('SELECT sequence FROM checkpoint WHERE id=1').fetchone()
            # Count accepted rows, not sequence arithmetic: producers may skip IDs.
            pending=db.execute('SELECT COUNT(*) FROM packets WHERE sequence>?',(checkpoint[0] if checkpoint else -1,)).fetchone()[0]
            if pending>=CHECKPOINT_INTERVAL:_save_checkpoint(db,engine,packet['sequence'],response_text)
            db.commit()
        _cache[key]=(packet['sequence'],engine);_cache.move_to_end(key)
        while len(_cache)>16:_cache.popitem(last=False)
        return base


def stream_history(folder,identifier,after=-1,limit=1000):
    with _lock:
        home=_home(folder,identifier)
        with sqlite3.connect(home/'stream.sqlite3') as db:
            rows=db.execute('SELECT response FROM packets WHERE sequence>? ORDER BY sequence LIMIT ?',(after,min(1000,max(1,limit)))).fetchall()
        return dict(**read_json(home/'stream.json'),snapshots=[json.loads(row[0]) for row in rows])


def latest_snapshot(folder,identifier):
    with _lock:
        home=_home(folder,identifier)
        with sqlite3.connect(home/'stream.sqlite3') as db:
            row=db.execute('SELECT response FROM packets ORDER BY sequence DESC LIMIT 1').fetchone()
        return dict(**read_json(home/'stream.json'),snapshot=json.loads(row[0]) if row else None)


def snapshot_at(folder,identifier,timestamp_ms):
    with _lock:
        home=_home(folder,identifier)
        with sqlite3.connect(home/'stream.sqlite3') as db:
            row=db.execute('SELECT response FROM packets WHERE timestamp_ms<=? ORDER BY timestamp_ms DESC LIMIT 1',(timestamp_ms,)).fetchone()
        return dict(**read_json(home/'stream.json'),snapshot=json.loads(row[0]) if row else None,
            historical=True,semantics='original issuance at or before requested time; not retrospective correction')
