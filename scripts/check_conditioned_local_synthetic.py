"""Same development controls, local timing conditioned on observed approach."""
import argparse
from scripts import check_local_age_synthetic as base
from app.experimental.intersection_conditioned_local import ConditionedLocalIntersection
from app.experimental import intersection_local_filter

OLD=base.OUT
base.OUT=base.OUT.parent/'conditioned_v1/synthetic'
intersection_local_filter.LocalProfileIntersection=ConditionedLocalIntersection


def seal():
    base.OUT.mkdir(parents=True,exist_ok=False)
    p=base.read_json(OLD/'protocol.json');p.update(source_sha256={n:base.digest(base.ROOT/n) for n in
        list(p['source_sha256'])+['app/experimental/intersection_conditioned_local.py','scripts/check_conditioned_local_synthetic.py']},
        emission_basis='condition on observed approach; sparse unseen channel uses original joint likelihood; same training profiles')
    base.save(base.OUT/'protocol.json',p)
    for k in range(2,6):base.save(base.OUT/f'k{k}_training.json',base.read_json(OLD/f'k{k}_training.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','evaluate']);p.add_argument('--k',type=int,choices=range(2,6))
    a=p.parse_args();seal() if a.action=='seal' else base.evaluate(a.k)
