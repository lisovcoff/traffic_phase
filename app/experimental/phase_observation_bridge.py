"""Opt-in preparation for the existing joint likelihood; never runs inference.

Latent vehicle times are not lamp-switch times. Positive off-phase intensities
allow anticipation, creep or permissive movement without assigning their cause.
Unknown exposure/demand is not silently replaced by complete exposure.
"""
import copy
import hashlib
import json
import math

from app.core.state_contract import StateEstimate, physical_estimate
from app.experimental.joint_track_model import ModelUnavailable, observation_components

VERSION = 'experimental-phase-observation-bridge-v2'
REQUIRED = ('rates_per_s', 'rate_source', 'release_delay_s', 'transit_delay_s',
            'delay_source', 'latent_demand_exposure', 'demand_source',
            'observation_windows_s', 'observation_window_source',
            'release_detection_probability', 'crossing_detection_probability',
            'release_method', 'crossing_method', 'horizon_s', 'movements')


def _seal(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def prepare_joint_observation(view, spec=None, *, origin_ms=None, max_events=512):
    """Snapshot a local-evidence query and build bounded observation components.

    Supplied windows are relative to origin_ms. Event times are translated exactly,
    never rounded to fit the synthetic clock. No defaults for scientific inputs.
    The returned components feed joint_track_model.path_loglik, NOT legacy HSMM.
    This is model readiness, not acceptance/calibration or a phase estimate.
    """
    base = dict(schema=VERSION, status='unavailable', reason=None,
        logical_phase=StateEstimate('UNKNOWN', 'logical_phase', VERSION,
            abstention_reason='NO_SEQUENCE_INFERENCE_IN_THIS_COMPONENT').to_dict(),
        physical_section=physical_estimate('UNKNOWN', source=VERSION).to_dict(),
        calibrated_lamp_probability=None, production_default_changed=False,
        assumptions=['one likelihood contribution per identified vehicle',
            'silence is informative only under supplied demand/exposure/detection',
            'vehicle activity may precede GREEN; latent vehicle time is not a switch',
            'latent phase/intensity grid remains a limitation; no timestamp rounding'],
        missing_inputs=[], components=None)
    if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 0:
        return {**base, 'reason': 'INVALID_EVENT_LIMIT'}
    if not isinstance(view, dict) or view.get('schema') != 'experimental-local-evidence-v1' or view.get('status') != 'available':
        return {**base, 'reason': 'AVAILABLE_LOCAL_EVIDENCE_VIEW_REQUIRED'}
    query_range=view.get('range_ms')
    if (not isinstance(query_range,(list,tuple)) or len(query_range)!=2 or any(
            isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x)
            for x in query_range) or query_range[1]<=query_range[0]):
        return {**base,'reason':'QUERY_TIMESTAMP_DOMAIN_REQUIRED'}
    rows = view.get('events', [])
    if not isinstance(rows, list) or len(rows) > max_events:
        return {**base, 'reason': 'EVENT_BUDGET_EXHAUSTED'}
    if any(r.get('eligible_vehicle_evidence') and r['event']['event_type'] not in
           ('RELEASE', 'CROSSING_PROXY') for r in rows):
        return {**base, 'reason': 'ELIGIBLE_CHANNEL_NOT_IN_JOINT_MODEL'}
    base.update(input_sha256=_seal(view), event_count=len(rows),
        vehicle_group_count=len({r.get('vehicle_group_id') for r in rows
            if r.get('eligible_vehicle_evidence') and r.get('vehicle_group_id')}),
        origin_ms=origin_ms, supplied_model_sha256=_seal(spec))
    if spec is not None and not isinstance(spec, dict):
        return {**base, 'reason': 'OBSERVATION_MODEL_OBJECT_REQUIRED'}
    supplied = {} if spec is None else spec
    missing = [k for k in REQUIRED if supplied.get(k) is None or supplied.get(k) == '']
    if missing:
        return {**base, 'reason': 'OBSERVATION_MODEL_INPUTS_UNKNOWN', 'missing_inputs': missing}
    h = supplied['horizon_s']
    if isinstance(h, bool) or not isinstance(h, int) or not 0 < h <= 80:
        return {**base, 'reason': 'HORIZON_BUDGET_EXHAUSTED'}
    if isinstance(origin_ms, bool) or not isinstance(origin_ms, (int, float)) or not math.isfinite(origin_ms):
        return {**base, 'reason': 'EXPLICIT_CLOCK_ORIGIN_REQUIRED'}
    # This bridge is for unverified vehicle proxies, not exclusive synthetic marks.
    try:
        if any(not math.isfinite(x) or x <= 0 for row in supplied['rates_per_s'] for x in row):
            return {**base, 'reason': 'NONEXCLUSIVE_POSITIVE_INTENSITIES_REQUIRED_FOR_PROXY_BRIDGE'}
    except (TypeError, ValueError):
        return {**base, 'reason': 'INVALID_INTENSITY_MATRIX'}
    relative = copy.deepcopy(view)
    relative['range_ms']=[x-origin_ms for x in query_range]
    for row in relative['events']:
        row['event']['timestamp_ms'] -= origin_ms
    # Keep original provenance/timestamp brackets unchanged: no false clock conversion.
    # observation_components consumes only translated timestamp fields, not provenance.
    try:
        backend=supplied.get('clock_model','legacy_finite_clock')
        if backend=='continuous_latent_rounded_marks':
            from app.experimental.rounded_observation import rounded_components
            components=rounded_components(relative,copy.deepcopy(supplied),max_tracks=max_events)
        elif backend=='legacy_finite_clock':
            components = observation_components(relative, copy.deepcopy(supplied), max_tracks=max_events)
        else:
            raise ModelUnavailable('UNSUPPORTED_CLOCK_MODEL')
    except ModelUnavailable as exc:
        return {**base, 'reason': str(exc),
            'observation_domain':getattr(exc,'observation_domain',None)}
    return {**base, 'status': 'ready_for_declared_model_only', 'reason': None,
            'components': components,
            'event_time_translation': {'origin_ms': origin_ms,
                'component_track_timestamps': 'relative_ms',
                'input_event_provenance': 'unchanged_original_clock',
                'rounding_applied': False}}
