"""Production recovery backend. Prediction receives only trajectory evidence.

The bounded cyclic fit is reused with explicit per-call backends. There are no
global monkeypatches, reference-video corrections, filename-based K or test labels.
"""
from array import array
from collections import defaultdict
from pathlib import Path
import numpy as np

from app.core.temporal_evidence import EventStreamBundle
from app.core.v9.fit import discover_phase_count,PhaseCountSearch,PhaseSearchConfig
from app.core.v9.primitives import infer_period
from app.core.v9.vehicle_evidence import select_permission_events_per_track
from app.core.recovery.grouping import rate_equivalent_mapping,merge_rate_equivalent_phases
from app.core.recovery.clock import regularize_phase_clock
from app.core.recovery.motion import extract_motion_evidence

VERSION='trajectory_recovery_v1'


def recovery_phase_search(x,by_stream,period,**kwargs):
    result=discover_phase_count(x,by_stream,period,**kwargs)
    selected,candidates,fits=result
    if selected is None:return result
    supported=[]
    for candidate in candidates:
        k=candidate['k'];probs=np.asarray(fits[k]['probs'])
        high=np.maximum(.010001,.25*probs.max(axis=0))
        active=np.any(probs>high[None,:],axis=1)
        candidate['recovery_quiet_components']=int(np.sum(~active))
        labels=np.asarray(fits[k]['labels'])
        counts=np.array([x[labels==z].sum(axis=0) for z in range(k)])
        den=np.maximum(counts.sum(axis=1,keepdims=True),1e-12)
        ll=float(np.sum(counts*np.log(np.maximum(counts/den,1e-15))))
        candidate['recovery_mark_bic']=float(-2*ll+(k*x.shape[1]-1)*np.log(max(2.,counts.sum())))
        if np.all(active) and np.isfinite(candidate['recovery_mark_bic']):supported.append(candidate)
    winner=min(supported,key=lambda c:c['recovery_mark_bic'])['k'] if supported else selected
    reason='conditional_mark_bic_for_weak_signatures'
    base=[c for c in candidates if not c['recovery_quiet_components'] and np.isfinite(c['selection_score'])]
    if base:
        original=min(base,key=lambda c:c['selection_score'])
        original_groups=len(set(rate_equivalent_mapping(fits[original['k']]['probs'],cosine_min=0.)[0].values()))
        new_groups=len(set(rate_equivalent_mapping(fits[winner]['probs'],cosine_min=0.)[0].values()))
        if not original['unsupported_phase_count'] or new_groups<=original_groups:
            winner=original['k'];reason='supported_bernoulli_candidate'
    diagnostic={**result.diagnostics,'selected_k':winner,'original_selected_k':selected,
        'recovery_no_quiet_phase':True,'supported_candidate_count':len(supported),'recovery_selection':reason,
        'score_margin':None,'score_margin_semantics':'hybrid_selection_NOT_calibrated_confidence',
        'mark_alternatives_ranked':[c['k'] for c in sorted(supported,key=lambda c:c['recovery_mark_bic'])]}
    return PhaseCountSearch(winner,candidates,fits,diagnostic)


def discover_bundle(bundle,*,input_name='trajectories',dt=1.,phase_search_config=None):
    from app.core.v9.model import _discover_bundle
    selected,methods=select_permission_events_per_track(bundle.temporal_events)
    streams=defaultdict(list)
    for event in selected:streams[event.movement].append((event.timestamp_ms-bundle[7])/1000)
    derived=EventStreamBundle(tuple(bundle),temporal_events=bundle.temporal_events,
        permission_streams={k:array('d',v) for k,v in streams.items()},diagnostics=bundle.diagnostics)
    result=_discover_bundle(derived,input_name=input_name,dt=dt,marks_path=None,
        evidence_policy='permission_per_stream',phase_search_config=phase_search_config,
        experimental_local_history=False,_search_backend=recovery_phase_search,
        _period_backend=lambda demand:infer_period(derived.permission_streams),_full_recording=True)
    result=merge_rate_equivalent_phases(result,cosine_min=0.)
    result=regularize_phase_clock(result,bundle.temporal_events,boundary_sigma_s=.75)
    result['algorithm']='Traffic Phase — trajectory-only phase recovery'
    result['schedule']['model']='permission_conditioned_cyclic_hsmm_with_queue_front_clock'
    result['phase_evidence'].update(source='permission_per_track',selection_scope='per_track',
        selection_by_movement=methods,demand_entries_used_for_phase_evidence=False)
    result['phase_model_selection']['criterion']='supported_bernoulli_or_conditional_mark_bic_then_permission_signature_merge'
    result['recovery_model']=dict(version=VERSION,video_used=False,annotations_received=False,
        reference_video_bias_applied=False,complete_input_processed=True,
        full_controller_count_identified=False,phase_count_scope='observed_logical_movement_signatures',
        settings=dict(quiet_relative_threshold=.25,quiet_floor=.010001,merge_same_support=True,
            boundary_regularization_sigma_s=.75,clock_stationarity_max_front_mad_s=2.))
    return result


def discover_path(path,*,dt=1.,source_member=None,session_id=None,phase_search_config=None):
    from app.core.v9.events import load_event_streams
    from app.core.v9.source_scope import choose_source,choose_session,attach_input_scope
    path=Path(path);member,sources=choose_source(path,source_member)
    bundle=load_event_streams(path,source_member=member if source_member is not None or len(sources)>1 else None,
        _event_extractor=extract_motion_evidence)
    scoped,selected,sessions=choose_session(bundle,member,session_id)
    result=discover_bundle(scoped,input_name=str(path),dt=dt,phase_search_config=phase_search_config)
    return attach_input_scope(result,member,selected,sessions,source_count=len(sources))
