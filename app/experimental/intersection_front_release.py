"""Default-off age resynchronization from a stopped queue-front vehicle.

A restart is not a measured GREEN onset. The bounded reaction interval below
is an uncalibrated hypothesis, with an explicit unchanged-age contamination.
No phase, section, absolute clock or video label is supplied externally.
"""
from copy import deepcopy

import numpy as np

from app.core.intersection_queue_observations import metric_xy
from app.experimental.intersection_adaptive_timing import AdaptiveRobustTimingIntersection


def stopped_front(track, reference, onset_ms):
    """Require position-supported waiting at the learned front before restart."""
    points=[d for d in track['points'] if onset_ms-3500<=d['millis']<onset_ms]
    if len(points)<3 or points[-1]['millis']-points[0]['millis']<1500:return False
    if onset_ms-points[-1]['millis']>2000:return False
    if any(b['millis']-a['millis']>2000 for a,b in zip(points,points[1:])):return False
    if any(str(d.get('zone'))!=track['origin'] for d in points):return False
    xy=[metric_xy(d,reference['anchor_lat_lng']) for d in points]
    if any(p is None for p in xy):return False
    xy=np.asarray(xy)
    if np.max(np.linalg.norm(xy-xy[-1],axis=1))>1.2:return False
    offset=xy[-1]-np.asarray(reference['point_m']);heading=np.asarray(reference['heading'])
    lateral=float(offset@np.array([-heading[1],heading[0]]))
    return abs(float(offset@heading))<=3 and abs(lateral)<=reference['lateral_radius_m']


class FrontReleaseTimingIntersection(AdaptiveRobustTimingIntersection):
    VERSION='experimental-front-release-timing-v1'
    RELEASE_REACTION_BOUND_S=4.
    RELEASE_REJUVENATION=.8

    def __init__(self,model):
        super().__init__(model)
        self.release_age_observations=[]

    def _tick_hypotheses(self,now,q,legacy,blocked):
        results,deltas=super()._tick_hypotheses(now,q,legacy,blocked)
        self.release_age_observations=[]
        masses=sum(float(w)*np.asarray([g.sum()+e.sum() for g,e in zip(f.green,f.edge)])
                   for w,f in zip(self.weights,self.filters))
        regime=int(masses.argmax())
        if masses[regime]<.85:return results,deltas
        groups={(a,b) for a,b,_ in q['restarts']};observed={}
        for track in self.restart_changes:
            origin=track['origin'];target=track['target']
            onset=track['last_restart_ms'];reference=self.source.queues.references.get(origin)
            if ((origin,target) not in groups or reference is None or blocked.get(origin,.03)>=.5
                    or not 0<=now-onset<=8000 or not stopped_front(track,reference,onset)):continue
            values=self.filters[0].marks.likelihoods(origin,target)[regime];order=np.argsort(values)
            if len(order)<2 or values[order[-1]]<4*values[order[-2]]:continue
            phase=int(order[-1])
            # Correlated heads/cars in the same phase supply one age update.
            if phase not in observed or onset<observed[phase]['onset_ms']:
                observed[phase]=dict(phase=phase,regime_index=regime,origin=origin,
                                     onset_ms=onset,available_at_ms=now)
        for phase,observation in observed.items():
            lag=(now-observation['onset_ms'])/1000
            for f in self.filters:
                ages=np.arange(f.age_cap+1)
                support=(ages>=lag)&(ages<=lag+self.RELEASE_REACTION_BOUND_S)
                if not support.any():continue
                prior=support/support.sum();bank=f.green[regime][phase];mass=float(bank.sum())
                # Preserve phase/regime mass and explicit transition states.
                # Only the current conditional GREEN-age distribution changes.
                bank[:]=(1-self.RELEASE_REJUVENATION)*bank+self.RELEASE_REJUVENATION*mass*prior
            self.release_age_observations.append(observation)
        if observed:
            results=[f.summarize(now,f.green,f.edge,f.evidence_ms,cache_current=True) for f in self.filters]
        return results,deltas

    def _summarize(self,base,results,q,blocked):
        result=super()._summarize(base,results,q,blocked)
        result.update(front_release_age_observations=deepcopy(self.release_age_observations),
                      front_release_age_prior=dict(reaction_bound_s=self.RELEASE_REACTION_BOUND_S,
                          rejuvenation=self.RELEASE_REJUVENATION,calibration='UNCALIBRATED_NOT_LAMP_TRUTH'))
        return result
