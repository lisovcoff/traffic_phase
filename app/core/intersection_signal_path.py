"""Maximum-probability paths on the SAME joint color/duration state graph.

An instantaneous point estimate can revise its recent path. Committed history
uses a declared fixed lag and discards paths contradicting earlier commitments.
Resynchronization is an explicit low-probability graph transition, never an
unreported fabrication of intermediate yellow states.
"""
from collections import deque
import numpy as np


def logarithm(x):
    result=np.full(np.shape(x),-np.inf,dtype=float)
    np.log(x,out=result,where=np.asarray(x)>0)
    return result


class SignalPath:
    def __init__(self,filter,lag_s=10):
        if type(lag_s) is not int or not 0<=lag_s<=30:raise ValueError('invalid path lag')
        self.filter=filter;self.lag_s=lag_s;self.last_ms=None;self.pointers=deque()
        self.gid=[];self.eid=[];offset=0
        for array,target in [(a,self.gid) for a in filter.green]+[(a,self.eid) for a in filter.edge]:
            target.append(np.arange(offset,offset+array.size).reshape(array.shape));offset+=array.size
        self.size=offset;self.delta=None;self.location=np.zeros(offset,dtype=int)
        for config,(r,kind,p,n,t) in filter.locations:
            if kind=='green':self.location[self.gid[r][p]]=config
            else:self.location[self.eid[r][p,n,t]]=config

    def update(self,now,predicted_g,predicted_e,current_g,current_e):
        f=self.filter;continuous=self.last_ms is not None and now-self.last_ms==1000
        if continuous:
            score=np.full(self.size,-np.inf);previous=np.full(self.size,-1,dtype=np.int32)
            best=int(np.argmax(self.delta));stay=np.log(.9999)
            for i,(gids,eids,hazard,transition,initial) in enumerate(zip(self.gid,self.eid,f.hazards,f.transitions,f.initial)):
                dg=self.delta[gids];de=self.delta[eids];remain=dg+logarithm(1-hazard)+stay
                score[gids[:,1:]]=remain[:,:-1];previous[gids[:,1:]]=gids[:,:-1]
                overflow=remain[:,-1]>score[gids[:,-1]]
                score[gids[:,-1]]=np.maximum(score[gids[:,-1]],remain[:,-1])
                previous[gids[:,-1]]=np.where(overflow,gids[:,-1],previous[gids[:,-1]])
                incoming=de[:,:,-1];source=np.argmax(incoming,axis=0);targets=np.arange(len(gids))
                score[gids[:,0]]=incoming[source,targets]+stay
                previous[gids[:,0]]=eids[source,targets,-1]
                leaving=dg+logarithm(hazard);age=np.argmax(leaving,axis=1)
                score[eids[:,:,0]]=leaving[np.arange(len(gids)),age][:,None]+logarithm(transition)+stay
                previous[eids[:,:,0]]=np.broadcast_to(gids[np.arange(len(gids)),age][:,None],transition.shape)
                score[eids[:,:,1:]]=de[:,:,:-1]+stay;previous[eids[:,:,1:]]=eids[:,:,:-1]
                reset=self.delta[best]+np.log(.0001)+logarithm(initial)
                replace=reset>score[gids];score[gids]=np.maximum(reset,score[gids])
                previous[gids]=np.where(replace,best,previous[gids])
        else:
            self.pointers.clear();score=np.full(self.size,-np.inf);previous=np.full(self.size,-1,dtype=np.int32)
            for gids,initial in zip(self.gid,f.initial):score[gids]=logarithm(initial)
        for ids,predicted,current in zip(self.gid+self.eid,predicted_g+predicted_e,current_g+current_e):
            likelihood=np.divide(current,predicted,out=np.zeros_like(current),where=predicted>0)
            score[ids]+=logarithm(likelihood)
        if not np.isfinite(score).any():raise ValueError('empty joint path support')
        score-=float(np.max(score));self.delta=score;self.last_ms=now
        self.pointers.append((now,previous));state=int(np.argmax(score));current_config=int(self.location[state]);history=None
        if len(self.pointers)>self.lag_s:
            ancestors=np.arange(self.size)
            for _,pointer in list(self.pointers)[1:][::-1]:ancestors=pointer[ancestors]
            committed=int(ancestors[state]);time,_=self.pointers.popleft()
            self.delta[ancestors!=committed]=-np.inf
            history=dict(timestamp_ms=time,available_at_ms=now,delay_s=self.lag_s,
                         heads=f.configurations[int(self.location[committed])],
                         estimate_kind='COMMITTED_FIXED_LAG_JOINT_PATH',observed_lamp=False)
        return dict(timestamp_ms=now,heads=f.configurations[current_config],
                    estimate_kind='PROVISIONAL_JOINT_PATH',history=history)
