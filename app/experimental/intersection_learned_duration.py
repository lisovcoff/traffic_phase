"""Default-off learned duration law plus the same causal local observation model."""
import numpy as np
from app.core.intersection_duration_learning import duration_arrays
from app.core.intersection_local_emissions import duration_age_weights
from app.experimental.intersection_local_filter import LocalEmissionFilter,LocalProfileIntersection,LocalObservationSource


class LearnedDurationFilter(LocalEmissionFilter):
    def __init__(self,model,**kwargs):
        super().__init__(model,**kwargs)
        for i,r in enumerate(model['regimes']):
            laws=r.get('causal_duration_laws')
            if not laws or any(law is None for law in laws):continue
            survival=[]
            for z,law in enumerate(laws):
                hazard,prior=duration_arrays(law,self.age_cap)
                self.hazards[i][z]=hazard;survival.append(prior);self.medians[i][z]=law['green_median_s']
            bank=np.array(survival);bank/=bank.sum()*len(model['regimes'])
            self.green[i]=bank.copy();self.initial[i]=bank.copy()
            if self.learned[i] is not None:
                profile=r['causal_local_emissions'];p=np.asarray(profile['probabilities']);green=[];edge=[]
                for z,median in enumerate(self.medians[i]):
                    w=duration_age_weights(self.hazards[i][z],median,self.prior.clearance_s,profile['bins']);green.append(w@p[z])
                    ix=np.minimum(profile['bins']-1,((median+np.arange(self.prior.clearance_s))/
                        (median+self.prior.clearance_s)*profile['bins']).astype(int));edge.append(p[z,ix])
                self.learned[i]=np.array(green);self.learned_edge[i]=np.array(edge)


class LearnedDurationIntersection(LocalProfileIntersection):
    def __init__(self,model,*,history_lag_s=10):
        self.source=LocalObservationSource(model);self.filter=LearnedDurationFilter(model,history_lag_s=history_lag_s)

    def ingest(self,packet):
        result=super().ingest(packet);result['schema']='experimental-local-learned-duration-v1'
        result['duration_basis']='OFFLINE_ROBUST_DURATION_AND_CAUSAL_CONFIRMATION_AGE'
        return result
