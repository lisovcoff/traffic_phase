"""Development-only ablation of duration adaptation; never imported by the app."""
import math
import types
from collections import Counter
import gzip
import json

from scripts.check_regime_observations import ROOT,OUT,RUNTIME
from app.core.intersection_project import read_json
import numpy as np


def attach(engine):
    original=engine._observe
    prior=[list(v) for v in engine.medians];last=[None]*len(prior)
    samples=[[[] for _ in v] for v in prior]
    def observe(events):
        original(events)
        now=engine._observation_time_ms/1000
        for a,b,w in events:
            if w<1:continue
            for i,values in enumerate(engine.marks.likelihoods(a,b)):
                order=np.argsort(values);z=int(order[-1])
                bank=engine.banks[i].sum(axis=1);conditional=bank/max(1e-15,bank.sum())
                if len(order)<2 or values[z]<2*values[order[-2]] or conditional[z]<.8:continue
                prev=last[i]
                if prev is None:last[i]=(z,now);continue
                old,start=prev
                if z==old:continue
                last[i]=(z,now);duration=now-start
                if engine.transitions[i][old,z]<.5 or not .4*prior[i][old]<=duration<=2.5*prior[i][old]:continue
                row=samples[i][old];row.append(duration);del row[:-7]
                if len(row)<3:continue
                med=(3*prior[i][old]+len(row)*float(np.median(row)))/(3+len(row))
                stats=engine.model['regimes'][i]['phase_durations'][engine.model['regimes'][i]['phase_names'][old]]
                lo=stats['p10_s'] or prior[i][old]*.7;hi=stats['p90_s'] or prior[i][old]*1.3
                sigma=max(.12,(math.log(max(1.,hi))-math.log(max(1.,lo)))/2.563)
                survival=np.array([.85*.5*math.erfc((math.log(max(.01,t))-math.log(med))/sigma/math.sqrt(2))
                    +.15*math.exp(-t/(4*med)) for t in range(engine.age_cap+2)])
                engine.hazards[i][old]=np.clip(1-survival[1:]/survival[:-1],.0001,.5)
                engine.medians[i][old]=med
    engine._observe=observe


def run(identifier):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.corpus_validation import save
    out=OUT/'synthetic'/identifier;runtime=RUNTIME/'synthetic'/identifier
    model=read_json(out/'model.json');truth=read_json(out/'online_truth.json')
    with gzip.open(runtime/'causal_events.json.gz','rt',encoding='utf8') as f:rows=json.load(f)
    source=(ROOT/'app/core/intersection_online.py').read_text(encoding='utf8').replace('events=[];rendered=[]','events=list(self.replay_events);rendered=[]')
    module=types.ModuleType('adaptation_replay');exec(compile(source,'<adaptation>','exec'),module.__dict__)
    engines={name:module.CausalIntersection(model) for name in ['adaptive','adaptive_noise20']}
    from app.core.intersection_emissions import MovementMarks
    for name,engine in engines.items():
        engine.marks=MovementMarks(model['regimes'])
        if 'noise20' in name:engine.marks.distributions=[.8*m+.2/len(engine.marks.vocabulary) for m in engine.marks.distributions]
        attach(engine)
    expected={}
    for a,b in dict(N='S',S='N',E='W',W='E').items():
        phases={p for p,g in enumerate(truth['groups']) if a+'->_'+b in g}
        expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
    stats={n:Counter() for n in engines}
    for row in rows:
        second=(row['timestamp_ms']-sim.BASE_MS)/1000
        for name,engine in engines.items():
            engine.replay_events=row['events'];engine._observation_time_ms=row['timestamp_ms']
            r=engine.ingest(dict(timestamp_ms=row['timestamp_ms'],sequence=row['sequence'],vehicles=[]))
            if second<180:continue
            for a,h in r['heads'].items():
                stats[name]['total']+=1;stats[name]['correct']+=h['main']['state']==sim.movement_color_at(expected[a],second)[0]
    result={n:dict(accuracy=s['correct']/s['total'],counts=dict(s),learned_medians=engines[n].medians) for n,s in stats.items()}
    save(out/'adaptation.json',result);print(identifier,{n:round(s['accuracy'],4) for n,s in result.items()},flush=True)


if __name__=='__main__':
    import sys
    for identifier in sys.argv[1:]:run(identifier)
