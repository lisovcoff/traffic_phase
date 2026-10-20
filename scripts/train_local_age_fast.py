"""Disposable SQLite spool acceleration for offline validation workers only.

The source archive and output packet rules are unchanged. These PRAGMAs must
never be applied to application journals or any irreplaceable database.
"""
from contextlib import contextmanager
import argparse
import sqlite3
from scripts import train_causal_local_ages as train


@contextmanager
def disposable_spool():
    original=sqlite3.connect
    def connect(*args,**kwargs):
        db=original(*args,**kwargs)
        db.execute('PRAGMA journal_mode=MEMORY');db.execute('PRAGMA synchronous=OFF')
        db.execute('PRAGMA cache_size=-65536');db.execute('PRAGMA temp_store=MEMORY')
        return db
    sqlite3.connect=connect
    try:yield
    finally:sqlite3.connect=original


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',type=int,required=True);a=p.parse_args()
    train.LOCAL=train.ROOT/'.web_runtime/local_observation_age_20261020/v1_fast'
    train.LOCAL.mkdir(exist_ok=True)
    with disposable_spool():train.train(a.index)
