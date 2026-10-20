import sqlite3
import pickle
import numpy as np

import pytest

from app.core import intersection_online_store as store
from app.core.intersection_engine import AdaptiveIntersection
from app.core.intersection_online import CausalIntersection
from app.core.intersection_project import write_json,model_fingerprint
from tests.test_intersection_online import model,packet
from tests.test_intersection_queue_observations import reference


@pytest.mark.parametrize('adaptive',[False,True])
def test_cold_checkpoint_skips_old_replay_but_restores_exact_issued_state(monkeypatch,tmp_path,adaptive):
    monkeypatch.setattr(store,'CHECKPOINT_INTERVAL',4)
    m=model()
    if adaptive:m['queue_observations']=reference()
    m['fingerprint']=model_fingerprint(m)
    folder=tmp_path/'project';write_json(folder/'model.json',m)
    stream=store.create_stream(folder)['stream_id']
    direct=AdaptiveIntersection(m) if adaptive else CausalIntersection(m)
    issued=[]
    for second in range(12):
        p=packet(second,sequence=second*10)
        issued.append(store.accept_packet(folder,stream,p))
        assert issued[-1]==direct.ingest(p)
    store._cache.clear()
    def forbidden(*args):raise AssertionError('cold engine replayed from start instead of checkpoint')
    monkeypatch.setattr(store,'create_engine',forbidden)
    p=packet(12,sequence=120)
    actual=store.accept_packet(folder,stream,p)
    assert actual==direct.ingest(p)
    assert store.stream_history(folder,stream)['snapshots']==issued+[actual]


@pytest.mark.parametrize('damage',['bytes','compatibility','response'])
def test_bad_or_incompatible_checkpoint_falls_back_without_rewriting_history(monkeypatch,tmp_path,damage):
    monkeypatch.setattr(store,'CHECKPOINT_INTERVAL',4)
    folder=tmp_path/'project';write_json(folder/'model.json',model())
    stream=store.create_stream(folder)['stream_id'];issued=[]
    for second in range(4):issued.append(store.accept_packet(folder,stream,packet(second)))
    db_path=folder/'online'/stream/'stream.sqlite3'
    with sqlite3.connect(db_path) as db:
        if damage=='bytes':db.execute("UPDATE checkpoint SET state=?",(b'bad derived cache',))
        elif damage=='compatibility':db.execute("UPDATE checkpoint SET compatibility='older code'")
        else:db.execute("UPDATE checkpoint SET response_digest='wrong response'")
    store._cache.clear()
    actual=store.accept_packet(folder,stream,packet(4))
    direct=CausalIntersection(model())
    for second in range(5):expected=direct.ingest(packet(second))
    assert actual==expected
    assert store.stream_history(folder,stream)['snapshots']==issued+[actual]


def test_invalid_packet_does_not_commit_checkpoint_or_advance_journal(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'CHECKPOINT_INTERVAL',4)
    folder=tmp_path/'project';write_json(folder/'model.json',model())
    stream=store.create_stream(folder)['stream_id']
    for second in range(3):store.accept_packet(folder,stream,packet(second))
    invalid=packet(3);invalid['vehicles'][0]['detections'][0]['millis']+=1
    with pytest.raises(ValueError,match='future'):store.accept_packet(folder,stream,invalid)
    with sqlite3.connect(folder/'online'/stream/'stream.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM packets').fetchone()[0]==3
        assert db.execute('SELECT COUNT(*) FROM checkpoint').fetchone()[0]==0


def test_checkpoint_retains_both_duration_families_and_bound_observation_methods():
    engine=AdaptiveIntersection(model());engine.ingest(packet(0))
    results=[f.summarize(0,f.green,f.edge,f.evidence_ms) for f in engine.filters]
    engine._propose(0,0,48,0,results,np.zeros(8))
    restored=pickle.loads(pickle.dumps(engine,protocol=pickle.HIGHEST_PROTOCOL))
    assert len(restored.filters)==16 and restored.proposals==engine.proposals
    for second in range(1,10):assert restored.ingest(packet(second))==engine.ingest(packet(second))
