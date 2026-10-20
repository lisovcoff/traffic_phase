import json
import sqlite3
from scripts.archive_online_packets import prepare
from scripts.train_local_age_fast import disposable_spool
from scripts.train_local_age_ram import ram_spool


def test_disposable_sqlite_settings_preserve_packets_and_restore_library(tmp_path):
    tracks=[]
    for i in range(12):
        ds=[dict(millis=1000+j*137+i,zone='N' if j<10 else '_S',speed=0 if j<7 else 12,
                 lat=55.,lng=61.,centroid_x=.4,centroid_y=.5) for j in range(20)]
        tracks.append(dict(id=i,zone_in='N',zone_out='_S',detections=ds))
    source=tmp_path/'records.json';source.write_text(json.dumps(tracks),encoding='utf8')
    original=sqlite3.connect
    normal=prepare(source,tmp_path/'normal.sqlite',tmp_path/'normal.jsonl')
    with disposable_spool():fast=prepare(source,tmp_path/'fast.sqlite',tmp_path/'fast.jsonl')
    assert sqlite3.connect is original
    assert normal['sha256']==fast['sha256'] and normal['counts']==fast['counts']
    assert (tmp_path/'normal.jsonl').read_bytes()==(tmp_path/'fast.jsonl').read_bytes()
    with ram_spool():ram=prepare(source,tmp_path/'unused.sqlite',tmp_path/'ram.jsonl')
    assert ram['sha256']==normal['sha256'] and sqlite3.connect is original
    assert (tmp_path/'ram.jsonl').read_bytes()==(tmp_path/'normal.jsonl').read_bytes()
