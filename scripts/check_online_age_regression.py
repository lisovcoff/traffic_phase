"""Compare age-prior candidate on the already-revealed diagnostic packet streams."""
import argparse
from collections import Counter
import json
from pathlib import Path

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(out,geographic=False):
    from scripts.enrich_intersection_model import enrich
    from app.core.intersection_online import CausalIntersection
    from scripts import realistic_traffic_benchmark as sim
    from app.core.intersection_project import read_json
    out=Path(out);out.mkdir(parents=True,exist_ok=False);rows=[]
    parent=ROOT/'evidence/intersection_online_20261019/diagnostic_v2'
    for k in (2,3):
        original=read_json(parent/f'k{k}_model.json');before=read_json(parent/f'k{k}_receipt.json')
        model,folder=enrich(ROOT/'logs/intersection_projects'/original['model_id'])
        truth=read_json(parent/f'k{k}_online_truth.json');engine=CausalIntersection(model);counts=Counter()
        runs={a:sim.movement_signal_plan(truth['signal_plan'],{p for p,g in enumerate(truth['groups']) if a+'->_'+b in g})
            for a,b in dict(N='S',S='N',E='W',W='E').items()}
        if geographic:
            from scripts.online_packets import packets_from_tracks
            env=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
            tracks,_=sim.generate(truth['config'],env)
            packets=packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+1800000)
        else:
            packets=[json.loads(line) for line in (parent/f'k{k}_packets.jsonl').read_text().splitlines()]
        for packet in packets:
                r=engine.ingest(packet);second=(r['timestamp_ms']-sim.BASE_MS)/1000
                if second<180:continue
                for a,h in r['heads'].items():
                    color=h['main']['state'];expected=sim.signal_at(runs[a],0,second)[0]
                    counts['total']+=1;counts['known']+=color!='UNKNOWN';counts['correct']+=color==expected
        accuracy=counts['correct']/counts['total'];row=dict(k=k,model_id=model['model_id'],counts=dict(counts),
            before=before['main_accuracy_including_unknown'],after=accuracy,
            coverage=counts['known']/counts['total'],conditional_known_accuracy=counts['correct']/counts['known'])
        row['geographic_detections']=geographic
        rows.append(row);save(out/f'k{k}.json',row);print(row,flush=True)
    save(out/'receipt.json',dict(status='COMPLETED',results=rows,scope='development comparison, revealed data; not independent validation'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--geographic',action='store_true');args=p.parse_args();main(args.out,args.geographic)
