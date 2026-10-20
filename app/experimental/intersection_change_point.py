"""Causal competing duration modes after an unexpected completed interval.

An outlier creates a provisional timing hypothesis, rather than prematurely
replacing the ordinary program or waiting for three full new cycles. Evidence
chooses between them. Both families keep the exact offline structure.
"""
from copy import deepcopy

import numpy as np

from app.core.intersection_duration_learning import duration_arrays
from app.experimental.intersection_timing_ensemble import trajectory_duration_law
from app.experimental.intersection_front_waiting import FrontWaitingTimingIntersection
from app.experimental.intersection_front_release import stopped_front


class ChangePointTimingIntersection(FrontWaitingTimingIntersection):
    VERSION='experimental-change-point-timing-v2'
    # Geometric quality alone does not calibrate the lamp/braking likelihood.
    # Retain the established weak emission; duration modes carry change evidence.
    LEADING_BRAKE_WEIGHT=.4

    def __init__(self,model):
        super().__init__(model)
        self.family_size=len(self.filters)
        self.proposals={}
        self.change_observations=[]

    def _propose(self,regime,phase,elapsed,now,results,deltas):
        tracker=self.trackers[regime];r=self.source.motion.model['regimes'][regime]
        expected=tracker.accepted[phase] or tracker.priors[phase]
        stats=r['phase_durations'][r['phase_names'][phase]]
        spread=((stats.get('p90_s') or expected)-(stats.get('p10_s') or expected))/2
        tolerance=max(2.,.05*expected,spread)
        if abs(elapsed-expected)<=tolerance:return results,deltas
        ratio=elapsed/expected
        target=[(tracker.accepted[z] or prior)*ratio for z,prior in enumerate(tracker.priors)]
        old=self.proposals.get(regime)
        if old is not None and max(abs(a-b) for a,b in zip(old,target))<=tolerance:return results,deltas
        self.proposals[regime]=target
        n=self.family_size
        if len(self.filters)==n:
            clones=[deepcopy(f,{id(f.model):f.model}) for f in self.filters]
            self.filters.extend(clones)
            self.weights=np.r_[self.weights*.5,self.weights*.5]
            results=results+deepcopy(results);deltas=np.r_[deltas,deltas]
        else:
            # Keep two bounded families even after another genuine change.
            # Replacing a provisional forecast never rewrites an issued row.
            for j,f in enumerate(self.filters[:n]):
                self.filters[n+j]=deepcopy(f,{id(f.model):f.model})
            ordinary=self.weights[:n];ordinary=ordinary/max(ordinary.sum(),1e-300)
            self.weights=np.r_[ordinary*.5,ordinary*.5]
            results=results[:n]+deepcopy(results[:n]);deltas=np.r_[deltas[:n],deltas[:n]]
        for f in self.filters[n:]:
            for index,values in self.proposals.items():
                mode=self.source.motion.model['regimes'][index]
                for z,value in enumerate(values):
                    # Preserve ordinary offline jitter; changing the median is
                    # not evidence that physical duration uncertainty is zero.
                    original=mode['phase_durations'][mode['phase_names'][z]]
                    center=tracker.priors[z] if index==regime else (
                        original['median_s'] or mode['period_s']/mode['phase_count'])
                    scale=value/max(center,1e-9)
                    fit=dict(median_s=value,p10_s=(original.get('p10_s') or center)*scale,
                             p90_s=(original.get('p90_s') or center)*scale)
                    law=trajectory_duration_law(fit,mode['period_s'],mode['phase_count'],f.prior.clearance_s)
                    law['tail_probability']=self.DURATION_TAIL_PROBABILITY
                    f.hazards[index][z],_=duration_arrays(law,f.age_cap)
                    f.medians[index][z]=law['green_median_s']
                self._reset_prior(f,index)
        self.change_observations.append(dict(regime_index=regime,completed_phase=phase,
            completed_interval_s=elapsed,ordinary_interval_s=expected,provisional_intervals_s=target,
            available_at_ms=now,source='OBSERVED_COMPLETED_INTERVAL_NOT_LAMP_TRUTH'))
        return results,deltas

    @staticmethod
    def _reset_prior(f,index):
        hazard=f.hazards[index]
        survival=np.c_[np.ones(len(hazard)),np.cumprod(1-hazard[:,:-1],axis=1)]
        f.initial[index]=survival/(survival.sum()*len(f.model['regimes']))

    def _tick_hypotheses(self,now,q,legacy,blocked):
        previous=[t.last for t in self.trackers]
        original=self.restart_changes
        # A following queued car is permission evidence, but its delayed start
        # cannot anchor a completed phase interval. Keep it in q for inference.
        self.restart_changes=[t for t in original if blocked.get(t['origin'],.03)<.5
            and t['origin'] in self.source.queues.references
            and stopped_front(t,self.source.queues.references[t['origin']],t['last_restart_ms'])]
        try:results,deltas=super()._tick_hypotheses(now,q,legacy,blocked)
        finally:self.restart_changes=original
        self.change_observations=[]
        if len(self.filters)>self.family_size and self.duration_updates:
            for f in self.filters[self.family_size:]:
                for update in self.duration_updates:self._reset_prior(f,update['regime_index'])
        for index,(old,t) in enumerate(zip(previous,self.trackers)):
            if old is None or t.last is None or old==t.last or old[0]==t.last[0]:continue
            elapsed=(t.last[1]-old[1])/1000;phase=old[0]
            if not .4*t.priors[phase]<=elapsed<=2.5*t.priors[phase]:continue
            if t.allowed[phase,t.last[0]]<.8:continue
            results,deltas=self._propose(index,phase,elapsed,now,results,deltas)
        return results,deltas

    def _summarize(self,base,results,q,blocked):
        result=super()._summarize(base,results,q,blocked)
        n=self.family_size
        result.update(timing_mode_probabilities=dict(ordinary=float(self.weights[:n].sum()),
            provisional=float(self.weights[n:].sum())),
            timing_change_observations=deepcopy(self.change_observations),
            duration_mode_semantics='COMPETING_FORECASTS; NOT_CONFIRMED_CONTROLLER_PROGRAMS')
        return result
