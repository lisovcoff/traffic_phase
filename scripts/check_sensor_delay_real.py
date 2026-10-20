"""Same known real windows, original v5 likelihoods with event availability correction."""
import argparse
from scripts import check_coherent_queue as base
from app.experimental.intersection_sensor_delay import SensorDelayIntersection

base.OUT=base.ROOT/'evidence/local_observation_age_20261020/sensor_delay/real'
base.LOCAL=base.ROOT/'.web_runtime/local_observation_age_20261020/sensor_delay/real'
base.CoherentIntersection=SensorDelayIntersection


def seal():
    base.OUT.mkdir(parents=True,exist_ok=False);base.LOCAL.mkdir(parents=True,exist_ok=False)
    parent=base.ROOT/'evidence/coherent_signal_20261020/v5/protocol.json';p=base.read_json(parent)
    base.save(base.LOCAL/'model.json',base.read_json(base.ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json'))
    paths=list(p['source_sha256'])+['app/experimental/intersection_local_filter.py','app/core/intersection_local_emissions.py',
          'app/experimental/intersection_sensor_delay.py','scripts/check_sensor_delay_real.py']
    p.update(source_sha256={n:base.digest(base.ROOT/n) for n in paths},
             correction='observed restart detector onset versus its confirmation time; NOT signal reaction calibration')
    base.save(base.OUT/'protocol.json',p)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','baseline','extended']);a=p.parse_args()
    seal() if a.action=='seal' else base.replay(a.action)
