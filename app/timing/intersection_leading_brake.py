"""Current leading-vehicle braking near an offline learned queue front.

No lamp labels or future destinations. An unimpeded brake is weak evidence for a
signal transition; an obstruction or permissive turn can still explain it.
"""
import numpy as np

from app.core.intersection_queue_observations import metric_xy
from app.timing.intersection_timing_ensemble import TimingEnsembleIntersection


class LeadingBrakeTimingIntersection(TimingEnsembleIntersection):
    VERSION='experimental-joint-leading-brake-timing-v1'
    REQUIRE_STOP_TARGET=False
    LEADING_BRAKE_WEIGHT=.4

    def __init__(self,model):
        super().__init__(model);self.brake_flags={};self.brake_observations=[]

    def _leading_brakes(self,now):
        references=self.source.queues.references;vehicles=[]
        for key,t in self.source.motion.tracks.items():
            ref=references.get(t['origin']);points=t['points']
            if not ref or not points or now-points[-1]['millis']>1000:continue
            heading=np.asarray(ref['heading']);normal=np.array([-heading[1],heading[0]])
            usable=[(d,metric_xy(d,ref['anchor_lat_lng'])) for d in points
                    if now-1800<=d['millis']<=now]
            usable=[(d,p) for d,p in usable if p is not None]
            if not usable:continue
            ds=[d for d,p in usable];xy=np.array([p for d,p in usable])-np.asarray(ref['point_m'])
            progress=xy@heading;lateral=xy@normal
            vehicles.append((key,t['origin'],ds,progress,lateral,ref))
        result=[];active=set()
        for key,origin,ds,p,l,ref in vehicles:
            active.add(key)
            if len(ds)<6 or abs(l[-1])>ref['lateral_radius_m']:continue
            if str(ds[-1].get('zone'))!=origin or p[-1]>1:continue
            times=np.array([d['millis'] for d in ds],dtype=float)/1000
            if times[-1]-times[0]<1.2 or np.max(np.diff(times))>.6:continue
            x=times-times[-1];coefs=np.polyfit(x,p,2);accel=2*coefs[0]
            speed=coefs[1];initial=speed+accel*x[0]
            residual=float(np.median(np.abs(np.polyval(coefs,x)-p)))
            if accel>-.3 and speed>3:self.brake_flags.pop(key,None)
            if (key in self.brake_flags or accel>=-1.2 or accel<-5 or initial<=4 or speed<0
                    or initial-speed<.8 or residual>.5 or np.ptp(l)>2):continue
            # Slowing down alone also occurs on GREEN (e.g. a convoy). Require
            # the fitted trajectory to target the repeated stopping location.
            projected_stop=p[-1]+speed*speed/(-2*accel)
            if self.REQUIRE_STOP_TARGET and abs(projected_stop)>4:continue
            # A leader close enough to explain the slowdown makes it ambiguous.
            if any(other!=key and a==origin and abs(lat[-1]-l[-1])<2.2
                   and 0<pos[-1]-p[-1]<max(12.,2*initial)
                   for other,a,_,pos,lat,_ in vehicles):continue
            distance=-p[-1];stopping_distance=initial*initial/(2*2.5)+8
            if distance>min(80.,max(25.,stopping_distance)):continue
            self.brake_flags[key]=now
            result.append(dict(origin=origin,vehicle_id=key,available_at_ms=now,
                               acceleration_mps2=float(accel),speed_mps=float(speed),
                               projected_stop_offset_m=float(projected_stop),
                               distance_to_queue_front_m=float(distance),position_fit_residual_m=residual))
        self.brake_flags={k:v for k,v in self.brake_flags.items() if k in active}
        return result

    def _tick_hypotheses(self,now,q,legacy,blocked):
        self.brake_observations=self._leading_brakes(now)
        for f in self.filters:
            f.braking_weights={r['origin']:self.LEADING_BRAKE_WEIGHT for r in self.brake_observations}
        q['braking']=sorted(set(q['braking'])|{r['origin'] for r in self.brake_observations})
        return super()._tick_hypotheses(now,q,legacy,blocked)

    def _summarize(self,base,results,q,blocked):
        result=super()._summarize(base,results,q,blocked)
        result['leading_brake_observations']=list(self.brake_observations)
        return result


class LeadingBrakePointTimingIntersection(LeadingBrakeTimingIntersection):
    VERSION='experimental-joint-leading-brake-point-v1'

    def __init__(self,model):
        super().__init__(model);self.point_estimator='joint_state'


class RobustTimingIntersection(LeadingBrakePointTimingIntersection):
    """Retain production's 15% long-duration branch while fitting ordinary jitter."""
    VERSION='experimental-joint-robust-tail-timing-v1'
    DURATION_TAIL_PROBABILITY=.15
