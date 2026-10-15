"""Safe interior target under explicitly supplied bounded vehicle delays.

Does not run a decoder. Context phase history must be inferred jointly; target
is never re-anchored as a new independent sequence at its left edge.
"""
import copy
import math

from app.core.temporal_evidence import EvidenceUnavailable
from app.core.state_contract import StateEstimate,physical_estimate
from app.experimental.rounded_observation import _mass,_finite
from app.experimental.joint_track_model import ModelUnavailable
from app.experimental.phase_observation_bridge import prepare_joint_observation


def prepare_context_observation(index,spec,*,context_origin_ms,target_range_ms,max_events=512):
    """Query supplied immutable index once; keep namespace and vehicle identity."""
    base=dict(schema='experimental-context-observation-v1',status='unavailable',components=None,
        logical_phase=StateEstimate('UNKNOWN','logical_phase','context_observation',
            abstention_reason='NO_VALIDATED_SEQUENCE_RECONSTRUCTION').to_dict(),
        physical_section=physical_estimate('UNKNOWN',source='context_observation').to_dict(),
        calibrated_lamp_probability=None,production_default_changed=False)
    try:
        if not isinstance(spec,dict) or spec.get('clock_model')!='continuous_latent_rounded_marks':
            raise ModelUnavailable('EXPLICIT_ROUNDED_CLOCK_MODEL_REQUIRED')
        if not _finite(context_origin_ms) or context_origin_ms<0:
            raise ModelUnavailable('FINITE_NONNEGATIVE_CONTEXT_ORIGIN_REQUIRED')
        h=spec.get('horizon_s');r=spec.get('timestamp_resolution_ms');o=spec.get('timestamp_rounding_origin_ms')
        if isinstance(h,bool) or not isinstance(h,int) or not 0<h<=80 or h%2:
            raise ModelUnavailable('BOUNDED_CONTEXT_HORIZON_REQUIRED')
        if not _finite(r) or r<=0 or not _finite(o):
            raise ModelUnavailable('SUPPLIED_ROUNDING_CLOCK_REQUIRED')
        delays=_mass(spec.get('release_delay_s'));transits=_mass(spec.get('transit_delay_s'))
        if len(delays)*len(transits)>64:raise ModelUnavailable('DELAY_PAIR_BUDGET_EXHAUSTED')
        pr=spec.get('release_detection_probability');pc=spec.get('crossing_detection_probability')
        if not _finite(pr) or not _finite(pc) or not 0<=pr<=1 or not 0<=pc<=1:
            raise ModelUnavailable('SUPPLIED_DETECTION_PROBABILITIES_REQUIRED')
        shifts=([d for d,_ in delays] if pr else [])+([d+lag for d,_ in delays for lag,_ in transits] if pc else [])
        dmax=max(shifts,default=0)*1000
        # Entire retained rounding cells must lie in [Dmax,h); no latent u<0 or u>=h.
        first=o+math.ceil((dmax+r/2-o)/r)*r
        last=o+math.floor((h*1000-r/2-o)/r)*r
        if first>last:raise ModelUnavailable('NO_SAFE_CONTEXT_OBSERVATION_DOMAIN')
        lower=first-r/2;upper=last+r/2
        safe=[context_origin_ms+lower,context_origin_ms+upper-dmax]
        if (not isinstance(target_range_ms,(list,tuple)) or len(target_range_ms)!=2
                or any(not _finite(t) for t in target_range_ms) or target_range_ms[0]>=target_range_ms[1]):
            raise ModelUnavailable('VALID_TARGET_INTERVAL_REQUIRED')
        if not safe[0]<=target_range_ms[0]<target_range_ms[1]<=safe[1]:
            return {**base,'reason':'TARGET_OUTSIDE_SAFE_CONTEXT_INTERIOR',
                'safe_target_range_ms':safe,'requested_target_range_ms':list(target_range_ms)}
        if isinstance(max_events,bool) or not isinstance(max_events,int) or max_events<0:
            raise ModelUnavailable('INVALID_EVENT_LIMIT')
        query=[context_origin_ms+first,context_origin_ms+last+r]
        view=index.query(*query,max_events=max_events)
        supplied=copy.deepcopy(spec);supplied['query_delivery_mode']='censored_reported_timestamps'
        prepared=prepare_joint_observation(view,supplied,origin_ms=context_origin_ms,max_events=max_events)
        if prepared['status']!='ready_for_declared_model_only':
            return {**base,'reason':prepared['reason'],'observation_readiness':prepared}
        plan=dict(context_range_ms=[context_origin_ms,context_origin_ms+h*1000],
            target_range_ms=list(target_range_ms),queried_reported_range_ms=query,
            retained_true_mark_range_ms=[context_origin_ms+lower,context_origin_ms+upper],
            safe_target_range_ms=safe,max_enabled_vehicle_delay_ms=dmax,
            population_boundary_assumption='bounded nonnegative supplied delays; NOT calibrated for real RELEASE',
            source_namespace=view['source_namespace'],
            edge_policy='outside target UNKNOWN; no independent target restart or overlap multiplication',
            upstream_completeness='ASSUMED_SUPPLIED_INDEX_ONLY',
            context_phase_history_required=True)
        return {**base,'status':'ready_for_supplied_context_model_only','reason':None,
            'components':prepared['components'],'context_plan':plan,'evidence_view':view,
            'input_sha256':prepared['input_sha256'],'supplied_model_sha256':prepared['supplied_model_sha256']}
    except OverflowError:
        return {**base,'reason':'CONTEXT_DOMAIN_NUMERIC_LIMIT'}
    except (ModelUnavailable,EvidenceUnavailable,ValueError,TypeError,KeyError,AttributeError) as exc:
        return {**base,'reason':getattr(exc,'reason_code',None) or str(exc)}
