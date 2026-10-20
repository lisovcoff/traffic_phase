"""Default-off waiting-time likelihood paired with queue-front release ages.

Continued position-supported waiting is an observation; absent traffic is not.
The same uncertain reaction interval governs release ages and waiting survival.
"""
import numpy as np

from app.experimental.intersection_front_release import FrontReleaseTimingIntersection,stopped_front
from app.core.intersection_queue_observations import metric_xy


def currently_waiting_front(track,reference,now):
    """The newest motion sample must agree with the preceding stationary run."""
    points=track['points']
    if len(points)<2 or now-points[-1]['millis']>1000:return False
    a,b=points[-2:];dt=(b['millis']-a['millis'])/1000
    if not 0<dt<=2 or str(b.get('zone'))!=track['origin']:return False
    xy=[metric_xy(d,reference['anchor_lat_lng']) for d in (a,b)]
    if any(p is None for p in xy):return False
    # Use the same geographic movement floor as the shared restart extractor;
    # vendor speed may remain stale when a vehicle stops or starts.
    if float(np.linalg.norm(xy[1]-xy[0]))/dt>=.8:return False
    return stopped_front(track,reference,now)


def waiting_survival(age,reaction_bound,contamination):
    return contamination+(1-contamination)*np.clip(1-np.asarray(age)/reaction_bound,0,1)


class FrontWaitingTimingIntersection(FrontReleaseTimingIntersection):
    VERSION='experimental-front-waiting-timing-v4'
    LEADING_BRAKE_WEIGHT=1.

    def __init__(self,model):
        super().__init__(model)
        self.last_waiting_ms=None
        self.waiting_origins=[]

    def _tick_hypotheses(self,now,q,legacy,blocked):
        previous=self.last_waiting_ms
        results,deltas=super()._tick_hypotheses(now,q,legacy,blocked)
        self.last_waiting_ms=now;self.waiting_origins=[]
        if previous is None or now-previous>2000:return results,deltas
        origins=set()
        for track in self.source.motion.tracks.values():
            origin=track['origin'];reference=self.source.queues.references.get(origin)
            # Unknown destinations on a head with additional permissions cannot
            # identify which section the waiting driver needs. Do not turn an
            # arrow queue into negative evidence for the main GREEN.
            if self.source.motion.topology.get(origin,{}).get('arrows'):continue
            if (reference is None or now-track['last_ms']>1000
                    or now-track.get('last_restart_ms',-100000)<8000
                    or blocked.get(origin,.03)>=.5):continue
            if currently_waiting_front(track,reference,now):origins.add(origin)
        for index,f in enumerate(self.filters):
            before=f.log_evidence
            for origin in origins:
                contamination=1-self.RELEASE_REJUVENATION*(1-blocked.get(origin,.03))
                ages=np.arange(f.age_cap+1);dt=(now-previous)/1000
                ratio=waiting_survival(ages,self.RELEASE_REACTION_BOUND_S,contamination)/waiting_survival(
                    np.maximum(0,ages-dt),self.RELEASE_REACTION_BOUND_S,contamination)
                for i,regime in enumerate(f.model['regimes']):
                    for z,heads in enumerate(regime['phase_head_states']):
                        if heads.get(origin,{}).get('main',{}).get('state')=='GREEN':f.green[i][z]*=ratio
                f._normalize_observation()
            deltas[index]+=f.log_evidence-before
            if origins:f.evidence_ms=now
        if origins:
            results=[f.summarize(now,f.green,f.edge,f.evidence_ms,cache_current=True) for f in self.filters]
        self.waiting_origins=sorted(origins)
        return results,deltas

    def _summarize(self,base,results,q,blocked):
        result=super()._summarize(base,results,q,blocked)
        result['continued_front_waiting']=list(self.waiting_origins)
        return result
