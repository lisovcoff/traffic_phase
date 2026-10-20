"""Bounded observed-onset correction for joint timing hypotheses; default-off.

Only data already received can revise the CURRENT posterior. The earlier issued
output is immutable. An onset is a vehicle-motion estimate, never a lamp label.
"""
import math

import numpy as np

from app.experimental.intersection_timing_ensemble import TimingEnsembleIntersection


class EventTimeTimingIntersection(TimingEnsembleIntersection):
    VERSION='experimental-joint-event-time-timing-v1'

    def __init__(self,model):
        super().__init__(model)
        self.rows=[];self.anchors=[self.snapshot(f) for f in self.filters]
        self.corrected=[]

    @staticmethod
    def snapshot(f):
        return dict(g=[a.copy() for a in f.green],e=[a.copy() for a in f.edge],
                    last=f.last_ms,evidence=f.evidence_ms,log_evidence=f.log_evidence)

    @staticmethod
    def restore(f,state):
        f.green=[a.copy() for a in state['g']];f.edge=[a.copy() for a in state['e']]
        f.last_ms=state['last'];f.evidence_ms=state['evidence'];f.log_evidence=state['log_evidence']

    def _tick_hypotheses(self,now,q,legacy,blocked):
        if self.rows and now-self.rows[-1]['now']!=1000:
            self.rows.clear();self.anchors=[self.snapshot(f) for f in self.filters]
        row=dict(now=now,legacy=[e for e in legacy if e[2]<1],restarts=[],
                 passages=q['passages'],stops=q['stops'],braking=q['braking'],blocked=dict(blocked))
        self.rows.append(row);first=self.rows[0]['now'];onsets={}
        for t in self.restart_changes:
            onset=t['last_restart_ms']
            if not 0<=now-onset<=8000:continue
            key=(t['origin'],t['target']);onsets[key]=max(onsets.get(key,onset),onset)
        self.corrected=[]
        for kind,events in [('legacy',[e for e in legacy if e[2]>=1]),('restarts',q['restarts'])]:
            for a,b,w in events:
                onset=onsets.get((a,b),now)
                assigned=max(first,first+math.ceil((onset-first)/1000)*1000)
                destination=next((r for r in self.rows if r['now']==assigned),row)
                destination[kind].append((a,b,w))
                self.corrected.append(dict(origin=a,onset_estimate_ms=onset,assigned_ms=destination['now'],
                                           available_at_ms=now,clipped_to_buffer=onset<first))
        results=[];deltas=[];new_anchors=[]
        for f,anchor in zip(self.filters,self.anchors):
            previous_score=f.log_evidence;self.restore(f,anchor)
            after_first=None
            for i,r in enumerate(self.rows):
                result=f.tick(r['now'],r['legacy'],near_restarts=r['restarts'],passages=r['passages'],
                              stops=r['stops'],braking=r['braking'],blocked=r['blocked'])
                if i==0:after_first=self.snapshot(f)
            new_anchors.append(after_first);results.append(result)
            deltas.append(f.log_evidence-previous_score)
        if len(self.rows)>8:
            self.rows.pop(0);self.anchors=new_anchors
        return results,np.asarray(deltas)

    def _summarize(self,base,results,q,blocked):
        result=super()._summarize(base,results,q,blocked)
        result.update(corrected_restart_observations=list(self.corrected),correction_buffer_s=8,
                      correction_basis='OBSERVED_VEHICLE_ONSET_NOT_SIGNAL_ONSET')
        return result
