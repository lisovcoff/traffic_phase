"""Default-off waiting-time likelihood paired with queue-front release ages.

Continued position-supported waiting is an observation; absent traffic is not.
The same uncertain reaction interval governs release ages and waiting survival.
"""
import numpy as np

from app.experimental.intersection_front_release import FrontReleaseTimingIntersection,stopped_front


def waiting_survival(age,reaction_bound,contamination):
    return contamination+(1-contamination)*np.clip(1-np.asarray(age)/reaction_bound,0,1)


class FrontWaitingTimingIntersection(FrontReleaseTimingIntersection):
    VERSION='experimental-front-waiting-timing-v2'

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
            if (reference is None or now-track['last_ms']>1000
                    or now-track.get('last_restart_ms',-100000)<8000
                    or blocked.get(origin,.03)>=.5):continue
            if stopped_front(track,reference,now):origins.add(origin)
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
