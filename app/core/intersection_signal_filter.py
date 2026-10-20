"""Joint phase, duration and physical transition hypotheses.

Candidate successor to the v7 median-color override. A duration hazard transfers
probability from green-bearing configurations into explicit, timed edge states.
Colors are projections of these SAME hypotheses, never a separate latched timer.
All timing priors remain uncalibrated estimates; no lamp/video input is accepted.
"""
from dataclasses import dataclass
import json
import math
import numpy as np

from app.core.intersection_emissions import MovementMarks


@dataclass(frozen=True)
class TransitionPrior:
    yellow_s: int = 3
    red_yellow_s: int = 2
    clearance_s: int = 4

    def __post_init__(self):
        if (any(type(x) is not int for x in (self.yellow_s,self.red_yellow_s,self.clearance_s))
                or not 0 < self.yellow_s <= self.clearance_s
                or not 0 <= self.red_yellow_s <= self.clearance_s):
            raise ValueError('invalid transition duration prior')


def transition_heads(current, following, second, prior):
    """One physical configuration on a learned phase edge.

    Continuing greens stay green across an arrow-only phase change. Additional
    one-lens sections use ON/OFF; their turning-off does not invent main yellow.
    """
    result={}
    for approach in sorted(set(current)|set(following)):
        a=current.get(approach,{});b=following.get(approach,{})
        old=a.get('main',{}).get('state','UNKNOWN');new=b.get('main',{}).get('state','UNKNOWN')
        if old==new:state=old
        elif old=='GREEN' and new=='RED':state='YELLOW' if second<prior.yellow_s else 'RED'
        elif old=='RED' and new=='GREEN':
            state='RED_YELLOW' if second>=prior.clearance_s-prior.red_yellow_s else 'RED'
        else:state='UNKNOWN'
        arrows=[]
        left={v['movement']:v['state'] for v in a.get('arrows',[])}
        right={v['movement']:v['state'] for v in b.get('arrows',[])}
        for movement in sorted(set(left)|set(right)):
            x,y=left.get(movement,'UNKNOWN'),right.get(movement,'UNKNOWN')
            arrows.append(dict(movement=movement,state=x if x==y else (
                'OFF' if x in ('ON','OFF') and y in ('ON','OFF') else 'UNKNOWN')))
        result[approach]=dict(main=dict(state=state),arrows=arrows)
    return result


class JointSignalFilter:
    """Finite semi-Markov filter over saved regimes and explicit phase edges."""
    def __init__(self,model,*,transition_prior=None,point_estimator='joint_state',history_lag_s=10):
        if point_estimator not in ('joint_state','configuration'):raise ValueError('unknown point estimator')
        self.model=model;self.prior=transition_prior or TransitionPrior();self.point_estimator=point_estimator
        self.log_evidence=0.
        self.use_restart_age_prior=True
        self.marks=MovementMarks(model['regimes'],contamination=.2)
        self.age_cap=min(1800,max(180,int(max(r['period_s'] for r in model['regimes'])*4)))
        self.green=[];self.edge=[];self.hazards=[];self.transitions=[];self.initial=[];self.medians=[]
        self.configurations=[];self.groups={};self.last_ms=None;self.evidence_ms=None
        self.topology={a:sorted({m for r in model['regimes'] for m in
            r.get('signal_topology',{}).get(a,{}).get('arrows',[])}) for a in model['approaches']}
        for i,r in enumerate(model['regimes']):
            k=r['phase_count'];survivals=[];hazards=[];medians=[]
            for name in r['phase_names']:
                stats=r['phase_durations'][name]
                total=max(2.,stats['median_s'] or r['period_s']/k)
                med=max(2.,total-self.prior.clearance_s)
                p10=max(1.,(stats['p10_s'] or total*.7)-self.prior.clearance_s)
                p90=max(1.,(stats['p90_s'] or total*1.3)-self.prior.clearance_s)
                sigma=max(.12,(math.log(p90)-math.log(p10))/2.563)
                survival=np.array([.85*.5*math.erfc((math.log(max(.01,a))-math.log(med))/sigma/math.sqrt(2))
                    +.15*math.exp(-a/(4*med)) for a in range(self.age_cap+2)])
                hazards.append(np.clip(1-survival[1:]/survival[:-1],.0001,.5))
                survivals.append(survival[:-1]);medians.append(med)
            bank=np.array(survivals);bank/=bank.sum()*len(model['regimes'])
            self.green.append(bank.copy());self.initial.append(bank.copy())
            self.edge.append(np.zeros((k,k,self.prior.clearance_s)))
            self.hazards.append(np.array(hazards));self.medians.append(medians)
            transition=np.zeros((k,k))
            for row in r.get('observed_transitions',[]):transition[row['source'],row['target']]+=row['observations']
            for z in range(k):
                if not transition[z].sum():transition[z,(z+1)%k]=1
                transition[z]/=transition[z].sum()
            self.transitions.append(transition)
            configurations=r.get('phase_head_states') or [{}]*k
            for z,c in enumerate(configurations):self._register(c,(i,'green',z,None,None))
            for z in range(k):
                for nxt in range(k):
                    if not transition[z,nxt]:continue
                    for second in range(self.prior.clearance_s):
                        c=transition_heads(configurations[z],configurations[nxt],second,self.prior)
                        self._register(c,(i,'edge',z,nxt,second))
        from app.core.intersection_signal_smoothing import FixedLagSignals
        self.smoother=FixedLagSignals(self,history_lag_s)

    def _register(self,heads,location):
        # Identical physical configurations across regimes share posterior mass.
        normalized={}
        for a in self.model['approaches']:
            h=heads.get(a,{})
            states={v['movement']:v['state'] for v in h.get('arrows',[])}
            normalized[a]=dict(main=dict(state=h.get('main',{}).get('state','UNKNOWN')),
                arrows=[dict(movement=m,state=states.get(m,'UNKNOWN')) for m in self.topology[a]])
        key=json.dumps(normalized,sort_keys=True,separators=(',',':'))
        if key not in self.groups:
            self.groups[key]=len(self.configurations);self.configurations.append(normalized)
        index=self.groups[key]
        if not hasattr(self,'locations'):self.locations=[]
        self.locations.append((index,location))

    def advance(self,seconds):
        for _ in range(min(seconds,self.age_cap)):
            for i,bank in enumerate(self.green):
                leave=(bank*self.hazards[i]).sum(axis=1)
                following=np.zeros_like(bank);remain=bank*(1-self.hazards[i])
                following[:,1:]=remain[:,:-1];following[:,-1]+=remain[:,-1]
                following[:,0]+=self.edge[i][:,:,-1].sum(axis=0)
                edge=np.zeros_like(self.edge[i]);edge[:,:,1:]=self.edge[i][:,:,:-1]
                edge[:,:,0]+=leave[:,None]*self.transitions[i]
                self.green[i]=following*.9999+self.initial[i]*.0001
                self.edge[i]=edge*.9999

    def observe(self,events,kind='LEGACY'):
        for origin,target,weight in events:
            values=self.marks.likelihoods(origin,target)
            for i,likelihood in enumerate(values):
                self.green[i]*=np.maximum(.001,likelihood[:,None])**weight
                # A downstream exit may still describe the outgoing permission.
                # Restarting inside a queue can also occur during clearance;
                # keep it possible rather than imposing event=GREEN certainty.
                edge_likelihood=likelihood[:,None] if weight<1 else (
                    .8*likelihood[:,None]+.2*likelihood[None,:])
                if kind=='NEAR_RESTART':edge_likelihood=.2*(likelihood[:,None]+likelihood[None,:])
                self.edge[i]*=np.maximum(.001,edge_likelihood[:,:,None])**weight
                if kind=='PASSAGE':
                    # A near-front passage is more current than an exit-zone
                    # observation. Coasting stays possible during yellow.
                    self.edge[i]*=(.2+.8*np.exp(-np.arange(self.prior.clearance_s)/1.5))[None,None,:]**weight
                if weight>=1 and self.use_restart_age_prior:
                    r=self.model['regimes'][i]
                    hist=[np.array(h) for m,h in r.get('restart_age_histograms',{}).items()
                          if m.replace('_','').split('->')[0]==origin and
                          (target is None or m.replace('_','').split('->')[1]==target)]
                    if hist:
                        histogram=np.mean(hist,axis=0)
                        for z,median in enumerate(self.medians[i]):
                            bins=np.minimum(15,(np.arange(self.age_cap+1)/(median+self.prior.clearance_s)*16).astype(int))
                            self.green[i][z]*=.5+.5*histogram[z,bins]
                            self.edge[i][z]*=.5+.5*histogram[z,-1]
            self._normalize_observation()

    def _normalize_observation(self):
        total=sum(float(g.sum()+e.sum()) for g,e in zip(self.green,self.edge))
        self.log_evidence+=math.log(max(total,1e-300))
        for g,e in zip(self.green,self.edge):g/=max(total,1e-300);e/=max(total,1e-300)

    def observe_stops(self,origins,blocked,*,braking=False):
        for origin in origins:
            obstruction=blocked.get(origin,.03)
            strength=getattr(self,'braking_weights',{}).get(origin,.4) if braking else .6
            def likelihood(state):
                if braking:
                    return (.08+.8*obstruction) if state=='GREEN' else (.9 if state=='YELLOW' else (
                        .65 if state in ('RED','RED_YELLOW') else .5))
                return (.15+.7*obstruction) if state=='GREEN' else (.7 if state=='YELLOW' else (
                    .85 if state in ('RED','RED_YELLOW') else .5))
            for i,r in enumerate(self.model['regimes']):
                configurations=r.get('phase_head_states') or [{}]*r['phase_count']
                for z,h in enumerate(configurations):
                    self.green[i][z]*=likelihood(h.get(origin,{}).get('main',{}).get('state','UNKNOWN'))**strength
                for z in range(r['phase_count']):
                    for nxt in range(r['phase_count']):
                        if not self.transitions[i][z,nxt]:continue
                        for second in range(self.prior.clearance_s):
                            h=transition_heads(configurations[z],configurations[nxt],second,self.prior)
                            self.edge[i][z,nxt,second]*=likelihood(h.get(origin,{}).get('main',{}).get('state','UNKNOWN'))**strength
            self._normalize_observation()

    def tick(self,now,events,*,near_restarts=(),passages=(),stops=(),braking=(),blocked=None):
        if type(now) is not int or now<0:raise ValueError('invalid observation time')
        for origin,target,weight in list(events)+list(near_restarts)+list(passages):
            if (origin not in self.model['approaches'] or target not in (None,*self.model['approaches'])
                    or isinstance(weight,bool) or not math.isfinite(weight) or not 0<weight<=1):
                raise ValueError('invalid current movement observation')
        if any(a not in self.model['approaches'] for a in list(stops)+list(braking)):raise ValueError('invalid stop approach')
        if blocked is not None and any(a not in self.model['approaches'] or isinstance(p,bool)
                or not isinstance(p,(int,float)) or not math.isfinite(p) or not 0<=p<=1 for a,p in blocked.items()):
            raise ValueError('invalid obstruction probability')
        if self.last_ms is not None:
            if now<=self.last_ms:raise ValueError('timestamp must increase')
            gap=now-self.last_ms
            if gap>self.age_cap*1000:
                self.green=[b.copy() for b in self.initial];self.edge=[np.zeros_like(e) for e in self.edge]
                self.evidence_ms=None
            else:self.advance(max(1,int(round(gap/1000))))
        predicted_g=[g.copy() for g in self.green];predicted_e=[e.copy() for e in self.edge]
        if events:self.observe(events);self.evidence_ms=now
        if near_restarts:self.observe(near_restarts,'NEAR_RESTART');self.evidence_ms=now
        if passages:self.observe(passages,'PASSAGE');self.evidence_ms=now
        if stops:self.observe_stops(stops,blocked or {});self.evidence_ms=now
        if braking:self.observe_stops(braking,blocked or {},braking=True);self.evidence_ms=now
        self.last_ms=now
        result=self.summarize(now,self.green,self.edge,self.evidence_ms,cache_current=True)
        reconstructed=self.smoother.push(now,predicted_g,predicted_e,self.green,self.edge,self.evidence_ms)
        if reconstructed is not None:
            history=self.summarize(reconstructed['timestamp_ms'],reconstructed.pop('green'),
                                   reconstructed.pop('edge'),reconstructed.pop('evidence_ms'))
            history.update(reconstructed,estimate_kind='CAUSAL_FIXED_LAG_RECONSTRUCTION',observed_lamp=False)
            result['finalized_history']=[history]
        else:result['finalized_history']=[]
        result['history_lag_s']=self.smoother.lag_s
        return result

    def summarize(self,now,green,edge,evidence_ms,*,cache_current=False):
        masses=[g.sum(axis=1)+e.sum(axis=(1,2)) for g,e in zip(green,edge)]
        i=int(np.argmax([m.sum() for m in masses]));r=self.model['regimes'][i];z=int(np.argmax(masses[i]))
        votes=np.zeros(len(self.configurations));best_point=(-1,None,None)
        for index,(regime,kind,phase,nxt,second) in self.locations:
            votes[index]+=float(green[regime][phase].sum() if kind=='green' else edge[regime][phase,nxt,second])
            point=float(green[regime][phase].max() if kind=='green' else edge[regime][phase,nxt,second])
            if point>best_point[0]:best_point=(point,index,(regime,phase))
        selected=int(np.argmax(votes))
        if self.point_estimator=='joint_state':
            _,selected,(i,z)=best_point;r=self.model['regimes'][i]
        configuration=self.configurations[selected]
        recent=evidence_ms is not None and now-evidence_ms<=max(15000,r['period_s']*500)
        heads={};color_marginals={a:{} for a in self.model['approaches']}
        for j,c in enumerate(self.configurations):
            for a in self.model['approaches']:
                state=c[a]['main']['state'];color_marginals[a][state]=color_marginals[a].get(state,0.)+float(votes[j])
        if cache_current:self.color_marginals=color_marginals
        for a,h in configuration.items():
            heads[a]=dict(main={},arrows=[])
            for movement in [None]+self.topology[a]:
                state=h['main']['state'] if movement is None else next(v['state'] for v in h['arrows'] if v['movement']==movement)
                confidence=sum(float(votes[j]) for j,c in enumerate(self.configurations) if (
                    c[a]['main']['state'] if movement is None else next(v['state'] for v in c[a]['arrows'] if v['movement']==movement))==state)
                # A joint-state MAP is a point estimate, not a calibrated 50%
                # claim about every projected color. Keep its true marginal
                # confidence visible instead of replacing it by phase confidence.
                supported=recent and (float(masses[i][z])>=.5 if self.point_estimator=='joint_state' else confidence>=.5)
                item=dict(state=state if supported else 'UNKNOWN',confidence=confidence,
                    source='JOINT_PHASE_DURATION_COLOR_POSTERIOR' if supported else 'INSUFFICIENT_CURRENT_EVIDENCE')
                if movement is None:heads[a]['main']=item
                else:heads[a]['arrows'].append(dict(movement=movement,**item))
        green_mass=float(green[i][z].sum())
        age=float(green[i][z]@np.arange(self.age_cap+1)/green_mass) if green_mass>1e-12 else None
        return dict(heads=heads,phase_count=r['phase_count'],regime_id=r['regime_id'],
            regime_confidence=float(masses[i].sum()),phase_id=z,phase_name=r['phase_names'][z],
            phase_confidence=float(masses[i][z]),phase_age_estimate_s=age,
            joint_configuration_confidence=float(votes[selected]),
            point_estimator=self.point_estimator,
            clearance_probability=sum(float(e.sum()) for e in edge),
            duration_basis='JOINT_SEMI_MARKOV_GREEN_AND_EXPLICIT_CLEARANCE',
            transition_prior=dict(yellow_s=self.prior.yellow_s,red_yellow_s=self.prior.red_yellow_s,
                                  clearance_s=self.prior.clearance_s,calibration='UNCALIBRATED_GENERAL_PRIOR'),
            last_evidence_ms=evidence_ms,status='TRACKING' if recent else 'AWAITING_EVIDENCE')


class CoherentIntersection:
    """Candidate raw-packet adapter; v7 remains the shared motion/validation path."""
    VERSION='causal-intersection-coherent-v1'

    def __init__(self,model,*,transition_prior=None,history_lag_s=10):
        from app.core.intersection_online import CausalIntersection
        from app.core.intersection_queue_observations import QueueObservations
        self.motion=CausalIntersection(model);self.filter=JointSignalFilter(model,transition_prior=transition_prior,history_lag_s=history_lag_s)
        self.queues=QueueObservations(model.get('queue_observations',{}))
        self.events=[];original=self.motion._observe
        def observe(events):self.events.extend(events);original(events)
        self.motion._observe=observe

    def ingest(self,packet):
        self.events.clear()
        old={k:t.get('last_restart_ms',-1) for k,t in self.motion.tracks.items()}
        result=self.motion.ingest(packet)  # full packet validated before any joint-state change
        observation=self.queues.extract(self.motion.tracks,[v['id'] for v in packet['vehicles']],packet['timestamp_ms'],old)
        local=observation['restarts']+observation['passages']
        for origin in observation['stops']+observation['braking']:
            previous=getattr(self.filter,'color_marginals',{}).get(origin,{}).get('GREEN',0.)
            if previous>.8 and any(a!=origin and getattr(self.filter,'color_marginals',{}).get(a,{}).get('GREEN',0.)>.8 for a,b,w in local):
                self.queues.blocked[origin]=max(.8,self.queues.blocked[origin])
        observation['blocked_probability']=dict(self.queues.blocked)
        legacy=[e for e in self.events if e[0] not in observation['covered']]
        result.update(self.filter.tick(packet['timestamp_ms'],legacy,near_restarts=observation['restarts'],
            passages=observation['passages'],stops=observation['stops'],braking=observation['braking'],blocked=self.queues.blocked))
        result.update(schema=self.VERSION,phase_timings='joint_causal_estimates_NOT_observed_lamps',
                      confidence_semantics='uncalibrated_joint_posterior_NOT_lamp_probability',
                      observation_channels={k:len(observation[k]) for k in ('restarts','passages','stops','braking')},
                      obstruction_probability=observation['blocked_probability'],
                      obstruction_semantics='uncalibrated_downstream_block_hypothesis_NOT_accident_classification')
        return result
