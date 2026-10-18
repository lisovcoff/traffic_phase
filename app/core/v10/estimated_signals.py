"""Operating signal estimates over the actual latent history; no periodic replay.

Hardware knowledge and modelled colors are separate from observed physical truth.
No manual transition times enter this projection or the signature assignment.
"""
from copy import deepcopy
import itertools
import json
from pathlib import Path

import numpy as np

from app.core.state_contract import prepare_logical_query

ROOT = Path(__file__).resolve().parents[3]


def resolve_profile(input_name='', requested='auto'):
    if requested == 'none':
        return None, None
    profiles = json.loads((ROOT/'config/known_intersections.json').read_text(encoding='utf-8'))
    if requested != 'auto':
        if requested not in profiles:
            raise ValueError('unknown intersection profile')
        return requested, profiles[requested]
    name = str(input_name).replace('\\','/').rsplit('/',1)[-1].casefold()
    for key, profile in profiles.items():
        if name in {v.casefold() for v in profile['known_source_names']} or any(token in name for token in profile['filename_tokens']):
            return key, profile
    return None, None


def _assign_catalog(schedule, profile):
    names = schedule['phase_names']
    groups = profile['groups']
    controlled = {head['main'] for head in profile['topology'].values()}
    controlled.update(m for head in profile['topology'].values() for m in head['arrows'])
    rows = {row['stream']: row['event_probability_by_phase'] for row in schedule['stream_activity_by_phase']}
    features = []
    for movement in sorted(controlled & rows.keys()):
        if any(name not in rows[movement] for name in names):
            continue
        values = np.asarray([rows[movement][name] for name in names], dtype=float)
        if not np.isfinite(values).all() or (values<0).any() or (values>1).any():
            continue
        span = float(np.ptp(values))
        if span > 1e-9:
            features.append((movement, (values-values.min())/span))
    if not features:
        return {}, 'NO_DISCRIMINATING_CONTROLLED_MOVEMENTS'
    scores = np.asarray([[sum(values[i]*(1 if movement in group['green_movements'] else -1)
                             for movement,values in features) for group in groups]
                         for i in range(len(names))])
    if len(names) <= len(groups):
        candidates = sorted(((sum(scores[i,j] for i,j in enumerate(order)), order)
            for order in itertools.permutations(range(len(groups)), len(names))), reverse=True)
        if len(candidates)>1 and abs(candidates[0][0]-candidates[1][0]) <= 1e-9:
            return {}, 'AMBIGUOUS_PHASE_CATALOG_ASSIGNMENT'
        chosen = candidates[0][1]
    else:
        chosen = []
        for row in scores:
            order = np.argsort(row)
            if abs(row[order[-1]]-row[order[-2]]) <= 1e-9:
                return {}, 'AMBIGUOUS_PHASE_CATALOG_ASSIGNMENT'
            chosen.append(int(order[-1]))
    return {name:groups[j]['name'] for name,j in zip(names,chosen)}, None


def _heads(topology, green):
    return {approach:dict(main=dict(state='GREEN' if head['main'] in green else 'RED',
                                  source='TRAJECTORY_PHASE_ESTIMATE'),
                         arrows=[dict(movement=m,state='GREEN' if m in green else 'OFF') for m in head['arrows']])
            for approach,head in topology.items()}


def build_estimated_signals(result, *, profile_id='auto', input_name=None):
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
    if profile:
        topology = deepcopy(profile['topology'])
        groups = profile['groups']
        mapping, error = _assign_catalog(result['schedule'],profile)
        if error:
            return {**base,'reason':error,'topology':topology}
    else:
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
    return {**base,'available':True,'reason':None,'profile_name':profile['name'] if profile else None,
        'topology_source':profile['source'] if profile else 'unverified_automatic_proposal',
        'topology':topology,'states':states,'segments':segments,
        'phase_mapping':label_to_id,'operating_phase_count':len(states),
        'phase_count_conditioned_on_operator_catalog':bool(profile),
        'unrepresented_configured_groups':[g['name'] for g in groups if g['name'] not in {s['name'] for s in states}]}
