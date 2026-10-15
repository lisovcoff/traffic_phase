"""Lossless local vehicle channels, not a signal observation likelihood.

No numeric vehicle timestamps are implicitly converted to lamp switches.
All windows are half-open. The caller supplies exposure; silence never supplies it.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import time

from app.core.temporal_evidence import EvidenceUnavailable, TemporalEvent
from app.core.state_contract import physical_estimate

VERSION = 'experimental-local-evidence-v1'
ROLES = {'ENTRY': 'demand', 'STOP': 'vehicle_stationary', 'RELEASE': 'restart_proxy',
         'CROSSING_PROXY': 'zone_transition_proxy', 'CROSSING': 'vehicle_crossing_verified_geometry'}


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _finite(value):
    return isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _interval(start, end):
    if not _finite(start) or not _finite(end) or not 0 <= start < end:
        raise ValueError('finite nonnegative half-open interval required')


def _eligibility(event):
    """Same RELEASE/proxy gates as accepted selector, without stream-wide choice."""
    if event.event_type == 'RELEASE':
        return (True,None) if event.evidence_quality != 'LOW' else (False,'LOW_QUALITY_RELEASE')
    if event.event_type == 'CROSSING_PROXY':
        p=event.provenance
        if not p.get('eligible_proxy'): return False,'INELIGIBLE_PROXY'
        if p.get('conflicting_timestamps'): return False,'CONFLICTING_TIMESTAMPS'
        if p.get('invalid_detections'): return False,'INVALID_DETECTIONS'
        return True,None
    if event.event_type == 'CROSSING':
        return True,None  # TemporalEvent requires verified_stop_line; still not GREEN.
    return False,'DEMAND_ONLY' if event.event_type == 'ENTRY' else 'STATIONARY_VEHICLE_NOT_RED'


@dataclass(frozen=True)
class ExposureWindow:
    start_ms: float
    end_ms: float
    source: str

    def __post_init__(self):
        _interval(self.start_ms,self.end_ms)
        if not isinstance(self.source,str) or not self.source.strip():
            raise ValueError('supplied exposure needs its own source')


@dataclass(frozen=True)
class _EventRow:
    timestamp_ms: float
    event_id: str
    vehicle_group_id: str | None
    serialized_event: str
    eligible: bool
    exclusion_reason: str | None
    source_indices: tuple[int,...]


@dataclass(frozen=True)
class LocalEvidenceIndex:
    rows: tuple[_EventRow,...]
    times: tuple[float,...]
    namespace: str
    exposure: tuple[ExposureWindow,...] | None
    input_event_count: int
    duplicate_events: int

    def legacy_streams(self):
        raise EvidenceUnavailable('separate source channels require an explicit observation model; no implicit timestamp union',
                                  reason_code='METHOD_DEPENDENCE_AND_EVENT_SIGNAL_DELAY_UNMODELLED')

    def query(self, start_ms, end_ms, *, max_duration_s=1800, max_events=100000):
        _interval(start_ms,end_ms)
        if not _finite(max_duration_s) or max_duration_s<=0 or isinstance(max_events,bool) or not isinstance(max_events,int) or max_events<0:
            raise ValueError('invalid query limits')
        if end_ms-start_ms > max_duration_s*1000:
            raise EvidenceUnavailable('query duration limit exceeded',reason_code='QUERY_DURATION_LIMIT')
        left,right=bisect_left(self.times,start_ms),bisect_left(self.times,end_ms)
        if right-left>max_events:
            raise EvidenceUnavailable('query event limit exceeded',reason_code='QUERY_EVENT_LIMIT')
        rows=self.rows[left:right]
        channels=defaultdict(list)
        correlated=defaultdict(list)
        source_rows=[]
        eligible_groups=set()
        unidentified=0
        conflicts=[]
        for row in rows:
            event=json.loads(row.serialized_event)
            in_exposure=(None if self.exposure is None else any(w.start_ms<=row.timestamp_ms<w.end_ms for w in self.exposure))
            item={'event_id':row.event_id,'vehicle_group_id':row.vehicle_group_id,
                  'source_indices':list(row.source_indices),'event':event,
                  'role':ROLES[event['event_type']],
                  'eligible_vehicle_evidence':row.eligible,'exclusion_reason':row.exclusion_reason,
                  'supplied_exposure_contains_timestamp':in_exposure,
                  'signal_relation':'UNKNOWN','calibrated_lamp_probability':None}
            source_rows.append(item)
            channels[(event['movement'],event['event_type'],event['evidence_method'])].append(row.event_id)
            if row.vehicle_group_id is not None:
                correlated[row.vehicle_group_id].append(row.event_id)
                if row.eligible: eligible_groups.add(row.vehicle_group_id)
            elif row.eligible:
                unidentified+=1
            if in_exposure is False: conflicts.append(row.event_id)
        supplied=[] if self.exposure is None else [
            {'start_ms':max(start_ms,w.start_ms),'end_ms':min(end_ms,w.end_ms),'source':w.source}
            for w in self.exposure if w.start_ms<end_ms and start_ms<w.end_ms]
        supplied_ms=sum(w['end_ms']-w['start_ms'] for w in supplied)
        exposure_status=('UNKNOWN' if self.exposure is None else
                         'SUPPLIED_FULL_WINDOW' if supplied_ms==end_ms-start_ms else
                         'SUPPLIED_PARTIAL_WINDOW' if supplied_ms else 'NO_SUPPLIED_WINDOW_SUPPORT')
        count=sum(row.eligible for row in rows)
        reason=None if count else 'NO_ELIGIBLE_LOCAL_MOVEMENT_EVIDENCE' if rows else 'NO_LOCAL_EVENTS'
        return {'schema':VERSION,'status':'available','range_ms':[start_ms,end_ms],
                'source_namespace':self.namespace,'events':source_rows,
                'channels':[{'movement':m,'event_type':t,'method':method,'event_ids':ids,'event_count':len(ids)}
                            for (m,t,method),ids in sorted(channels.items())],
                'correlated_vehicle_groups':dict(correlated),
                'counts':{'events':len(rows),'eligible_vehicle_events':count,
                          'known_vehicle_groups_with_eligible_evidence':len(eligible_groups),
                          'eligible_events_without_track_identity':unidentified,
                          'events_by_type':dict(Counter(json.loads(r.serialized_event)['event_type'] for r in rows))},
                'observation_support':{'status':exposure_status,'supplied_windows':supplied,
                    'supplied_duration_s':None if self.exposure is None else supplied_ms/1000,
                    'source':'explicit caller input, never inferred from event absence',
                    'event_ids_outside_supplied_windows':conflicts,'demand':'UNKNOWN'},
                'abstention_reason':reason,
                'logical_phase':{'estimated_state':'UNKNOWN','reason':'NO_SEQUENCE_INFERENCE_IN_THIS_COMPONENT'},
                'physical_section':physical_estimate('UNKNOWN',source=VERSION).to_dict(),
                'legacy_likelihood_compatibility':{'status':'unavailable',
                    'reason':'METHOD_DEPENDENCE_AND_EVENT_SIGNAL_DELAY_UNMODELLED'},
                'assumptions':['counts are vehicle evidence, not independent lamp observations',
                               'track fingerprints identify correlation groups, not calibrated independence',
                               'no-event bins cannot identify no-demand, blockage or RED',
                               'event-to-signal delay and permissive/protected semantics UNKNOWN']}


def build_local_evidence(events, *, source_namespace, exposure_windows=None,
                         max_events=20000, max_seconds=30.0):
    """Snapshot existing TemporalEvent contracts, retaining all channels.

    Identity/dedup depends only on the event, never remote events or phase labels.
    Missing fingerprints remain unidentified; numeric IDs alone are not reliable.
    """
    if events is None:
        raise EvidenceUnavailable('event input missing',reason_code='MISSING_EVENT_INPUT')
    if not isinstance(source_namespace,str) or not source_namespace.strip():
        raise ValueError('source namespace required')
    if isinstance(max_events,bool) or not isinstance(max_events,int) or max_events<0 or not _finite(max_seconds) or max_seconds<0:
        raise ValueError('invalid build limits')
    deadline=time.monotonic()+max_seconds
    exposure=None
    if exposure_windows is not None:
        supplied=[]
        for window in exposure_windows:
            if len(supplied)>=1000 or time.monotonic()>=deadline:
                raise EvidenceUnavailable('supplied exposure budget exceeded',reason_code='EXPOSURE_INPUT_LIMIT')
            supplied.append(window)
        exposure=tuple(supplied)
        if any(not isinstance(w,ExposureWindow) for w in exposure): raise ValueError('ExposureWindow required')
        if any(a.end_ms>b.start_ms for a,b in zip(exposure,exposure[1:])):
            raise ValueError('exposure windows must be ordered and disjoint')
    unique={}
    count=0
    for index,event in enumerate(events):
        if time.monotonic()>=deadline:
            raise EvidenceUnavailable('build time limit exceeded',reason_code='EVIDENCE_TIME_LIMIT')
        if index>=max_events:
            raise EvidenceUnavailable('build event limit exceeded',reason_code='EVIDENCE_EVENT_LIMIT')
        if not isinstance(event,TemporalEvent): raise TypeError('TemporalEvent required; no annotations accepted')
        if isinstance(event.timestamp_ms,bool) or not _finite(event.timestamp_ms) or event.timestamp_ms<0:
            raise ValueError('invalid event timestamp')
        if not isinstance(event.movement,str) or not event.movement.strip(): raise ValueError('movement required')
        payload=event.to_dict()
        serialized=_canonical(payload)
        eid=_hash([source_namespace,payload])
        count+=1
        if eid in unique:
            unique[eid][1].append(index)
            continue
        fp=event.provenance.get('track_fingerprint')
        group=(_hash([source_namespace,event.provenance.get('source'),fp])
               if isinstance(fp,str) and fp else None)
        eligible,reason=_eligibility(event)
        unique[eid]=[(event.timestamp_ms,eid,group,serialized,eligible,reason),[index]]
    if time.monotonic()>=deadline:
        raise EvidenceUnavailable('build time limit exceeded',reason_code='EVIDENCE_TIME_LIMIT')
    rows=tuple(sorted((_EventRow(*v[0],tuple(v[1])) for v in unique.values()), key=lambda r:(r.timestamp_ms,r.event_id)))
    if time.monotonic()>=deadline:
        raise EvidenceUnavailable('build time limit exceeded',reason_code='EVIDENCE_TIME_LIMIT')
    return LocalEvidenceIndex(rows,tuple(r.timestamp_ms for r in rows),source_namespace,exposure,count,count-len(rows))
