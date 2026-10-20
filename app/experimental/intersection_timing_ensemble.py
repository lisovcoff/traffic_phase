"""Default-off joint timing hypotheses using trajectory-only offline statistics.

The intergreen is latent rather than fixed to the last three seconds of a phase.
Physical colors and variable-duration tails belong to the same posterior. Videos,
lamp labels, site names and absolute offline phase clocks are not accepted.
"""
from copy import deepcopy
import json
import math

import numpy as np

from app.core.intersection_duration_learning import duration_arrays
from app.core.intersection_signal_filter import JointSignalFilter, TransitionPrior
from app.experimental.intersection_local_filter import LocalObservationSource


def trajectory_duration_law(stats, period, k, clearance):
    """Quantile fit, with an explicit one-second grid floor and 2% tail prior.

    These are trajectory-phase intervals, not independently measured green times.
    The clearance hypotheses express that uncalibrated semantic uncertainty.
    """
    total=max(2.,stats.get('median_s') or period/k)
    lo=stats.get('p10_s') or total*.7
    hi=stats.get('p90_s') or total*1.3
    median=max(2.,total-clearance)
    sigma=max(1/median,(math.log(max(1.,hi-clearance))-math.log(max(1.,lo-clearance)))/2.563)
    return dict(green_median_s=median,log_sigma=sigma,tail_probability=.02,tail_mean_s=4*median)


class TimingHypothesis(JointSignalFilter):
    def __init__(self,model,clearance,*,tail_probability=.02):
        super().__init__(model,transition_prior=TransitionPrior(clearance_s=clearance),history_lag_s=0)
        for i,r in enumerate(model['regimes']):
            survivals=[]
            for z,name in enumerate(r['phase_names']):
                law=trajectory_duration_law(r['phase_durations'][name],r['period_s'],r['phase_count'],clearance)
                law['tail_probability']=tail_probability
                self.hazards[i][z],survival=duration_arrays(law,self.age_cap)
                self.medians[i][z]=law['green_median_s'];survivals.append(survival)
            bank=np.asarray(survivals);bank/=bank.sum()*len(model['regimes'])
            self.green[i]=bank.copy();self.initial[i]=bank.copy()


class TimingEnsembleIntersection:
    """Finite intergreen hypotheses, updated from currently available vehicles."""
    VERSION='experimental-joint-timing-ensemble-v1'
    DURATION_TAIL_PROBABILITY=.02
    USE_TRAJECTORY_AGE_PRIOR=True

    def __init__(self,model,*,point_estimator='configuration'):
        if point_estimator not in ('configuration','joint_state'):raise ValueError('invalid point estimator')
        self.point_estimator=point_estimator
        self.source=LocalObservationSource(model)
        self.filters=[TimingHypothesis(model,c,tail_probability=self.DURATION_TAIL_PROBABILITY) for c in range(3,11)]
        for f in self.filters:f.use_restart_age_prior=self.USE_TRAJECTORY_AGE_PRIOR
        self.weights=np.full(len(self.filters),1/len(self.filters))
        self.keys={};self.last_ms=None

    def ingest(self,packet):
        # Source validates the entire packet before any hypothesis is advanced.
        old={k:t.get('last_restart_ms',-1) for k,t in self.source.motion.tracks.items()}
        base,q,legacy,marks,lags=self.source.ingest(packet)
        self.restart_changes=[t for k,t in self.source.motion.tracks.items()
                              if t.get('last_restart_ms',-1)>old.get(k,-1)]
        now=packet['timestamp_ms'];blocked=self.source.queues.blocked
        if self.last_ms is not None and now-self.last_ms>self.filters[0].age_cap*1000:
            self.weights[:]=1/len(self.filters)
        self.last_ms=now
        results,deltas=self._tick_hypotheses(now,q,legacy,blocked)
        log_weights=np.log(np.maximum(1e-12,self.weights))+deltas
        self.weights=np.exp(log_weights-log_weights.max());self.weights/=self.weights.sum()
        return self._summarize(base,results,q,blocked)

    def _tick_hypotheses(self,now,q,legacy,blocked):
        results=[];deltas=[]
        for f in self.filters:
            before=f.log_evidence
            results.append(f.tick(now,legacy,near_restarts=q['restarts'],passages=q['passages'],
                                  stops=q['stops'],braking=q['braking'],blocked=blocked))
            deltas.append(f.log_evidence-before)
        return results,np.asarray(deltas)

    def _summarize(self,base,results,q,blocked):
        configurations={};color_marginals={a:{} for a in self.source.motion.model['approaches']}
        best_point=(-1,None,None)
        for hypothesis,(weight,f) in enumerate(zip(self.weights,self.filters)):
            votes=np.zeros(len(f.configurations))
            for index,(r,kind,z,nxt,second) in f.locations:
                votes[index]+=float(f.green[r][z].sum() if kind=='green' else f.edge[r][z,nxt,second])
                point=float(weight*(f.green[r][z].max() if kind=='green' else f.edge[r][z,nxt,second]))
                if point>best_point[0]:best_point=(point,hypothesis,index)
            for c,vote in zip(f.configurations,votes):
                key=json.dumps(c,sort_keys=True,separators=(',',':'))
                if key not in configurations:configurations[key]=[c,0.]
                mass=float(weight*vote);configurations[key][1]+=mass
                for a,h in c.items():
                    state=h['main']['state'];color_marginals[a][state]=color_marginals[a].get(state,0.)+mass
        selected,mass=max(configurations.values(),key=lambda pair:pair[1])
        best=results[int(self.weights.argmax())]
        if self.point_estimator=='joint_state':
            _,hypothesis,index=best_point
            best=results[hypothesis];selected=self.filters[hypothesis].configurations[index]
            key=json.dumps(selected,sort_keys=True,separators=(',',':'));mass=configurations[key][1]
        heads=deepcopy(selected)
        recent=best['status']=='TRACKING'
        supported=recent and (best['phase_confidence']>=.5 if self.point_estimator=='joint_state' else mass>=.5)
        for a,h in heads.items():
            color=h['main']['state'];confidence=color_marginals[a].get(color,0.)
            h['main'].update(state=color if supported else 'UNKNOWN',confidence=confidence,
                             source='JOINT_TIMING_HYPOTHESES' if supported else 'INSUFFICIENT_CURRENT_EVIDENCE')
            for arrow in h['arrows']:
                if not supported:arrow['state']='UNKNOWN'
                arrow.update(confidence=mass,source='JOINT_TIMING_HYPOTHESES')
        base.update(best)
        base.update(schema=self.VERSION,heads=heads,production_enabled=False,
            point_estimator=self.point_estimator,
            joint_configuration_confidence=mass,
            intergreen_hypotheses=[dict(clearance_s=f.prior.clearance_s,probability=float(w))
                                  for w,f in zip(self.weights,self.filters)],
            duration_basis='TRAJECTORY_QUANTILES_AND_LATENT_INTERGREEN',
            observation_channels={k:len(q[k]) for k in ('restarts','passages','stops','braking')},
            obstruction_probability=dict(blocked),
            confidence_semantics='UNCALIBRATED_JOINT_TIMING_POSTERIOR_NOT_OBSERVED_LAMPS')
        return base
