"""Causal local timing conditioned on approach, avoiding traffic-volume mode bias."""
import numpy as np
from app.core.intersection_local_emissions import duration_age_weights
from app.core.intersection_signal_filter import JointSignalFilter
from app.experimental.intersection_local_filter import LocalEmissionFilter,LocalObservationSource,LocalProfileIntersection


class ConditionedLocalFilter(LocalEmissionFilter):
    def __init__(self,model,**kwargs):
        super().__init__(model,**kwargs);support=[]
        for i,r in enumerate(model['regimes']):
            profile=r.get('causal_local_emissions')
            if profile is None:continue
            p=np.array(profile['probabilities'],dtype=float);names=profile['alphabet']
            # Condition on the approach currently observed. Absolute N/S/E/W
            # demand ratios in a training hour must not select a timing regime.
            for a in model['approaches']:
                ix=[j for j,n in enumerate(names) if n.endswith(':'+a)]
                p[:,:,ix]/=p[:,:,ix].sum(axis=2,keepdims=True)*len(model['approaches'])
            green=[];edge=[]
            for z,median in enumerate(self.medians[i]):
                w=duration_age_weights(self.hazards[i][z],median,self.prior.clearance_s,profile['bins'])
                green.append(w@p[z]);ix=np.minimum(profile['bins']-1,
                    ((median+np.arange(self.prior.clearance_s))/(median+self.prior.clearance_s)*profile['bins']).astype(int))
                edge.append(p[z,ix])
            self.learned[i]=np.array(green);self.learned_edge[i]=np.array(edge)
            support.append(np.asarray(profile['counts']).sum(axis=(0,1))>=8)
        self.support=np.logical_and.reduce(support) if support else np.zeros(len(self.mark_index),dtype=bool)

    def observe(self,events,kind='LEGACY'):
        for a,b,w in events:
            channel=('LEGACY_RESTART' if w>=1 else 'LEGACY_EXIT') if kind=='LEGACY' else kind
            if self.support[self.mark_index[channel+':'+a]]:self.positive(channel,a,b,w)
            else:JointSignalFilter.observe(self,[(a,b,w)],kind)

    def observe_stops(self,origins,blocked,*,braking=False):
        for a in origins:
            channel='BRAKE' if braking else 'STOP'
            if self.support[self.mark_index[channel+':'+a]]:
                self.positive(channel,a,None,.4 if braking else .6,blocked.get(a,.03))
            else:JointSignalFilter.observe_stops(self,[a],blocked,braking=braking)


class ConditionedLocalIntersection(LocalProfileIntersection):
    def __init__(self,model,*,history_lag_s=10):
        self.source=LocalObservationSource(model);self.filter=ConditionedLocalFilter(model,history_lag_s=history_lag_s)

    def ingest(self,packet):
        result=super().ingest(packet);result['schema']='experimental-conditioned-local-age-v1'
        result['local_emission_basis']='CAUSAL_CHANNEL_AGE_CONDITIONED_ON_OBSERVED_APPROACH'
        return result
