"""Bounded causal fixed-lag reconstruction for the joint signal state model.

This uses observations received AFTER the reconstructed second, up to the stated
availability time. It is never an instantaneous estimate or an observed lamp.
"""
from collections import deque
import numpy as np


class FixedLagSignals:
    def __init__(self,filter,lag_s):
        if type(lag_s) is not int or not 0<=lag_s<=30:raise ValueError('lag must be 0..30 seconds')
        self.filter=filter;self.lag_s=lag_s;self.rows=deque()

    def backward(self,green,edge):
        """Apply the transpose of exactly the forward one-second transition."""
        f=self.filter;result_g=[];result_e=[]
        reset=sum(float((initial*b).sum()) for initial,b in zip(f.initial,green))*.0001
        for i,(g,e) in enumerate(zip(green,edge)):
            # Last age is an overflow bin that remains at the last age.
            surviving=np.c_[g[:,1:],g[:,-1]]
            leaving=(f.transitions[i]*e[:,:,0]).sum(axis=1)
            previous_g=(1-f.hazards[i])*surviving+f.hazards[i]*leaving[:,None]
            previous_e=np.zeros_like(e);previous_e[:,:,:-1]=e[:,:,1:]
            previous_e[:,:,-1]=g[:,0][None,:]
            result_g.append(previous_g*.9999+reset);result_e.append(previous_e*.9999+reset)
        return result_g,result_e

    def push(self,now,predicted_g,predicted_e,current_g,current_e,evidence_ms):
        if not self.lag_s:return None
        if self.rows and now-self.rows[-1]['time']!=1000:self.rows.clear()
        emissions=[]
        for prior,posterior in zip(predicted_g+predicted_e,current_g+current_e):
            emission=np.divide(posterior,prior,out=np.zeros_like(prior),where=prior>0)
            emissions.append(emission)
        scale=max(max(float(e.max()) for e in emissions),1e-300)
        n=len(current_g)
        self.rows.append(dict(time=now,g=[g.copy() for g in current_g],e=[e.copy() for e in current_e],
                              likelihood_g=[e/scale for e in emissions[:n]],
                              likelihood_e=[e/scale for e in emissions[n:]],evidence_ms=evidence_ms))
        if len(self.rows)<=self.lag_s:return None
        bg=[np.ones_like(g) for g in current_g];be=[np.ones_like(e) for e in current_e]
        for row in list(self.rows)[1:][::-1]:
            bg,be=self.backward([b*l for b,l in zip(bg,row['likelihood_g'])],
                                [b*l for b,l in zip(be,row['likelihood_e'])])
            scale=max(max(float(b.max()) for b in bg+be),1e-300)
            bg=[b/scale for b in bg];be=[b/scale for b in be]
        row=self.rows.popleft();g=[a*b for a,b in zip(row['g'],bg)];e=[a*b for a,b in zip(row['e'],be)]
        total=sum(float(a.sum()+b.sum()) for a,b in zip(g,e))
        if total<=0:raise ValueError('empty fixed-lag posterior')
        return dict(timestamp_ms=row['time'],available_at_ms=now,delay_s=self.lag_s,
                    green=[a/total for a in g],edge=[b/total for b in e],evidence_ms=row['evidence_ms'])
