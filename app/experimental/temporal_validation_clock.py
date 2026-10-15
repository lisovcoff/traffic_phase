"""Frozen image/clock checks that never treat missing observations as mismatch.

Only anchors with source support throughout the declared delta domain constrain
that domain. Others abstain. No interpolation limit or geometry is fitted/relaxed.
"""
import copy
import inspect

import numpy as np

from app.experimental.vehicle_clock_alignment import (
    _intersect,conditional_clock_set,interpolate,predict,prepare_tracks,
)


def check_frozen_window(model,records,anchors):
    configured=copy.deepcopy(model)
    configured['common_observed_delta_bounds_s']=list(model['declared_delta_bounds_s'])
    domain=[list(model['declared_delta_bounds_s'])]
    tracks=prepare_tracks(records)
    gap_limit=inspect.signature(interpolate).parameters['max_gap_ms'].default
    rows=[];constraints=[]
    for row in anchors:
        record=next(r for r in records if r['id']==row['track_id'])
        track=tracks[row['track_id']]
        times=track[:,0]-model['origin_ms']
        lo,hi=[1000*(row['actual_media_pts_s']+delta) for delta in model['declared_delta_bounds_s']]
        gaps=[float(b-a) for a,b in zip(times,times[1:]) if a<hi and b>lo]
        complete=times[0]<=lo and times[-1]>=hi and bool(gaps) and max(gaps)<=gap_limit
        out=dict(track_id=row['track_id'],actual_media_pts_s=row['actual_media_pts_s'],
            requested_media_s=row.get('requested_media_s'),
            max_source_gap_in_declared_domain_ms=max(gaps,default=None),
            interpolation_limit_ms=gap_limit,full_domain_source_support=bool(complete))
        try:
            xy=predict(tracks,[row],model['homography'],model['delta_s'],model['origin_ms'])[0]
            out['nominal_prediction_px']=xy.tolist()
            out['nominal_residual_px']=float(np.linalg.norm(xy-np.asarray(row['image_point_px'])))
        except ValueError as exc:
            out['nominal_prediction_status']='UNAVAILABLE'
            out['nominal_prediction_reason']=str(exc)
        if complete:
            feasible=conditional_clock_set(configured,record,[row],row['localization_allowance_px'])
            constraints.append(feasible['delta_sets_s'])
            out['conditional_delta_sets_s']=feasible['delta_sets_s']
            out['status']='CONDITIONAL_OBSERVED_CONSTRAINT'
        else:
            out['status']='UNAVAILABLE_PARTIAL_SOURCE_SUPPORT'
            out['reason']='missing source interpolation support is not evidence against a clock value'
        rows.append(out)
    if not constraints:
        return dict(status='UNAVAILABLE_SOURCE_SUPPORT',rows=rows,conditional_clock_set_s=None,
            declared_delta_domain_s=domain[0],nominal_candidate_in_conditional_set=None,
            calibrated_sync_uncertainty_ms=None,fit_calls=0)
    for constraint in constraints:
        domain=_intersect(domain,constraint)
    compatible=any(a<=model['delta_s']<=b for a,b in domain)
    return dict(status='CONDITIONAL_FROZEN_CLOCK_COMPATIBLE' if compatible else 'FROZEN_CLOCK_INCOMPATIBLE',
        rows=rows,conditional_clock_set_s=domain,nominal_candidate_in_conditional_set=compatible,
        constraining_anchor_count=len(constraints),unavailable_anchor_count=len(rows)-len(constraints),
        calibrated_sync_uncertainty_ms=None,fit_calls=0,
        semantics='frozen-H50px feasible clock values on fully observed source domains; NOT joint calibrated uncertainty')
