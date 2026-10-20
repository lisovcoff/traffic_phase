"""Known real GREEN/YELLOW development brackets; raw causal packets only."""
import argparse
from scripts import check_coherent_queue as replay
from scripts.train_causal_local_ages import OUT,LOCAL,SOURCES
from app.experimental.intersection_local_filter import LocalProfileIntersection
from app.experimental.intersection_conditioned_local import ConditionedLocalIntersection


def configure(variant):
    replay.OUT=OUT/variant/'real';replay.LOCAL=LOCAL/variant/'real'
    replay.CoherentIntersection=LocalProfileIntersection if variant=='local_v1' else ConditionedLocalIntersection


def seal(variant):
    replay.OUT.mkdir(parents=True,exist_ok=False);replay.LOCAL.mkdir(parents=True,exist_ok=False)
    model=replay.read_json(LOCAL/'model.json');receipt=replay.read_json(OUT/'training_ram/model_receipt.json')
    assert replay.digest(LOCAL/'model.json')==receipt['sha256']
    replay.save(replay.LOCAL/'model.json',model)
    training=[replay.read_json(OUT/f'training_ram/train_{i}.json') for i in range(len(model['regimes']))]
    code=SOURCES+['scripts/train_local_age_ram.py','scripts/check_local_age_real.py','scripts/check_coherent_queue.py']
    if variant=='conditioned_v1':code+=['app/experimental/intersection_conditioned_local.py']
    replay.save(replay.OUT/'protocol.json',dict(source_sha256={n:replay.digest(replay.ROOT/n) for n in code},
        candidate_model_sha256=replay.digest(replay.LOCAL/'model.json'),variant=variant,
        sampled_detection_extent_ms=[min(t['stats']['first_ms'] for t in training),max(t['stats']['last_ms'] for t in training)],
        extent_semantics='legacy field name; actual complete causal training packet extent, not a sample',
        history_lag_s=10,training_regimes=len(model['regimes']),video_supplied_to_training=False,
        source_comparison='same known original and +12s copies as previous experiments; conditional clock; development only',
        production_enabled=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','baseline','extended'])
    p.add_argument('--variant',choices=['local_v1','conditioned_v1'],default='local_v1');a=p.parse_args()
    configure(a.variant);seal(a.variant) if a.action=='seal' else replay.replay(a.action)
