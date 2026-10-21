"""Default-off causal adaptation from repeated completed front-release intervals.

An isolated extension does not replace the ordinary program. No phase count,
movement grouping, hardware section or previously issued result is changed.
"""
from collections import deque
from copy import deepcopy

import numpy as np

from app.core.intersection_duration_learning import duration_arrays
from app.timing.intersection_timing_ensemble import trajectory_duration_law
from app.timing.intersection_leading_brake import RobustTimingIntersection


class CompletedPhaseDurations:
    def __init__(self,regime):
        self.priors=[regime['phase_durations'][n]['median_s'] or regime['period_s']/regime['phase_count']
                     for n in regime['phase_names']]
        k=regime['phase_count'];self.allowed=np.zeros((k,k))
        for row in regime.get('observed_transitions',[]):self.allowed[row['source'],row['target']]+=row['observations']
        for z in range(k):
            if not self.allowed[z].sum():self.allowed[z,(z+1)%k]=1
            self.allowed[z]/=self.allowed[z].sum()
        self.last=None;self.samples=[deque(maxlen=7) for _ in self.priors]
        self.accepted=[None]*k

    def observe(self,phase,onset_ms):
        if self.last is None:self.last=(phase,onset_ms);return None
        previous,start=self.last
        if onset_ms<=start or phase==previous:return None
        elapsed=(onset_ms-start)/1000
        if elapsed>2.5*max(self.priors):
            self.last=(phase,onset_ms);return None
        if self.allowed[previous,phase]<.8 or not .4*self.priors[previous]<=elapsed<=2.5*self.priors[previous]:return None
        self.last=(phase,onset_ms);samples=self.samples[previous];samples.append(elapsed)
        if len(samples)<3:return None
        window=np.asarray(list(samples)[-3:])
        median=float(np.median(window));mad=float(np.median(np.abs(window-median)))
        # Two recent agreeing intervals are needed as well as the robust median.
        tolerance=max(2.,.05*median)
        if mad>tolerance or max(abs(v-median) for v in list(samples)[-2:])>tolerance:return None
        old=self.accepted[previous]
        if old is not None and abs(old-median)<.5:return None
        self.accepted[previous]=median
        return dict(phase=previous,median_s=median,scale_s=max(1.,1.4826*mad),samples=len(window),
                    available_at_ms=onset_ms,source='COMPLETED_FRONT_RELEASE_INTERVALS_NOT_LAMP_LABELS')


class AdaptiveRobustTimingIntersection(RobustTimingIntersection):
    VERSION='experimental-joint-adaptive-timing-v2'
    REQUIRE_STOP_TARGET=True
    # Fitted logical phase age includes unknown transition offsets. Applying
    # that histogram to GREEN age shifts the clock; do not equate the two.
    USE_TRAJECTORY_AGE_PRIOR=False

    def __init__(self,model):
        super().__init__(model)
        self.trackers=[CompletedPhaseDurations(r) for r in model['regimes']]
        self.duration_updates=[]

    def _tick_hypotheses(self,now,q,legacy,blocked):
        results,deltas=super()._tick_hypotheses(now,q,legacy,blocked)
        masses=sum(float(weight)*np.asarray([g.sum()+e.sum() for g,e in zip(f.green,f.edge)])
                   for weight,f in zip(self.weights,self.filters))
        regime_index=int(masses.argmax());self.duration_updates=[]
        if masses[regime_index]<.85:return results,deltas
        groups={(a,b) for a,b,w in q['restarts']}
        observed={}
        for track in self.restart_changes:
            group=(track['origin'],track['target'])
            if group not in groups:continue
            onset=track['last_restart_ms']
            if not 0<=now-onset<=8000:continue
            observed[group]=min(observed.get(group,onset),onset)
        tracker=self.trackers[regime_index]
        for (a,b),onset in sorted(observed.items(),key=lambda pair:pair[1]):
            values=self.filters[0].marks.likelihoods(a,b)[regime_index];order=np.argsort(values)
            if len(order)<2 or values[order[-1]]<4*values[order[-2]]:continue
            update=tracker.observe(int(order[-1]),onset)
            if update is None:continue
            update=dict(update,regime_index=regime_index,available_at_ms=now)
            self.duration_updates.append(update)
            # Only future transitions use the updated law; current mass and past
            # issued colors are retained. Structure remains entirely offline.
            r=self.source.motion.model['regimes'][regime_index];z=update['phase']
            stats=dict(median_s=update['median_s'],p10_s=update['median_s']-1.2815*update['scale_s'],
                       p90_s=update['median_s']+1.2815*update['scale_s'])
            for f in self.filters:
                law=trajectory_duration_law(stats,r['period_s'],r['phase_count'],f.prior.clearance_s)
                law['tail_probability']=self.DURATION_TAIL_PROBABILITY
                hazard,survival=duration_arrays(law,f.age_cap)
                f.hazards[regime_index][z]=hazard;f.medians[regime_index][z]=law['green_median_s']
                # Rebuild the reset-age distribution for every phase in this regime.
                prior=[]
                for phase,name in enumerate(r['phase_names']):
                    value=tracker.accepted[phase]
                    s=r['phase_durations'][name] if value is None else dict(median_s=value,p10_s=value-1.2815,p90_s=value+1.2815)
                    reset_law=trajectory_duration_law(s,r['period_s'],r['phase_count'],f.prior.clearance_s)
                    reset_law['tail_probability']=self.DURATION_TAIL_PROBABILITY
                    _,age_prior=duration_arrays(reset_law,f.age_cap);prior.append(age_prior)
                bank=np.asarray(prior);bank/=bank.sum()*len(self.trackers);f.initial[regime_index]=bank
        return results,deltas

    def _summarize(self,base,results,q,blocked):
        result=super()._summarize(base,results,q,blocked)
        result.update(completed_interval_updates=deepcopy(self.duration_updates),
                      adapted_phase_medians_s=[list(t.accepted) for t in self.trackers],
                      duration_basis='CAUSAL_REPEATED_COMPLETED_INTERVALS_WITH_ISOLATED_EXTENSION_TAIL')
        return result
