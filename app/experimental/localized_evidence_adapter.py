"""Explicit integration into existing lossless evidence channels, NOT a likelihood.

The production selector/model remains unchanged. Unknown localization never
silently falls back to the old point; original events remain separate references.
"""
import copy
from dataclasses import dataclass,fields

from app.core.temporal_evidence import EvidenceUnavailable,TemporalEvent
from app.experimental.local_evidence import build_local_evidence,LocalEvidenceIndex


def event_key(event):
    fp=event.provenance.get('track_fingerprint')
    if not isinstance(fp,str) or not fp:
        raise ValueError('TRACK_FINGERPRINT_REQUIRED')
    return event.source_track_id,fp,event.timestamp_ms


def decode_event(payload):
    return TemporalEvent(**{field.name:payload[field.name] for field in fields(TemporalEvent)})


@dataclass(frozen=True)
class LocalizedEvidenceView:
    index: LocalEvidenceIndex
    references: tuple[TemporalEvent,...]
    abstentions: tuple[dict,...]
    replacements: int

    def query(self,start_ms,end_ms):
        result=self.index.query(start_ms,end_ms)
        result['restart_localization_adapter']=dict(
            mode='explicit_localized_vehicle_activity',replacement_count_total=self.replacements,
            replacement_count_in_window=sum(row['event']['evidence_method']==
                'kinematic_restart_unsmoothed_interval_proxy' for row in result['events']),
            original_events_in_window=[e.to_dict() for e in self.references if start_ms<=e.timestamp_ms<end_ms],
            abstentions=[copy.deepcopy(row) for row in self.abstentions if start_ms<=row['legacy_timestamp_ms']<end_ms],
            fallback_to_legacy_timestamp=False,production_default_changed=False,
            semantics='vehicle activity proxies; no conversion to lamp switch or permission certainty')
        return result


def build_localized_evidence_view(events,localizations,*,source_namespace,exposure_windows=None,
                                   max_events=20000):
    """Use explicit supplied results; never reads trajectories, video or labels.

    Only legacy kinematic RELEASE timestamps can be replaced. Other methods and
    demand/zone channels are passed unchanged to the accepted evidence index.
    Legacy timestamp union remains unavailable through index.legacy_streams().
    """
    if not isinstance(events,(list,tuple)) or not isinstance(localizations,(list,tuple)):
        raise TypeError('bounded event/result sequences required')
    if isinstance(max_events,bool) or not isinstance(max_events,int) or max_events<0:
        raise ValueError('INVALID_ADAPTER_EVENT_LIMIT')
    if len(events)>max_events or len(localizations)>max_events:
        raise EvidenceUnavailable('adapter event limit exceeded',reason_code='ADAPTER_EVENT_LIMIT')
    results={}
    for result in localizations:
        if result.get('legacy_event') is None:
            raise ValueError('ORIGINAL_KINEMATIC_RELEASE_REQUIRED')
        original=decode_event(result['legacy_event'])
        if original.event_type!='RELEASE' or original.evidence_method!='kinematic_restart_proxy':
            raise ValueError('ONLY_KINEMATIC_LOCALIZATION_RESULTS_ALLOWED')
        key=event_key(original)
        if key in results:
            raise ValueError('DUPLICATE_LOCALIZATION_RESULT')
        results[key]=result
    active=[];references=[];abstentions=[];replaced=0;used=set()
    for event in events:
        if not isinstance(event,TemporalEvent):
            raise TypeError('TemporalEvent required')
        if event.event_type!='RELEASE' or event.evidence_method!='kinematic_restart_proxy':
            active.append(event)
            continue
        references.append(decode_event(event.to_dict()))  # snapshot mutable provenance
        key=event_key(event)
        result=results.get(key)
        if result is not None and decode_event(result['legacy_event'])!=event:
            raise ValueError('LOCALIZATION_SOURCE_MISMATCH')
        if result is None or result['status']!='available_proxy':
            reason=('NO_LOCALIZATION_RESULT' if result is None else
                    result['estimate'].get('abstention_reason'))
            if not reason:
                raise ValueError('MISSING_ABSTENTION_REASON')
            abstentions.append(dict(source_track_id=event.source_track_id,
                track_fingerprint=key[1],legacy_timestamp_ms=event.timestamp_ms,reason=reason,
                alternatives=[] if result is None else copy.deepcopy(result['alternatives'])))
            if result is not None:
                used.add(key)
            continue
        localized=decode_event(result['localized_event'])
        names=('event_type','movement','source_track_id','confidence','evidence_quality','temporal_uncertainty_ms')
        provenance_names=('source','track_fingerprint','role','proxy','verified_stop_line','signal_state_observed')
        if (any(getattr(localized,name)!=getattr(event,name) for name in names)
                or any(localized.provenance.get(name)!=event.provenance.get(name) for name in provenance_names)
                or localized.provenance.get('track_fingerprint')!=key[1]
                or localized.provenance.get('legacy_timestamp_ms')!=event.timestamp_ms
                or localized.evidence_method!='kinematic_restart_unsmoothed_interval_proxy'):
            raise ValueError('LOCALIZATION_CONTRACT_MISMATCH')
        active.append(localized);replaced+=1;used.add(key)
    if used!=set(results):
        raise ValueError('UNMATCHED_LOCALIZATION_RESULT')
    index=build_local_evidence(active,source_namespace=source_namespace,
                               exposure_windows=exposure_windows,max_events=max_events)
    return LocalizedEvidenceView(index,tuple(references),tuple(abstentions),replaced)
