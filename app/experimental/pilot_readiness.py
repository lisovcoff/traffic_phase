"""Metadata-only pilot intake. Completeness is NOT scientific validation.

No events, annotations, inference or filesystem access here. Session identities
and completeness declarations require human review against independent sources.
"""
import math

from app.experimental.phase_observation_bridge import REQUIRED

VERSION = 'real-pilot-intake-v1'
EVIDENCE_FIELDS = ('synchronization', 'logical_movement_mapping',
                   'physical_section_semantics', 'duration_prior',
                   'vehicle_delay_model', 'observation_assumptions')


def assess_pilot(manifest):
    """Report missing provenance and obvious split leakage; never approve a model.

    capture_id denotes the original continuous acquisition, not a renamed file
    or a cropped block. source_ids denote original assets before derivation.
    Both are declarations, not independently established by this function.
    """
    problems = []
    sessions = manifest.get('sessions', [])
    if manifest.get('schema') != VERSION or not isinstance(sessions, list):
        raise ValueError('INVALID_PILOT_MANIFEST')
    seen = set()
    for session in sessions:
        sid = session.get('id')
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError('INVALID_OR_DUPLICATE_SESSION_ID')
        seen.add(sid)
        if session.get('role') not in ('development', 'calibration', 'validation'):
            raise ValueError('INVALID_SESSION_ROLE')
        for field in ('capture_id', 'intersection_id', 'camera_id', 'source_ids'):
            value = session.get(field)
            if not value:
                problems.append(f'{sid}:MISSING_{field.upper()}')
        sources = session.get('source_ids', [])
        if not isinstance(sources, list) or any(not isinstance(x, str) or not x for x in sources):
            raise ValueError('INVALID_SOURCE_IDS')
        if session.get('role') == 'validation' and session.get('previously_used_for_development') is not False:
            problems.append(f'{sid}:VALIDATION_ALREADY_USED_OR_USAGE_UNKNOWN')
        for field in ('trajectory_source', 'independent_signal_source', 'synchronization'):
            item = session.get(field, {})
            if not isinstance(item, dict) or not item.get('source') or item.get('status') != 'documented':
                problems.append(f'{sid}:UNDOCUMENTED_{field.upper()}')
        sync = session.get('synchronization', {})
        uncertainty = sync.get('uncertainty_ms')
        if (isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float))
                or not math.isfinite(uncertainty) or uncertainty < 0):
            problems.append(f'{sid}:SYNC_UNCERTAINTY_UNKNOWN_OR_INVALID')
    calibration = [s for s in sessions if s['role'] == 'calibration']
    validation = [s for s in sessions if s['role'] == 'validation']
    if not calibration:
        problems.append('CALIBRATION_SESSION_NOT_REGISTERED')
    if not validation:
        problems.append('INDEPENDENT_VALIDATION_SESSION_NOT_REGISTERED')
    # Validation must be independent of ALL known development/calibration input,
    # not merely of the most recently named calibration session.
    collisions = []
    for val in validation:
        for other in sessions:
            if other['id'] == val['id']:
                continue
            reasons = []
            if val.get('capture_id') and val['capture_id'] == other.get('capture_id'):
                reasons.append('SAME_CONTINUOUS_CAPTURE')
            if set(val.get('source_ids', [])) & set(other.get('source_ids', [])):
                reasons.append('SHARED_ORIGINAL_SOURCE')
            if reasons:
                collisions.append({'validation': val['id'], 'other': other['id'], 'reasons': reasons})
                problems.append(f"{val['id']}:NONINDEPENDENT:{other['id']}")
        if not any(c.get('intersection_id') and c['intersection_id'] == val.get('intersection_id')
                   for c in calibration):
            problems.append(f"{val['id']}:SAME_INTERSECTION_CALIBRATION_MISSING")
    evidence = manifest.get('evidence', {})
    missing_evidence = [key for key in EVIDENCE_FIELDS if not isinstance(evidence.get(key), dict)
                        or evidence[key].get('status') != 'documented' or not evidence[key].get('source')]
    problems.extend(f'UNDOCUMENTED_{key.upper()}' for key in missing_evidence)
    # Reuse the actual observation bridge's list; do not invent numerical defaults.
    supplied = manifest.get('observation_model', {})
    sources = manifest.get('observation_parameter_sources', {})
    missing_parameters = [key for key in REQUIRED if supplied.get(key) is None or supplied.get(key) == '']
    unsourced_parameters = [key for key in REQUIRED if key not in missing_parameters and not sources.get(key)]
    problems.extend(f'MISSING_MODEL_INPUT:{key}' for key in missing_parameters)
    problems.extend(f'UNSOURCED_MODEL_INPUT:{key}' for key in unsourced_parameters)
    # Supplier units / geometry may be explicitly UNKNOWN if not consumed.
    for field in ('supplier_definitions', 'geometry'):
        item = manifest.get(field, {})
        if item.get('required_by_model') is not False and (item.get('status') != 'documented' or not item.get('source')):
            problems.append(f'REQUIRED_{field.upper()}_UNKNOWN')
    return dict(schema=VERSION, status='incomplete' if problems else 'ready_for_independent_review',
                problems=sorted(set(problems)), split_collisions=collisions,
                missing_model_inputs=missing_parameters, unsourced_model_inputs=unsourced_parameters,
                registered_block_count=len(sessions),
                declared_capture_count=len({s['capture_id'] for s in sessions if s.get('capture_id')}),
                inference_performed=False,
                scientific_validation='NOT_PERFORMED',
                logical_phase='UNKNOWN', physical_section='UNKNOWN', calibrated_lamp_probability=None,
                limitations=['Declared asset/capture identities are not a content deduplicator.',
                             'Documented sources are not certified truth or calibrated parameters.',
                             'No numerical model validation, likelihood or sequence inference.'])
