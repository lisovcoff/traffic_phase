"""Operating signal estimates over the actual latent history; no periodic replay.

Hardware knowledge and modelled colors are separate from observed physical truth.
No manual transition times enter this projection or the signature assignment.
"""
from copy import deepcopy
import json

from app.core.state_contract import prepare_logical_query

def resolve_profile(input_name='', requested='auto'):
    """Keep the automatic path independent of source names and manual catalogues."""
    if requested not in ('auto', 'none'):
        raise ValueError('named intersection profiles are not supported; use automatic discovery')
    return None, None


def _heads(topology, green):
    return {approach:dict(main=dict(state='GREEN' if head['main'] in green else 'RED',
                                  source='TRAJECTORY_PHASE_ESTIMATE'),
                         arrows=[dict(movement=m,state='GREEN' if m in green else 'OFF') for m in head['arrows']])
            for approach,head in topology.items()}


def build_estimated_signals(result, *, profile_id='auto', input_name=None, transitions=True,
                            yellow_s=3., red_yellow_s=2., boundary_calibration=None):
    query = prepare_logical_query(result)
    key, profile = resolve_profile(input_name if input_name is not None else result.get('input',''), profile_id)
    base = dict(schema='estimated-operating-signals-v1', available=False,
        observed_physical_state='UNKNOWN', calibrated_lamp_probability=None,
        latent_phase_count=result.get('schedule',{}).get('phase_count'),
        profile_id=key, hardware_confirmed=bool(profile),
        source='known_operator_scheme' if profile else 'automatic_mapping_hypothesis',
        schedule_base_timestamp_ms=result.get('schedule_base_timestamp_ms'),
        phase_timings='trajectory_model_estimates_NOT_observed_lamp_switches',
        marks_used=False, segments=[],states=[])
    if query.validation_error or not query.segments:
        return {**base,'reason':query.validation_error or 'NO_VALID_LOCAL_HISTORY'}
    plan = result.get('physical_signal_plan') or {}
    if not plan.get('enabled') or not all(key in plan for key in ('topology','phases','mapping')):
        return {**base,'reason':'NO_SIGNAL_MAPPING'}
    topology = deepcopy(plan['topology'])
    groups = plan['phases']
    mapping = plan['mapping']
    states, indices, label_to_id = [], {}, {}
    by_name = {group['name']:group for group in groups}
    for name in query.phase_names:
        if name not in mapping or mapping[name] not in by_name:
            return {**base,'reason':'INCOMPLETE_PHASE_MAPPING'}
        group = by_name[mapping[name]]
        heads = _heads(topology,set(group['green_movements']))
        signature = json.dumps(heads,sort_keys=True)
        if signature not in indices:
            indices[signature] = len(states)
            states.append(dict(id=len(states),name=group['name'],heads=heads,
                green_movements=list(group['green_movements'])))
        label_to_id[name] = indices[signature]
    segments = []
    for start,end,phase in query.segments:
        state = label_to_id[query.phase_names[phase]]
        if segments and segments[-1][1] == start and segments[-1][2] == state:
            segments[-1][1] = end
        else:
            segments.append([start,end,state])
    estimate = {**base,'available':True,'reason':None,'profile_name':profile['name'] if profile else None,
        'topology_source':profile['source'] if profile else 'unverified_automatic_proposal',
        'hardware_scope':profile.get('hardware_scope','configured_topology') if profile else 'unverified_automatic_proposal',
        'topology':topology,'states':states,'segments':segments,
        'phase_mapping':label_to_id,'operating_phase_count':len(states),
        'phase_count_conditioned_on_operator_catalog':bool(profile),
        'unrepresented_configured_groups':[g['name'] for g in groups if g['name'] not in {s['name'] for s in states}]}
    if transitions:
        from app.core.v10.signal_timing import apply_signal_timing
        estimate=apply_signal_timing(estimate,yellow_s=yellow_s,red_yellow_s=red_yellow_s,
            boundary_calibration=boundary_calibration)
    return estimate
