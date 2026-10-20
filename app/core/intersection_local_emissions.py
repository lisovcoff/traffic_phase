"""Offline fitted ages of CAUSALLY CONFIRMED observations, not lamp delays.

Positive marks share one categorical alphabet across regimes. No absent vehicle
is interpreted as RED. Phase histories are trajectory fits, never lamp truth.
"""
from collections import Counter
import numpy as np

KINDS=('LEGACY_RESTART','LEGACY_EXIT','NEAR_RESTART','PASSAGE','STOP','BRAKE')


def alphabet(approaches):
    return [kind+':'+a for kind in KINDS for a in sorted(approaches)]


class LocalAgeCounts:
    def __init__(self,approaches,phase_count,bins=32):
        self.alphabet=alphabet(approaches);self.lookup={v:i for i,v in enumerate(self.alphabet)}
        self.counts=np.zeros((phase_count,bins,len(self.alphabet)));self.bins=bins
        self.samples=Counter()

    def add(self,kind,origin,phase,fraction):
        if not 0<=fraction<1:return
        key=kind+':'+origin
        self.counts[phase,min(self.bins-1,int(fraction*self.bins)),self.lookup[key]]+=1
        self.samples[kind]+=1

    def finish(self):
        c=self.counts;phase_prior=c.sum(axis=1)+1
        phase_prior/=phase_prior.sum(axis=1,keepdims=True)
        smoothed=np.zeros_like(c)
        for offset,weight in ((-2,1),(-1,2),(0,3),(1,2),(2,1)):
            ix=np.clip(np.arange(self.bins)+offset,0,self.bins-1)
            smoothed+=c[:,ix,:]*weight/9
        # Eight broad pseudo-observations shrink sparse age cells to that
        # phase's composition, not to another channel's event-time definition.
        values=smoothed+8*phase_prior[:,None,:]
        values/=values.sum(axis=2,keepdims=True)
        return dict(schema='causal-confirmation-age-v1',alphabet=self.alphabet,bins=self.bins,
                    probabilities=values.tolist(),counts=c.tolist(),samples=dict(self.samples),
                    time_basis='packet availability aligned to fitted trajectory-phase history',
                    physical_reaction_or_lamp_delay_calibrated=False)


def duration_age_weights(hazard,median,clearance,bins):
    """P(normalized phase age | still GREEN at elapsed a), same duration law.

Using a/median clipped at the last bin would make a legitimate extension look
like a permanent end-of-phase observation. Marginalize over surviving durations
instead. Residual overflow is represented by its exponential-tail expectation.
"""
    hazard=np.asarray(hazard,dtype=float);cap=len(hazard)-1
    survival=np.r_[1.,np.cumprod(1-hazard)]
    durations=np.r_[np.arange(1,cap+2,dtype=float),cap+1+4*median]
    mass=np.r_[survival[:-1]*hazard,survival[-1]]
    result=np.zeros((cap+1,bins))
    for age in range(cap+1):
        valid=durations>age;weights=mass[valid];weights=weights/weights.sum()
        index=np.minimum(bins-1,(age/(durations[valid]+clearance)*bins).astype(int))
        np.add.at(result[age],index,weights)
    return result
