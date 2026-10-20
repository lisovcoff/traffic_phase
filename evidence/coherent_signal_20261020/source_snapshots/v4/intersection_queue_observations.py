"""Offline learned queue-front references and causal local motion observations.

A reference is a repeated stopping location, NOT a certified painted stop line.
Stopped cars can indicate either red or downstream obstruction. No video, lamp
labels, site names or future online destinations are accepted by this module.
"""
from collections import defaultdict
import math
import numpy as np


def metric_xy(d,anchor):
    lat,lng=d.get('lat'),d.get('lng')
    if lat is None or lng is None or not math.isfinite(lat) or not math.isfinite(lng):return None
    return np.array([(lng-anchor[1])*111_000*math.cos(math.radians(anchor[0])),(lat-anchor[0])*111_000])


def learn_queue_references(records):
    anchor=None;directions=defaultdict(list);stops=defaultdict(list);counts=defaultdict(int)
    for track in records:
        origin=str(track.get('zone_in','')).replace('_','')
        if origin not in ('N','S','E','W'):continue
        ds=[d for d in track.get('detections',[]) if d.get('lat') is not None and d.get('lng') is not None]
        if len(ds)<8:continue
        if anchor is None:anchor=[ds[0]['lat'],ds[0]['lng']]
        xy=np.array([metric_xy(d,anchor) for d in ds])
        if xy.dtype==object or not np.isfinite(xy).all():continue
        times=np.array([d['millis'] for d in ds]);dt=np.diff(times)/1000
        if np.any(dt<=0):continue
        chord=xy[-1]-xy[0];length=float(np.linalg.norm(chord))
        path=float(np.linalg.norm(np.diff(xy,axis=0),axis=1).sum())
        if length<25 or path>1.25*length:continue
        heading=chord/length
        # Reject strongly curved turns; the learned main queue reference must
        # not become an interior waiting point for a permissive left/U-turn.
        lateral=np.abs((xy-xy[0])@np.array([-heading[1],heading[0]]))
        if float(np.quantile(lateral,.9))>4:continue
        counts[origin]+=1;directions[origin].append(heading)
        speed=np.linalg.norm(np.diff(xy,axis=0),axis=1)/dt;run=[]
        for i,v in enumerate(speed,1):
            zone=str(ds[i].get('zone','')).replace('_','')
            incoming=(zone==origin and not str(ds[i].get('zone','')).startswith('_'))
            if v<.8 and dt[i-1]<=2 and incoming:run.append(i)
            else:
                if run and (times[run[-1]]-times[run[0]])>=1500:
                    stops[origin].append(np.median(xy[run],axis=0))
                run=[]
        if run and (times[run[-1]]-times[run[0]])>=1500:stops[origin].append(np.median(xy[run],axis=0))
    references={}
    for origin,points in stops.items():
        if len(points)<8:continue
        heading=np.median(directions[origin],axis=0);heading/=max(1e-9,np.linalg.norm(heading))
        xy=np.array(points);progress=xy@heading
        bins=np.floor(progress/3).astype(int);minimum=max(5,int(len(points)*.05))
        eligible=[b for b in set(bins) if np.sum(np.abs(bins-b)<=1)>=minimum]
        if not eligible:continue
        # Furthest sufficiently populated stopping cluster, not furthest car.
        selected=max(eligible);mask=np.abs(bins-selected)<=1
        center=np.median(xy[mask],axis=0);normal=np.array([-heading[1],heading[0]])
        references[origin]=dict(anchor_lat_lng=anchor,point_m=center.tolist(),heading=heading.tolist(),
            lateral_radius_m=max(4.,float(np.quantile(np.abs((xy[mask]-center)@normal),.9))+1),
            stopping_runs=int(mask.sum()),straight_tracks=counts[origin],
            semantics='observed_queue_front_NOT_verified_stop_line')
    return dict(version='offline-queue-reference-v1',references=references,
                input_scope='offline trajectories only',physical_stop_line_verified=False)


class QueueObservations:
    def __init__(self,learned):
        self.references=learned.get('references',{});self.flags={};self.blocked={a:.03 for a in self.references}

    def extract(self,tracks,vehicle_ids,now,previous_restarts):
        restart=[];passage=[];stops=[];braking=[];downstream=set();covered=set()
        self.flags={k:v for k,v in self.flags.items() if k in tracks}
        for a in self.blocked:self.blocked[a]=.03+(self.blocked[a]-.03)*math.exp(-1/300)
        for key in vehicle_ids:
            track=tracks.get(str(key));origin=track['origin'] if track else None
            ref=self.references.get(origin)
            if not ref:continue
            points=track['points'];usable=[(d,metric_xy(d,ref['anchor_lat_lng'])) for d in points]
            usable=[(d,p) for d,p in usable if p is not None]
            if len(usable)<2:continue
            covered.add(origin)
            center=np.array(ref['point_m']);heading=np.array(ref['heading']);normal=np.array([-heading[1],heading[0]])
            ds=[d for d,p in usable];xy=np.array([p for d,p in usable]);progress=(xy-center)@heading
            lateral=np.abs((xy-center)@normal);flags=self.flags.setdefault(str(key),dict(passed=False,stopped=False,braked=False))
            near=lateral[-1]<=ref['lateral_radius_m']
            if not near or now-ds[-1]['millis']>2000:continue
            if track.get('last_restart_ms',-1)>previous_restarts.get(str(key),-1) and -8<=progress[-1]<=5:
                restart.append((origin,track['target'],1.))
            if not flags['passed'] and any(a<=3<b for a,b in zip(progress,progress[1:])):
                passage.append((origin,track['target'],.7));flags['passed']=True
            tail=[i for i,d in enumerate(ds) if d['millis']>=ds[-1]['millis']-2000]
            stationary=(len(tail)>=3 and ds[tail[-1]]['millis']-ds[tail[0]]['millis']>=1500
                        and np.max(np.linalg.norm(xy[tail]-xy[tail[-1]],axis=1))<1.2
                        and all(b['millis']-a['millis']<=2000 for a,b in zip(ds[tail[0]:],ds[tail[0]+1:])))
            if stationary:
                if 5<progress[-1]<40:downstream.add(origin)
                if -8<=progress[-1]<=4 and not flags['stopped']:
                    stops.append(origin);flags['stopped']=True
            elif np.linalg.norm(xy[-1]-xy[-2])>1:flags['stopped']=False
            recent=[i for i,d in enumerate(ds) if d['millis']>=ds[-1]['millis']-3000]
            if len(recent)>=5 and ds[recent[-1]]['millis']-ds[recent[0]]['millis']>=2500:
                first,middle,last=recent[0],recent[len(recent)//2],recent[-1]
                dt1=(ds[middle]['millis']-ds[first]['millis'])/1000
                dt2=(ds[last]['millis']-ds[middle]['millis'])/1000
                before=(progress[middle]-progress[first])/dt1;after=(progress[last]-progress[middle])/dt2
                continuous=all(b['millis']-a['millis']<=2000 for a,b in zip(ds[first:],ds[first+1:]))
                if (continuous and -25<=progress[-1]<=1 and before>3 and 0<=after<before*.65
                        and (after-before)/((dt1+dt2)/2)<-1 and not flags['braked']):
                    braking.append(origin);flags['braked']=True
        for a in downstream:self.blocked[a]=max(.9,self.blocked[a])
        # Correlated cars in one movement/second are one observation, as in v7.
        dedup=lambda rows:list({(a,b):(a,b,w) for a,b,w in rows}.values())
        return dict(restarts=dedup(restart),passages=dedup(passage),stops=sorted(set(stops)),braking=sorted(set(braking)),
                    blocked_probability=dict(self.blocked),downstream_occupied=sorted(downstream),covered=covered)
