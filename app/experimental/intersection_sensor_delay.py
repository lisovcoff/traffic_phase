"""Bounded out-of-sequence restart observations on the original joint model.

Only an already observed detector onset is retimed. No reaction-to-GREEN delay
is invented. Past issued predictions are immutable; reconstruction has an explicit
availability timestamp. All other observation likelihoods remain coherent v5.
"""
import math
import numpy as np
from app.core.intersection_queue_observations import metric_xy
from app.core.intersection_signal_filter import JointSignalFilter
from app.core.intersection_signal_smoothing import FixedLagSignals
from app.experimental.intersection_local_filter import LocalObservationSource


class SensorDelayIntersection:
    def __init__(self,model,*,history_lag_s=10):
        if type(history_lag_s) is not int or not 8<=history_lag_s<=30:
            raise ValueError('history must cover the detector maximum 8s confirmation delay')
        self.source=LocalObservationSource(model);self.filter=JointSignalFilter(model,history_lag_s=0)
        self.lag=history_lag_s;self.rows=[];self.anchor=self.snapshot();self.last_ms=None

    def snapshot(self):
        f=self.filter
        return dict(g=[a.copy() for a in f.green],e=[a.copy() for a in f.edge],last=f.last_ms,evidence=f.evidence_ms)

    def restore(self,state):
        f=self.filter;f.green=[a.copy() for a in state['g']];f.edge=[a.copy() for a in state['e']]
        f.last_ms=state['last'];f.evidence_ms=state['evidence'];f.smoother=FixedLagSignals(f,self.lag)

    def ingest(self,packet):
        now=packet['timestamp_ms']
        if type(now) is not int or now<0:raise ValueError('invalid observation timestamp')
        old={k:t.get('last_restart_ms',-1) for k,t in self.source.motion.tracks.items()}
        base,q,legacy,marks,lags=self.source.ingest(packet)  # validation before modifying the correction buffer
        local=q['restarts']+q['passages'];blocked=self.source.queues.blocked
        for origin in q['stops']+q['braking']:
            previous=getattr(self.filter,'color_marginals',{}).get(origin,{}).get('GREEN',0.)
            if previous>.8 and any(a!=origin and getattr(self.filter,'color_marginals',{}).get(a,{}).get('GREEN',0.)>.8 for a,b,w in local):
                blocked[origin]=max(.8,blocked[origin])
        if self.last_ms is not None and now-self.last_ms!=1000:
            self.rows.clear();self.anchor=self.snapshot()
        current=dict(now=now,legacy=[e for e in legacy if e[2]<1],restarts=[],passages=q['passages'],
                     stops=q['stops'],braking=q['braking'],blocked=dict(blocked))
        self.rows.append(current);onsets={};near_onsets={}
        for vehicle in packet['vehicles']:
            key=str(vehicle['id']);track=self.source.motion.tracks.get(key)
            if not track:continue
            onset=track.get('last_restart_ms',-1)
            if onset<=old.get(key,-1) or not 0<=now-onset<=8000:continue
            group=(track['origin'],track['target']);onsets[group]=max(onsets.get(group,onset),onset)
            ref=self.source.queues.references.get(track['origin'])
            if ref and track['points']:
                point=metric_xy(track['points'][-1],ref['anchor_lat_lng'])
                if point is not None:
                    d=point-np.asarray(ref['point_m']);heading=np.asarray(ref['heading'])
                    if (-8<=float(d@heading)<=5 and abs(float(d@[-heading[1],heading[0]]))<=ref['lateral_radius_m']):
                        near_onsets[group]=max(near_onsets.get(group,onset),onset)
        moved=[]
        for kind,events,times in [('legacy',[e for e in legacy if e[2]>=1],onsets),('restarts',q['restarts'],near_onsets)]:
            for a,b,w in events:
                onset=times.get((a,b),now)
                # Reconstruct on the same one-second grid as causal packet arrival.
                first=self.rows[0]['now'];assigned=max(first,first+math.ceil((onset-first)/1000)*1000)
                row=next((r for r in self.rows if r['now']==assigned),current)
                row[kind].append((a,b,w))
                moved.append(dict(kind=kind,onset_estimate_ms=onset,assigned_ms=row['now'],available_at_ms=now,
                                  onset_outside_available_history=onset<first))
        self.restore(self.anchor);after_first=None;result=None
        for i,row in enumerate(self.rows):
            result=self.filter.tick(row['now'],row['legacy'],near_restarts=row['restarts'],passages=row['passages'],
                stops=row['stops'],braking=row['braking'],blocked=row['blocked'])
            if i==0:after_first=self.snapshot()
        if len(self.rows)>self.lag:
            self.rows.pop(0);self.anchor=after_first
        self.last_ms=now;base.update(result)
        base.update(schema='experimental-sensor-confirmation-delay-v1',history_lag_s=self.lag,
            observation_channels={k:len(q[k]) for k in ('restarts','passages','stops','braking')},
            corrected_restart_observations=moved,correction_basis='OBSERVED_RESTART_ONSET_NOT_GREEN_ONSET',
            obstruction_probability=dict(blocked),production_enabled=False)
        return base
