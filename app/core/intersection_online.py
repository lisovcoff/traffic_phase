"""Causal fixed-structure phase/age filter. No offline clock or future track fields.

Positive observed restarts/zone exits supply weak permission evidence. Absence of
cars is never a red observation. Timing/transition priors come from the saved model.
"""
from copy import deepcopy
import math
from types import SimpleNamespace
import numpy as np

from app.core.intersection_project import _compass
from app.core.recovery.motion import restart_from_raw_speed
from app.core.v9.spatial import apply_projection
from app.core.trajectory_geometry import haversine_distance_m

VERSION='causal-intersection-v4'


def coarse_restart(points,now):
    """Support 1Hz sensors: three sustained moving samples after a real zero run."""
    valid=[d for d in points if d.get('speed') is not None]
    if len(valid)<6:return None
    speeds=[d['speed'] for d in valid if d['speed']>0]
    if not speeds:return None
    threshold=.08*sorted(speeds)[int(.75*(len(speeds)-1))]
    run=[]
    for d in reversed(valid):
        if d['speed']<=threshold:break
        run.append(d)
    run.reverse()
    if len(run)<3 or run[-1]['millis']-run[0]['millis']<600:return None
    zeros=[d for d in valid if d['millis']<run[0]['millis']]
    stationary=[]
    for d in reversed(zeros):
        if d['speed']!=0:break
        stationary.append(d)
    if len(stationary)<2 or stationary[0]['millis']-stationary[-1]['millis']<1500:return None
    tail=list(reversed(stationary))+run
    if any(b['millis']-a['millis']>2000 for a,b in zip(tail,tail[1:])):return None
    return dict(timestamp_ms=run[0]['millis'])


def geographic_restart(points,now):
    """Causal position-derived motion when vendor speed is stale/nonzero at rest."""
    speeds=[]
    for a,b in zip(points,points[1:]):
        dt=(b['millis']-a['millis'])/1000
        if not 0<dt<=2 or any(d.get(k) is None for d in (a,b) for k in ('lat','lng')):continue
        speed=haversine_distance_m(SimpleNamespace(lat=a['lat'],lng=a['lng']),SimpleNamespace(lat=b['lat'],lng=b['lng']))/dt
        speeds.append(dict(millis=b['millis'],speed=0. if speed<.8 else speed))
    return restart_from_raw_speed(speeds,now+1) or coarse_restart(speeds,now)


class CausalIntersection:
    def __init__(self,model):
        self.model=model;self.last_ms=None;self.tracks={};self.evidence_ms=None;self.event_count=0
        self.banks=[];self.initial=[];self.hazards=[];self.transitions=[];self.medians=[]
        self.age_cap=min(1800,max(180,int(max(r['period_s'] for r in model['regimes'])*4)))
        self.geometry_key=next(iter(model.get('geometries',{})),None)
        self.projection=model['geometries'][self.geometry_key]['projection'] if self.geometry_key else None
        self.offsets=[];offset=0
        for regime in model['regimes']:
            k=regime['phase_count'];medians=[];hazards=[];survivals=[]
            for name in regime['phase_names']:
                stats=regime['phase_durations'][name];med=max(2.,stats['median_s'] or regime['period_s']/k)
                p10=stats['p10_s'] or med*.7;p90=stats['p90_s'] or med*1.3
                sigma=max(.12,(math.log(max(1.,p90))-math.log(max(1.,p10)))/2.563)
                survival=np.array([.85*.5*math.erfc((math.log(max(.01,a))-math.log(med))/sigma/math.sqrt(2))
                    +.15*math.exp(-a/(4*med)) for a in range(self.age_cap+2)])
                hazards.append(np.clip(1-survival[1:]/survival[:-1],.0001,.5))
                survivals.append(survival[:-1]);medians.append(med)
            initial=np.array(survivals);initial/=initial.sum()*len(model['regimes'])
            self.initial.append(initial);self.banks.append(initial.copy());self.hazards.append(np.array(hazards))
            self.medians.append(medians);transition=np.zeros((k,k))
            for row in regime.get('observed_transitions',[]):transition[row['source'],row['target']]+=row['observations']
            for z in range(k):
                if not transition[z].sum():transition[z,(z+1)%k]=1
                transition[z]/=transition[z].sum()
            self.transitions.append(transition);self.offsets.append(offset);offset+=k

    def _advance(self,seconds):
        for _ in range(min(seconds,self.age_cap)):
            for i,bank in enumerate(self.banks):
                remain=bank*(1-self.hazards[i]);following=np.zeros_like(bank)
                following[:,1:]=remain[:,:-1];following[:,-1]+=remain[:,-1]
                following[:,0]+=(bank*self.hazards[i]).sum(axis=1)@self.transitions[i]
                # Small known-state restart mass permits resynchronization, never new K.
                self.banks[i]=following*.9999+self.initial[i]*.0001

    def _observe(self,events):
        for origin,target,weight in events:
            likelihoods=[]
            for regime in self.model['regimes']:
                candidates=[]
                for movement,values in regime['movement_probabilities'].items():
                    parts=movement.replace('_','').split('->')
                    if parts[0]!=origin or (target and parts[1]!=target):continue
                    rates=np.array(values);span=float(np.ptp(rates))
                    if span>.01:candidates.append((rates-rates.min())/span)
                likelihoods.append(.05+.95*np.max(candidates,axis=0) if candidates else np.full(regime['phase_count'],.2))
            for i,values in enumerate(likelihoods):
                self.banks[i]*=values[:,None]**weight
                if weight>=1:
                    regime=self.model['regimes'][i];histograms=[]
                    for movement,hist in regime.get('restart_age_histograms',{}).items():
                        parts=movement.replace('_','').split('->')
                        if parts[0]==origin and (target is None or parts[1]==target):histograms.append(np.array(hist))
                    if histograms:
                        histogram=np.mean(histograms,axis=0)
                        for phase,median in enumerate(self.medians[i]):
                            bins=np.minimum(15,(np.arange(self.age_cap+1)/median*16).astype(int))
                            self.banks[i][phase]*=.5+.5*histogram[phase,bins]
            total=sum(float(bank.sum()) for bank in self.banks)
            for bank in self.banks:bank/=max(total,1e-300)

    def ingest(self,packet):
        now=packet['timestamp_ms'];previous=self.last_ms
        if previous is not None and now<=previous:raise ValueError('timestamp must increase')
        vehicles=packet['vehicles']
        if len({str(v['id']) for v in vehicles})!=len(vehicles):raise ValueError('duplicate vehicle IDs in packet')
        # Validate the entire packet before advancing inference or touching tracks.
        for vehicle in vehicles:
            origin=_compass(vehicle['zone_in']);key=str(vehicle['id']);ds=vehicle['detections']
            if origin not in self.model['approaches']:raise ValueError('approach not learned offline')
            if 'zone_out' in vehicle:raise ValueError('zone_out is unavailable future metadata; send observed detection zones')
            old=self.tracks.get(key)
            if old and old['origin']!=origin:raise ValueError('vehicle ID changed origin')
            for d in ds:
                if d['millis']>now:raise ValueError('future detection')
                for name in ('speed','centroid_x','centroid_y','lat','lng'):
                    x=d.get(name)
                    if x is not None and (isinstance(x,bool) or not math.isfinite(x)):raise ValueError('nonfinite detection')
            if any(b['millis']<a['millis'] for a,b in zip(ds,ds[1:])):raise ValueError('unordered detections')
            known={d['millis']:d for d in old['points']} if old else {}
            for d in ds:
                if d['millis'] in known and d!=known[d['millis']]:raise ValueError('conflicting detection timestamp')
                known[d['millis']]=d
        gap_ms=now-previous if previous is not None else 0
        if gap_ms>self.age_cap*1000:self.banks=[b.copy() for b in self.initial]
        elif previous is not None:self._advance(max(1,int(round(gap_ms/1000))))
        self.tracks={k:t for k,t in self.tracks.items() if now-t['last_ms']<=180000}
        events=[];rendered=[]
        for vehicle in vehicles:
            key=str(vehicle['id']);origin=_compass(vehicle['zone_in'])
            if key not in self.tracks:
                if len(self.tracks)>=2000:raise ValueError('active trajectory capacity exceeded')
                self.tracks[key]=dict(origin=origin,points=[],last_ms=-1,released=False,crossed=False,target=None)
            track=self.tracks[key];new=[d for d in vehicle['detections'] if d['millis']>track['last_ms']]
            track['points']=(track['points']+new)[-128:]
            if not new:continue
            track['last_ms']=new[-1]['millis'];points=track['points']
            exits=[_compass(d.get('zone')) for d in points[-2:]
                if _compass(d.get('zone')) and (_compass(d['zone'])!=origin or str(d['zone']).startswith('_'))]
            if len(exits)==2 and exits[0]==exits[1]:track['target']=exits[-1]
            candidates=[c for c in (restart_from_raw_speed(points,now+1) or coarse_restart(points,now),geographic_restart(points,now)) if c]
            restart=max(candidates,key=lambda c:c['timestamp_ms']) if candidates else None
            if restart and now-restart['timestamp_ms']<=8000 and restart['timestamp_ms']>track.get('last_restart_ms',-3000)+2000:
                events.append((origin,track['target'],1.));track['released']=True
                track['last_restart_ms']=restart['timestamp_ms']
            if track['target'] and not track['crossed'] and now-points[-1]['millis']<=5000:
                events.append((origin,track['target'],.35));track['crossed']=True
            d=points[-1]
            if self.projection and d.get('centroid_x') is not None and d.get('centroid_y') is not None and now-d['millis']<=2000:
                x,y=apply_projection(self.projection,d['centroid_x'],d['centroid_y'])
                angle=0.
                if len(points)>1 and all(points[-2].get(n) is not None for n in ('centroid_x','centroid_y')):
                    a,b=apply_projection(self.projection,points[-2]['centroid_x'],points[-2]['centroid_y']);angle=math.atan2(y-b,x-a)
                rendered.append(dict(id=key,x=x,y=y,angle=angle,approach=origin))
        # Correlated queued vehicles cannot multiply one movement observation arbitrarily.
        events=list({(a,b):(a,b,w) for a,b,w in sorted(events,key=lambda e:e[2])}.values())
        events=[(a,b,w) for a,b,w in events if any(m.split('->')[0]==a and (b is None or m.replace('_','').split('->')[1]==b)
            and np.ptp(values)>.01 for r in self.model['regimes'] for m,values in r['movement_probabilities'].items())]
        if events:self._observe(events);self.evidence_ms=now
        self.event_count+=len(events)
        self.last_ms=now
        masses=[b.sum(axis=1) for b in self.banks];regime_index=int(np.argmax([v.sum() for v in masses]))
        regime=self.model['regimes'][regime_index];phase=int(np.argmax(masses[regime_index]))
        phase_probability=float(masses[regime_index][phase]);mode_probability=float(masses[regime_index].sum())
        age=float(np.dot(self.banks[regime_index][phase],np.arange(self.age_cap+1))/max(phase_probability,1e-300))
        recent=self.evidence_ms is not None and now-self.evidence_ms<=max(15000,regime['period_s']*500)
        heads={};best_heads=(regime.get('phase_head_states') or [{}]*regime['phase_count'])[phase]
        for approach in self.model['approaches']:
            topology=regime.get('signal_topology',{}).get(approach,dict(arrows=[]))
            head=dict(main=dict(state='UNKNOWN',source='INSUFFICIENT_CURRENT_EVIDENCE',confidence=0.),arrows=[])
            for movement in [None]+topology['arrows']:
                votes={}
                for i,r in enumerate(self.model['regimes']):
                    for z,configuration in enumerate(r.get('phase_head_states',[])):
                        h=configuration.get(approach,{})
                        state=h.get('main',{}).get('state','UNKNOWN') if movement is None else next(
                            (a['state'] for a in h.get('arrows',[]) if a['movement']==movement),'UNKNOWN')
                        votes[state]=votes.get(state,0.)+float(masses[i][z])
                state=max(votes,key=votes.get) if votes else 'UNKNOWN';confidence=votes.get(state,0.)
                supported=recent and confidence>=.65
                item=dict(state=state if supported else 'UNKNOWN',confidence=confidence,
                    source='CAUSAL_TRAJECTORY_ESTIMATE' if supported else 'INSUFFICIENT_CURRENT_EVIDENCE')
                if movement is None:head['main']=item
                else:head['arrows'].append(dict(movement=movement,**item))
            heads[approach]=head
        # Normative transition estimates are prior-based, explicitly labelled.
        if recent and phase_probability>=.65 and regime.get('phase_head_states'):
            nxt=int(np.argmax(self.transitions[regime_index][phase]));next_heads=regime['phase_head_states'][nxt]
            remaining=self.medians[regime_index][phase]-age
            fresh={a for a,b,w in events if w>=1}
            if 0<=remaining<=3:
                for a,head in heads.items():
                    current=best_heads.get(a,{}).get('main',{}).get('state');following=next_heads.get(a,{}).get('main',{}).get('state')
                    color='YELLOW' if current=='GREEN' and following=='RED' and a not in fresh else (
                        'RED_YELLOW' if current=='RED' and following=='GREEN' and remaining<=2 else None)
                    if color and head['main']['state']!='UNKNOWN':head['main'].update(state=color,source='OFFLINE_DURATION_TRANSITION_PRIOR')
        return dict(schema=VERSION,timestamp_ms=now,sequence=packet['sequence'],model_id=self.model['model_id'],
            model_fingerprint=self.model['fingerprint'],structure_source='OFFLINE_ONLY',
            phase_count=regime['phase_count'],regime_id=regime['regime_id'],regime_confidence=mode_probability,
            phase_id=phase,phase_name=regime['phase_names'][phase],phase_confidence=phase_probability,
            phase_age_estimate_s=age,heads=heads,vehicles=rendered,evidence_count=len(events),
            event_count=self.event_count,retained_track_count=len(self.tracks),
            issuance_basis='CURRENT_VEHICLE_EVENTS' if events else 'PREDICTED_FROM_PAST',
            confidence_semantics='uncalibrated_state_posterior_NOT_lamp_probability',
            last_evidence_ms=self.evidence_ms,status='TRACKING' if recent else 'AWAITING_EVIDENCE',
            missing_interval_ms=[previous+1000,now] if previous is not None and gap_ms>1500 else None,
            projection_source=self.geometry_key,projection_semantics='offline_reference_camera_assumption',
            phase_timings='causal_estimates_NOT_observed_lamps',video_used=False,annotations_used=False)
