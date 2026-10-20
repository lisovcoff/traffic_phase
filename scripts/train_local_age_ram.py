"""Same causal packets using disposable in-memory SQLite; reuse verified raw copies."""
from contextlib import contextmanager
import argparse
import json
import shutil
import sqlite3
import time
import zipfile
import zlib
from scripts import train_causal_local_ages as base

ORIGINAL_OUT=base.OUT
base.OUT=base.OUT/'training_ram'
RUNTIME=base.ROOT/'.web_runtime/local_observation_age_20261020/v1_ram'


@contextmanager
def ram_spool():
    original=sqlite3.connect
    def connect(*args,**kwargs):
        db=original(':memory:')
        db.execute('PRAGMA journal_mode=MEMORY');db.execute('PRAGMA temp_store=MEMORY')
        return db
    sqlite3.connect=connect
    try:yield
    finally:sqlite3.connect=original


def seal():
    base.OUT.mkdir(parents=True,exist_ok=False);RUNTIME.mkdir(exist_ok=False)
    protocol=base.read_json(ORIGINAL_OUT/'protocol.json')
    protocol['source_sha256']['scripts/train_local_age_ram.py']=base.digest(base.ROOT/'scripts/train_local_age_ram.py')
    protocol.update(spool='same SQLite packet builder, :memory: database; no application journal changes',
                    prior_slow_spools='retained, workers stopped; their unfinished outputs are not training results')
    base.save(base.OUT/'protocol.json',protocol)


def train(index):
    from scripts.archive_online_packets import prepare
    protocol=base.read_json(base.OUT/'protocol.json');assert all(base.digest(base.ROOT/n)==sha for n,sha in protocol['source_sha256'].items())
    model=base.read_model(base.ROOT/'logs/intersection_projects'/base.PARENT);chosen=protocol['chosen'][index]
    r=model['regimes'][index];session=chosen['session'];runtime=RUNTIME/f'train_{index}';runtime.mkdir(exist_ok=False)
    cached=base.ROOT/f'.web_runtime/local_observation_age_20261020/v1_fast/train_{index}/source.json'
    with zipfile.ZipFile(model['input_path_private']) as archive:
        info=archive.getinfo(session['source_member']);valid=cached.exists() and cached.stat().st_size==info.file_size
        crc=0
        if valid:
            with cached.open('rb') as src:
                for chunk in iter(lambda:src.read(4*1024**2),b''):crc=zlib.crc32(chunk,crc)
            valid=crc==info.CRC
        if not valid:
            cached=runtime/'source.json'
            with archive.open(info) as src,cached.open('xb') as dst:shutil.copyfileobj(src,dst,4*1024**2)
    model['queue_observations']=base.read_json(base.ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json')['queue_observations']
    assert base.digest(base.ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json')==protocol['expected_geometry_model_sha256']
    segments,origin=base.phase_history(base.ROOT/'logs/intersection_projects'/base.PARENT,session,model['approaches'],model['projection_version'])
    began=time.monotonic()
    with ram_spool():manifest=prepare(cached,runtime/'unused.sqlite3',runtime/'packets.jsonl')
    print('PACKETS',index,manifest['packets'],round(time.monotonic()-began,1),flush=True)
    with (runtime/'packets.jsonl').open() as stream:
        profile,stats=base.fit_packets(model,r,chosen['member'],segments,origin,(json.loads(line) for line in stream))
    assert all(base.digest(base.ROOT/n)==sha for n,sha in protocol['source_sha256'].items())
    base.save(base.OUT/f'train_{index}.json',dict(regime_id=r['regime_id'],source_member=session['source_member'],
        raw_sha256=base.digest(cached),raw_crc32=info.CRC,prediction_sha256=session['prediction_sha256'],
        packet_manifest=manifest,profile=profile,stats=stats,runtime_s=time.monotonic()-began))
    print('TRAIN RAM',index,stats,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','train','combine']);p.add_argument('--index',type=int)
    a=p.parse_args();seal() if a.action=='seal' else base.combine() if a.action=='combine' else train(a.index)
