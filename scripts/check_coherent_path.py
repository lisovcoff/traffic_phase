"""Same raw-packet scoring protocol, committed joint path instead of marginal MAP."""
import argparse
from scripts import check_coherent_queue as base
from app.experimental.intersection_signal_path import PathIntersection

base.OUT=base.ROOT/'evidence/coherent_signal_20261020/path_v1'
base.LOCAL=base.ROOT/'.web_runtime/coherent_signal_20261020/path_v1'
base.CoherentIntersection=PathIntersection


def seal():
    base.OUT.mkdir(parents=True,exist_ok=False);base.LOCAL.mkdir(parents=True,exist_ok=False)
    origin=base.ROOT/'evidence/coherent_signal_20261020/v5/protocol.json'
    protocol=base.read_json(origin)
    model=base.read_json(base.ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json')
    base.save(base.LOCAL/'model.json',model)
    sources=list(protocol['source_sha256'])+['app/core/intersection_signal_path.py',
        'app/experimental/intersection_signal_path.py','scripts/check_coherent_path.py']
    protocol.update(source_sha256={p:base.digest(base.ROOT/p) for p in sources},
                    point_estimator='COMMITTED_FIXED_LAG_MAX_PRODUCT_PATH',
                    geometry_parent_protocol_sha256=base.digest(origin),
                    candidate_model_sha256=base.digest(base.LOCAL/'model.json'))
    base.save(base.OUT/'protocol.json',protocol)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['seal','baseline','extended'])
    args=parser.parse_args();seal() if args.action=='seal' else base.replay(args.action)
