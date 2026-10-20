"""Default-off joint filter with offline learned causal local-age emissions."""
import numpy as np
from app.core.intersection_online import CausalIntersection
from app.core.intersection_queue_observations import QueueObservations
from app.core.intersection_signal_filter import JointSignalFilter
from app.core.intersection_local_emissions import alphabet,duration_age_weights


class LocalObservationSource:
    """Identical causal motion/queue extraction in training and inference."""
    def __init__(self,model):
        self.motion=CausalIntersection(model);self.queues=QueueObservations(model.get('queue_observations',{}))
        self.events=[]
        # Motion extraction does not read phase banks. Avoid computing a second
        # unused signal filter; keep the same validation/track/target/render path.
        self.motion._advance=lambda seconds:None
        self.motion._observe=self._collect_events

    def _collect_events(self,events):
        # A bound Python method follows its source through deepcopy in the
        # transactional online store. A closure keeps mutating the old source.
        self.events.extend(events)

    def ingest(self,packet):
        self.events.clear();old={k:t.get('last_restart_ms',-1) for k,t in self.motion.tracks.items()}
        base=self.motion.ingest(packet)
        local=self.queues.extract(self.motion.tracks,[v['id'] for v in packet['vehicles']],packet['timestamp_ms'],old)
        legacy=[e for e in self.events if e[0] not in local['covered']]
        marks=[]
        for a,b,w in legacy:marks.append(('LEGACY_RESTART' if w>=1 else 'LEGACY_EXIT',a))
        for kind,key in [('NEAR_RESTART','restarts'),('PASSAGE','passages')]:
            marks.extend((kind,a) for a,b,w in local[key])
        marks.extend(('STOP',a) for a in local['stops']);marks.extend(('BRAKE',a) for a in local['braking'])
        lags=[]
        for vehicle in packet['vehicles']:
            key=str(vehicle['id']);t=self.motion.tracks.get(key)
            if t and t.get('last_restart_ms',-1)>old.get(key,-1):
                lags.append((t['origin'],packet['timestamp_ms']-t['last_restart_ms']))
        return base,local,legacy,marks,lags


class LocalEmissionFilter(JointSignalFilter):
    def __init__(self,model,**kwargs):
        super().__init__(model,**kwargs);self.learned=[];self.learned_edge=[]
        names=alphabet(model['approaches']);self.mark_index={n:i for i,n in enumerate(names)}
        for i,r in enumerate(model['regimes']):
            profile=r.get('causal_local_emissions')
            if not profile:
                self.learned.append(None);self.learned_edge.append(None);continue
            if profile['alphabet']!=names:raise ValueError('incompatible local-observation alphabet')
            p=np.asarray(profile['probabilities'],dtype=float)
            if (p.shape!=(r['phase_count'],profile['bins'],len(names)) or not np.isfinite(p).all()
                    or np.any(p<=0) or not np.allclose(p.sum(axis=2),1)):
                raise ValueError('invalid local-observation probabilities')
            green=[];edge=[]
            for z,median in enumerate(self.medians[i]):
                weights=duration_age_weights(self.hazards[i][z],median,self.prior.clearance_s,profile['bins'])
                green.append(weights@p[z])
                index=np.minimum(profile['bins']-1,((median+np.arange(self.prior.clearance_s))/
                                  (median+self.prior.clearance_s)*profile['bins']).astype(int))
                edge.append(p[z,index])
            self.learned.append(np.array(green));self.learned_edge.append(np.array(edge))
        if any(p is not None for p in self.learned) and any(p is None for p in self.learned):
            raise ValueError('local-observation profiles must cover all saved regimes')

    def positive(self,kind,origin,target,weight,obstruction=0.):
        key=self.mark_index[kind+':'+origin]
        known=self.marks.likelihoods(origin,target) if target is not None else None
        marginal=self.marks.likelihoods(origin,None) if target is not None else None
        for i in range(len(self.green)):
            if self.learned[i] is None:continue
            lg=self.learned[i][:,:,key];le=self.learned_edge[i][:,:,key]
            # A known destination supplies P(target | origin, phase), avoiding
            # counting the origin composition twice. No future target is used.
            if known is not None:
                conditional=np.clip(known[i]/np.maximum(1e-12,marginal[i]),.001,1)
                lg=lg*conditional[:,None];le=le*conditional[:,None]
            uniform=1/len(self.mark_index)
            contamination=.2+.7*obstruction if kind in ('STOP','BRAKE') else .2
            lg=(1-contamination)*lg+contamination*uniform
            le=(1-contamination)*le+contamination*uniform
            self.green[i]*=np.maximum(1e-12,lg)**weight
            self.edge[i]*=np.maximum(1e-12,le[:,None,:])**weight
        total=sum(float(g.sum()+e.sum()) for g,e in zip(self.green,self.edge))
        for g,e in zip(self.green,self.edge):g/=max(total,1e-300);e/=max(total,1e-300)

    def observe(self,events,kind='LEGACY'):
        if not any(p is not None for p in self.learned):return super().observe(events,kind)
        for a,b,w in events:
            channel=('LEGACY_RESTART' if w>=1 else 'LEGACY_EXIT') if kind=='LEGACY' else kind
            self.positive(channel,a,b,w)

    def observe_stops(self,origins,blocked,*,braking=False):
        if not any(p is not None for p in self.learned):return super().observe_stops(origins,blocked,braking=braking)
        for a in origins:self.positive('BRAKE' if braking else 'STOP',a,None,.4 if braking else .6,blocked.get(a,.03))


class LocalProfileIntersection:
    def __init__(self,model,*,history_lag_s=10):
        self.source=LocalObservationSource(model)
        self.filter=LocalEmissionFilter(model,history_lag_s=history_lag_s)

    def ingest(self,packet):
        result,q,legacy,marks,lags=self.source.ingest(packet)
        local=q['restarts']+q['passages'];blocked=self.source.queues.blocked
        for origin in q['stops']+q['braking']:
            previous=getattr(self.filter,'color_marginals',{}).get(origin,{}).get('GREEN',0.)
            if previous>.8 and any(a!=origin and getattr(self.filter,'color_marginals',{}).get(a,{}).get('GREEN',0.)>.8 for a,b,w in local):
                blocked[origin]=max(.8,blocked[origin])
        result.update(self.filter.tick(packet['timestamp_ms'],legacy,near_restarts=q['restarts'],passages=q['passages'],
            stops=q['stops'],braking=q['braking'],blocked=blocked))
        result.update(schema='experimental-causal-local-age-v1',
            observation_channels={k:len(q[k]) for k in ('restarts','passages','stops','braking')},
            observation_time_basis='LEARNED_CAUSAL_CONFIRMATION_AGE_NOT_PHYSICAL_LAMP_LATENCY',
            obstruction_probability=dict(blocked),production_enabled=False)
        return result
