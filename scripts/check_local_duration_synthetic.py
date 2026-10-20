"""Same twelve development streams, additionally using offline duration laws."""
import argparse
from scripts import check_local_age_synthetic as base
from app.experimental.intersection_learned_duration import LearnedDurationIntersection
from app.experimental import intersection_local_filter

OLD=base.OUT
base.OUT=base.OUT.parent/'duration_v1/synthetic'
base.LOCAL=base.LOCAL.parent/'duration_v1/synthetic'
intersection_local_filter.LocalProfileIntersection=LearnedDurationIntersection
EXTRA=['app/core/intersection_duration_learning.py','app/experimental/intersection_learned_duration.py',
       'scripts/learn_local_duration_laws.py','scripts/check_local_duration_synthetic.py']


def seal():
    base.OUT.mkdir(parents=True,exist_ok=True);base.LOCAL.mkdir(parents=True,exist_ok=True)
    p=base.read_json(OLD/'protocol.json')
    p.update(source_sha256={n:base.digest(base.ROOT/n) for n in list(p['source_sha256'])+EXTRA},
             duration_basis='offline fitted durations; 1s grid spread floor; 2% minimum exception component; no video tuning')
    base.save(base.OUT/'protocol.json',p)


def prepare(k):
    old=base.read_json(OLD/f'k{k}_training.json')
    old.update(model_sha256=base.digest(base.LOCAL/f'k{k}_model.json'),
               duration_laws_sha256=base.digest(base.OUT/f'k{k}_model_duration_laws.json'),
               same_local_emission_training_as=str(OLD/f'k{k}_training.json'))
    base.save(base.OUT/f'k{k}_training.json',old)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','prepare','evaluate']);p.add_argument('--k',type=int,choices=range(2,6))
    a=p.parse_args();seal() if a.action=='seal' else prepare(a.k) if a.action=='prepare' else base.evaluate(a.k)
