"""Rejected duration-learning experiment; NOT imported by production inference.

V6 improved synthetic scores but biased real yellow timing because differences
between queue restart delays are not differences between lamp durations. This
implementation is retained for reproduction, not enabled as an application mode.

No absence/stop is a red label. A different phase needs both a distinctive
movement and a concentrated posterior. Durations are restart-to-restart proxies,
shrunk to the original offline prior, not observed controller timings.
"""
import math
import numpy as np


class DurationLearning:
    def __init__(self, medians):
        self.prior=[list(v) for v in medians]
        self.last=[None]*len(medians)
        self.samples=[[[] for _ in v] for v in medians]

    def observe(self, engine, events, timestamp_ms):
        now=timestamp_ms/1000
        for origin,target,weight in events:
            if weight<1:continue
            for i,values in enumerate(engine.marks.likelihoods(origin,target)):
                order=np.argsort(values);phase=int(order[-1])
                mass=engine.banks[i].sum(axis=1);conditional=mass/max(1e-15,mass.sum())
                if len(order)<2 or values[phase]<2*values[order[-2]] or conditional[phase]<.8:continue
                previous=self.last[i]
                if previous is None:self.last[i]=(phase,now);continue
                old,start=previous
                if phase==old:continue
                self.last[i]=(phase,now);duration=now-start;prior=self.prior[i][old]
                if engine.transitions[i][old,phase]<.5 or not .4*prior<=duration<=2.5*prior:continue
                row=self.samples[i][old];row.append(duration);del row[:-7]
                if len(row)<3:continue
                median=(3*prior+len(row)*float(np.median(row)))/(3+len(row))
                regime=engine.model['regimes'][i];stats=regime['phase_durations'][regime['phase_names'][old]]
                lo=stats['p10_s'] or prior*.7;hi=stats['p90_s'] or prior*1.3
                sigma=max(.12,(math.log(max(1.,hi))-math.log(max(1.,lo)))/2.563)
                survival=np.array([.85*.5*math.erfc((math.log(max(.01,a))-math.log(median))/sigma/math.sqrt(2))
                    +.15*math.exp(-a/(4*median)) for a in range(engine.age_cap+2)])
                engine.hazards[i][old]=np.clip(1-survival[1:]/survival[:-1],.0001,.5)
                engine.medians[i][old]=median

    def reset_observations(self):
        self.last=[None]*len(self.last)
