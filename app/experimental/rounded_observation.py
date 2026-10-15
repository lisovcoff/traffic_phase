"""Exact piecewise integration for continuous vehicle time and rounded marks.

Shares the existing joint track likelihood interface; no sequence inference.
Resolution is a supplied measurement model, never an extractor confidence radius.
"""
import math

import numpy as np

from app.experimental.joint_track_model import GRID_S, ModelUnavailable, tracks_from_view


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _mass(rows):
    if not isinstance(rows, list) or not rows or len(rows)>64:
        raise ModelUnavailable('BOUNDED_SUPPLIED_DELAY_MASS_REQUIRED')
    if any(not isinstance(r, list) or len(r)!=2 or not _finite(r[0]) or r[0]<0
           or not _finite(r[1]) or r[1]<=0 for r in rows):
        raise ModelUnavailable('INVALID_DELAY_MASS')
    if len({r[0] for r in rows})!=len(rows) or abs(sum(r[1] for r in rows)-1)>1e-10:
        raise ModelUnavailable('UNNORMALIZED_DELAY_MASS')
    return rows


def rounded_components(view, spec, *, max_tracks=512, max_q_cells=50000,
                       max_pieces=2000000):
    """Return q fractions and detection exposure for joint_track_model.path_loglik.

    Intensity is constant within each 2s latent cell. Integration is analytic
    piecewise-constant integration, not sampling/quadrature approximation.
    No latent vehicles outside [0,horizon): explicit finite-input assumption.
    """
    h=spec.get('horizon_s'); names=spec.get('movements')
    if not isinstance(h, int) or isinstance(h, bool) or not 0<h<=80 or h%GRID_S:
        raise ModelUnavailable('BOUNDED_GRID_ALIGNED_LATENT_HORIZON_REQUIRED')
    if not isinstance(names, list) or not names or len(names)>16 or any(not isinstance(x,str) for x in names) or len(set(names))!=len(names):
        raise ModelUnavailable('INVALID_MOVEMENT_NAMES')
    required=('rate_source','delay_source','demand_source','observation_window_source',
              'timestamp_resolution_source')
    if any(not spec.get(k) for k in required):
        raise ModelUnavailable('SUPPLIED_SCIENTIFIC_SOURCES_REQUIRED')
    n=h//GRID_S
    try:
        rates=np.asarray(spec.get('rates_per_s'), dtype=float)
        exposure=np.asarray(spec.get('latent_demand_exposure'), dtype=float)
    except (TypeError,ValueError):
        raise ModelUnavailable('INVALID_RATE_OR_EXPOSURE') from None
    if rates.ndim!=2 or rates.shape[0] not in (2,3) or rates.shape[1]!=len(names) or not np.isfinite(rates).all() or (rates<0).any():
        raise ModelUnavailable('INVALID_INTENSITY_MATRIX')
    if exposure.shape!=(len(names),n) or not np.isfinite(exposure).all() or (exposure<0).any():
        raise ModelUnavailable('SUPPLIED_DEMAND_EXPOSURE_REQUIRED')
    resolution=spec.get('timestamp_resolution_ms')
    if not _finite(resolution) or resolution<=0:
        raise ModelUnavailable('SUPPLIED_TIMESTAMP_RESOLUTION_REQUIRED')
    rounding_origin=spec.get('timestamp_rounding_origin_ms')
    if not _finite(rounding_origin):
        raise ModelUnavailable('SUPPLIED_ROUNDING_CLOCK_ORIGIN_REQUIRED')
    windows=spec.get('observation_windows_s')
    if not isinstance(windows,list) or len(windows)>32:
        raise ModelUnavailable('BOUNDED_OBSERVATION_WINDOWS_REQUIRED')
    prev=0
    for row in windows:
        if not isinstance(row,list) or len(row)!=2 or any(not _finite(x) for x in row) or not 0<=row[0]<row[1] or row[0]<prev:
            raise ModelUnavailable('INVALID_OBSERVATION_WINDOWS')
        prev=row[1]
    delays=_mass(spec.get('release_delay_s')); transits=_mass(spec.get('transit_delay_s'))
    if len(delays)*len(transits)>64:
        raise ModelUnavailable('DELAY_PAIR_BUDGET_EXHAUSTED')
    pr=spec.get('release_detection_probability'); pc=spec.get('crossing_detection_probability')
    if not _finite(pr) or not _finite(pc) or not 0<=pr<=1 or not 0<=pc<=1:
        raise ModelUnavailable('SUPPLIED_DETECTION_PROBABILITIES_REQUIRED')
    rows=view.get('events',[])
    if len(rows)>max_tracks*2:
        raise ModelUnavailable('EVENT_BUDGET_EXHAUSTED')
    if any(r.get('eligible_vehicle_evidence') and r['event']['event_type'] not in ('RELEASE','CROSSING_PROXY') for r in rows):
        raise ModelUnavailable('ELIGIBLE_CHANNEL_NOT_IN_JOINT_MODEL')
    tracks=tracks_from_view(view,spec)
    if len(tracks)>max_tracks or n*len(tracks)>max_q_cells:
        raise ModelUnavailable('TRACK_OR_Q_CELL_BUDGET_EXHAUSTED')
    bound=n*len(delays)*len(transits)*(1+len(tracks))*(4*len(windows)+7)
    if bound>max_pieces:
        raise ModelUnavailable('INTEGRATION_PIECE_BUDGET_EXHAUSTED')
    def visible(t): return any(a<=t<b for a,b in windows)
    half=resolution/2000
    for t in tracks:
        if t['movement'] not in names: raise ModelUnavailable('MOVEMENT_NOT_IN_RATE_MODEL')
        for field in ('release_ms','crossing_ms'):
            v=t[field]
            if v is not None and _finite(v):
                projected=round((v-rounding_origin)/resolution)*resolution+rounding_origin
                if abs(v-projected)>max(1e-7,abs(v)*1e-15):
                    raise ModelUnavailable('TIMESTAMP_NOT_ON_SUPPLIED_ROUNDING_CLOCK')
            if v is not None and (not _finite(v) or not any(
                    a<v/1000+half and v/1000-half<b for a,b in windows)):
                raise ModelUnavailable('OBSERVATION_OUTSIDE_SUPPLIED_WINDOWS')
    q=np.zeros((len(tracks),n)); detected=np.zeros(n)
    pieces=0
    for j in range(n):
        lo=j*GRID_S; hi=lo+GRID_S
        for d,pd in delays:
            for lag,pt in transits:
                cuts=[x-shift for w in windows for x in w for shift in (d,d+lag)]
                def integrate(fun, extra=()):
                    nonlocal pieces
                    points=sorted({lo,hi,*[x for x in (*cuts,*extra) if lo<x<hi]})
                    pieces+=len(points)-1
                    return sum((b-a)*fun((a+b)/2) for a,b in zip(points,points[1:]))/GRID_S
                def detection(u):
                    a=pr if visible(u+d) else 0.
                    b=pc if visible(u+d+lag) else 0.
                    return 1-(1-a)*(1-b)
                detected[j]+=pd*pt*integrate(detection)
                for i,t in enumerate(tracks):
                    r=t['release_ms']; c=t['crossing_ms']
                    extra=[]
                    for v,shift in ((r,d),(c,d+lag)):
                        if v is not None: extra.extend((v/1000-half-shift,v/1000+half-shift))
                    def pattern(u):
                        a=pr if visible(u+d) else 0.
                        b=pc if visible(u+d+lag) else 0.
                        ar=(1-a) if r is None else (a if r/1000-half<=u+d<r/1000+half else 0.)
                        bc=(1-b) if c is None else (b if c/1000-half<=u+d+lag<c/1000+half else 0.)
                        return ar*bc
                    q[i,j]+=pd*pt*integrate(pattern,extra)
    if len(tracks) and np.any(q.sum(axis=1)<=0):
        raise ModelUnavailable('TRACK_PATTERN_UNSUPPORTED_BY_DELAY_DETECTION_MODEL')
    return dict(tracks=tracks,q=q,detected_probability=detected,rates=rates,
        exposure=exposure,movements=names,n=n,integration_pieces=pieces,
        observation_model='continuous_latent_rounded_marks',
        timestamp_resolution_ms=resolution,
        limitations=['supplied rounding kernel, not calibrated extractor uncertainty',
            'no latent vehicles outside supplied finite horizon',
            'phase/intensity boundaries remain on 2s latent grid'])
