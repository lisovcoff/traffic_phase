"""Exact fixed-order renewal messages with bounded vehicle-factor history.

No full-path enumeration or approximate pruning. A factor is evaluated once on
its last support cell; state retains all phase labels needed by unfinished factors.
"""
import copy
import math
import time

import numpy as np

from app.core.state_contract import StateEstimate,physical_estimate
from app.experimental.joint_track_model import GRID_S,PRIORS,ModelUnavailable
from app.experimental.unanchored_sequence import duration_masses
from app.experimental.local_factor_sequence import _lse
from app.experimental.context_observation import prepare_context_observation


class VehicleFactors:
    """Closure potentials exactly equal existing joint-track path_loglik."""
    def __init__(self,comp,max_span):
        self.n=comp['n'];self.k=len(comp['rates']);self.rates=comp['rates']
        q=np.asarray(comp['q'])
        if q.shape!=(len(comp['tracks']),self.n) or not np.isfinite(q).all() or (q<0).any():
            raise ModelUnavailable('INVALID_VEHICLE_KERNEL')
        self.closed=[[] for _ in range(self.n)];self.max_span=0
        self.compensator=np.stack([-np.sum(comp['rates'][z,:,None]*comp['exposure']*GRID_S,axis=0)*
            comp['detected_probability'] for z in range(self.k)],axis=1)
        for i,track in enumerate(comp['tracks']):
            support=np.flatnonzero(q[i]>0)
            if not len(support):raise ModelUnavailable('EMPTY_VEHICLE_KERNEL')
            span=int(support[-1]-support[0]+1);self.max_span=max(self.max_span,span)
            if span>max_span:raise ModelUnavailable('KERNEL_HISTORY_LIMIT_EXCEEDED')
            m=comp['movements'].index(track['movement'])
            weights=comp['exposure'][m,support]*GRID_S*q[i,support]
            self.closed[int(support[-1])].append((m,list(zip(support.tolist(),weights.tolist()))))
        self.cache=[{} for _ in range(self.n)]

    def value(self,j,history):
        if history in self.cache[j]:return self.cache[j][history]
        value=float(self.compensator[j,history[-1]])
        for movement,weights in self.closed[j]:
            mu=sum(w*self.rates[history[len(history)-1-j+s],movement] for s,w in weights)
            if mu<=0:value=-math.inf;break
            value+=math.log(mu)
        self.cache[j][history]=value
        return value


def infer_bounded_factors(comp,order,*,max_kernel_span_cells=3,max_states_per_layer=4096,
                          max_total_states=100000,max_memory_bytes=32*1024*1024,max_seconds=5.):
    started=time.process_time();wall=time.perf_counter()
    base=dict(schema='experimental-bounded-factor-renewal-v1',status='unavailable',complete=False,results={},
        logical_phase=StateEstimate('UNKNOWN','logical_phase','bounded_factor_sequence',
            abstention_reason='MODEL_CONDITIONED_DIAGNOSTIC_NOT_VALIDATED_HISTORY').to_dict(),
        physical_section=physical_estimate('UNKNOWN',source='bounded_factor_sequence').to_dict(),
        calibrated_lamp_probability=None,published_logical_unknown_fraction=1.,
        published_physical_unknown_fraction=1.,production_default_changed=False,
        enumeration_used=False,truncation_used=False,
        assumptions=['bounded complete q support span; no positive mass discarded',
            'fixed supplied K/order and observation model','stationary residual start; unchanged duration priors',
            'finite2s phase grid; model probabilities are not lamp calibration'])
    def failed(reason):return {**base,'reason':reason,'cpu_s':time.process_time()-started,'wall_s':time.perf_counter()-wall}
    def check():
        if time.process_time()-started>max_seconds or time.perf_counter()-wall>max_seconds:
            raise ModelUnavailable('TIME_BUDGET_EXHAUSTED_NO_POSTERIOR')
    try:
        limits=(max_kernel_span_cells,max_states_per_layer,max_total_states,max_memory_bytes)
        if (any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in limits)
                or not 1<=max_kernel_span_cells<=5 or isinstance(max_seconds,bool)
                or not isinstance(max_seconds,(int,float)) or not math.isfinite(max_seconds) or max_seconds<=0):
            raise ModelUnavailable('INVALID_OR_EXHAUSTED_RESOURCE_LIMIT')
        n=comp['n'];k=len(comp['rates'])
        if not isinstance(n,int) or isinstance(n,bool) or not 1<=n<=40 or k not in (2,3):
            raise ModelUnavailable('BOUNDED_K2_K3_CONTEXT_REQUIRED')
        if not isinstance(order,list) or any(isinstance(z,bool) or not isinstance(z,int) for z in order) or sorted(order)!=list(range(k)):
            raise ModelUnavailable('SUPPLIED_CYCLIC_ORDER_REQUIRED')
        check();factors=VehicleFactors(comp,max_kernel_span_cells);W=max(1,factors.max_span)
        next_phase={z:order[(i+1)%k] for i,z in enumerate(order)}
        results={};peak_layer=0;peak_total=0;peak_allowance=0
        for name,prior in PRIORS.items():
            ds,pm=duration_masses(prior);R=int(ds[-1]//GRID_S)
            mass=np.zeros(R+1);mass[(ds//GRID_S).astype(int)]=pm
            residual=np.array([0.]+[mass[r:].sum() for r in range(1,R+1)])
            residual/=float(np.arange(R+1)@mass)
            survival=np.cumsum(mass[::-1])[::-1];res_survival=np.cumsum(residual[::-1])[::-1]
            total=0
            def reserve(layer_size):
                nonlocal total,peak_layer,peak_total,peak_allowance
                check()
                if layer_size>max_states_per_layer:raise ModelUnavailable('LAYER_STATE_BUDGET_EXHAUSTED_NO_POSTERIOR')
                if total+1>max_total_states:raise ModelUnavailable('TOTAL_STATE_BUDGET_EXHAUSTED_NO_POSTERIOR')
                allowance=(total+1)*((n+1)*8+4096+W*32)+65536
                if allowance>max_memory_bytes:raise ModelUnavailable('MEMORY_BUDGET_EXHAUSTED_NO_POSTERIOR')
                total+=1;peak_layer=max(peak_layer,layer_size);peak_total=max(peak_total,total)
                peak_allowance=max(peak_allowance,allowance)
            initial={};best0={}
            for z in order:
                reserve(len(initial)+1);node=((z,),1)
                vector=np.full(n+1,-math.inf);vector[0]=-math.log(k)
                initial[node]=vector;best0[node]=-math.log(k)
            layers=[initial];best=best0;pointers=[{}];edges=[]
            for j in range(n-1):
                check();following={};next_best={};back={};outgoing={}
                for node,alpha in layers[-1].items():
                    history,age=node;g=factors.value(j,history)
                    if not np.isfinite(alpha+g).any():continue # exact zero, never a beam
                    distribution=residual if age==j+1 else mass
                    tail=res_survival if age==j+1 else survival
                    p_switch=float(distribution[age]/tail[age])
                    p_stay=float(tail[age+1]/tail[age]) if age<R else 0.
                    for switched,p in ((False,p_stay),(True,p_switch)):
                        if p<=0:continue
                        z=next_phase[history[-1]] if switched else history[-1]
                        target=((history+(z,))[-W:],1 if switched else age+1)
                        if target not in following:
                            reserve(len(following)+1);following[target]=np.full(n+1,-math.inf)
                            next_best[target]=-math.inf
                        lp=math.log(p);contribution=alpha+g+lp
                        if switched:contribution=np.r_[-math.inf,contribution[:-1]]
                        following[target]=np.logaddexp(following[target],contribution)
                        v=best[node]+g+lp
                        if v>next_best[target]:next_best[target]=v;back[target]=node
                        outgoing.setdefault(node,[]).append((target,lp,switched))
                if not following:raise ModelUnavailable('ALL_PATHS_HAVE_ZERO_OBSERVATION_PROBABILITY')
                layers.append(following);best=next_best;pointers.append(back);edges.append(outgoing)
            finals={node:alpha+factors.value(n-1,node[0]) for node,alpha in layers[-1].items()}
            logZ=_lse([_lse(v) for v in finals.values()])
            if not math.isfinite(logZ):raise ModelUnavailable('ALL_PATHS_HAVE_ZERO_OBSERVATION_PROBABILITY')
            count=[math.exp(_lse([v[c] for v in finals.values()])-logZ) for c in range(n+1)]
            beta=[{} for _ in range(n)]
            beta[-1]={node:factors.value(n-1,node[0]) for node in layers[-1]}
            for j in range(n-2,-1,-1):
                check()
                for node in layers[j]:
                    terms=[lp+beta[j+1][target] for target,lp,_ in edges[j].get(node,[])]
                    beta[j][node]=factors.value(j,node[0])+(_lse(terms) if terms else -math.inf)
            phase=[];boundaries=[]
            for j in range(n):
                check();row=[0.]*k
                for node,alpha in layers[j].items():row[node[0][-1]]+=math.exp(_lse(alpha)+beta[j][node]-logZ)
                phase.append(row)
                if j<n-1:
                    terms=[_lse(layers[j][node])+factors.value(j,node[0])+lp+beta[j+1][target]
                        for node,transitions in edges[j].items() for target,lp,switched in transitions if switched]
                    boundaries.append(dict(time_s=(j+1)*GRID_S,
                        model_conditioned_existence_probability=math.exp(_lse(terms)-logZ) if terms else 0.))
            last=max(best,key=lambda node:best[node]+factors.value(n-1,node[0]))
            map_score=best[last]+factors.value(n-1,last[0]);labels=[last[0][-1]]
            for j in range(n-1,0,-1):last=pointers[j][last];labels.append(last[0][-1])
            labels.reverse();segments=[]
            for j,z in enumerate(labels):
                if segments and segments[-1][2]==z:segments[-1][1]=(j+1)*GRID_S
                else:segments.append([j*GRID_S,(j+1)*GRID_S,z])
            results[name]=dict(prior=copy.deepcopy(prior),log_normalizer=float(logZ),
                transition_count_posterior={str(c):float(p) for c,p in enumerate(count) if p>0},
                phase_posterior=phase,initial_phase_posterior={str(z):phase[0][z] for z in order},
                boundary_existence=boundaries,diagnostic_segments=segments,diagnostic_map_log_joint=float(map_score),
                posterior_semantics='exact supplied bounded-history grid model; not calibrated lamp probability')
        check()
        return {**base,'status':'complete_bounded_factor_posterior','complete':True,'results':results,
            'observed_max_kernel_span_cells':factors.max_span,'retained_history_cells':W,
            'max_states_in_layer':peak_layer,'max_retained_states':peak_total,
            'declared_state_allowance_bytes':peak_allowance,'context_extent_s':[0,n*GRID_S],
            'likelihood_constant_over_phase_paths':all(len(set(cache.values()))==1 for cache in factors.cache),
            'path_dependence_semantics':'equality sufficient for prior-only; inequality NOT identifiability',
            'cpu_s':time.process_time()-started,'wall_s':time.perf_counter()-wall}
    except (ModelUnavailable,ValueError,TypeError,KeyError,IndexError,OverflowError) as exc:return failed(str(exc))


def infer_bounded_context(index,spec,*,context_origin_ms,target_range_ms,**limits):
    prepared=prepare_context_observation(index,spec,context_origin_ms=context_origin_ms,target_range_ms=target_range_ms)
    if prepared['status']!='ready_for_supplied_context_model_only':
        return {**prepared,'schema':'experimental-bounded-factor-renewal-v1','complete':False,'results':{}}
    result=infer_bounded_factors(prepared['components'],spec.get('cyclic_order'),**limits)
    return {**result,'context_plan':prepared['context_plan'],'input_sha256':prepared['input_sha256'],
        'supplied_model_sha256':prepared['supplied_model_sha256']}
