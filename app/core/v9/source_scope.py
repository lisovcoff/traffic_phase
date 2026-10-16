"""Source/session boundaries before V9 fitting; not signal-regime detection."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import zipfile

from app.core.temporal_evidence import EvidenceUnavailable

MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_SOURCE_CHOICES = 512


class ScopeChoiceRequired(EvidenceUnavailable):
    def __init__(self, kind, choices, *, source_member=None):
        super().__init__('Choose one input source/session; unrelated observations are not pooled',
                         reason_code=f'{kind.upper()}_SELECTION_REQUIRED')
        self.kind, self.choices, self.source_member = kind, choices, source_member

    def to_dict(self):
        return {**super().to_dict(), 'choice_kind': self.kind, 'choices': self.choices,
                'source_member': self.source_member, 'fitting_performed': False}


def choose_source(path, requested=None, *, max_bytes=MAX_SOURCE_BYTES):
    """Inspect ZIP directory only. Each JSON is an unverified source namespace.

    Different names do not prove different cameras; equal names/zones do not
    prove the same intersection. No automatic union without a verified manifest.
    """
    path = Path(path)
    if path.is_file() and path.suffix.lower() == '.json':
        choices = [dict(source_member=path.name, uncompressed_bytes=path.stat().st_size)]
    elif path.is_file() and path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            infos = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith('.json')]
            choices = []
            names = set()
            for info in infos:
                member = Path(info.filename.replace('\\', '/'))
                if member.is_absolute() or '..' in member.parts or PureWindowsPath(info.filename).drive:
                    raise ValueError(f'unsafe ZIP member path: {info.filename}')
                key = info.filename.replace('\\', '/').casefold()
                if key in names:
                    raise ValueError('duplicate or colliding ZIP JSON member name')
                names.add(key)
                if info.flag_bits & 1:
                    raise ValueError('encrypted trajectory ZIP members are unsupported')
                choices.append(dict(source_member=info.filename, uncompressed_bytes=info.file_size,
                                    crc32=f'{info.CRC:08x}'))
    elif path.is_dir():
        choices = [dict(source_member=str(p), uncompressed_bytes=p.stat().st_size)
                   for p in sorted(path.rglob('*.json')) if not (
                       p.name.lower().endswith('_manual_marks.json') or
                       'phase_discovery' in p.name.lower() or 'benchmark' in p.name.lower())]
    else:
        raise ValueError(f'unsupported or missing V9 source: {path}')
    choices.sort(key=lambda r: r['source_member'])
    if not choices:
        raise EvidenceUnavailable('no JSON input sources', reason_code='NO_TRAJECTORY_SOURCES')
    if len(choices) > MAX_SOURCE_CHOICES:
        raise EvidenceUnavailable('input source choice budget exceeded', reason_code='SOURCE_COUNT_BUDGET')
    if requested is None and len(choices) > 1:
        raise ScopeChoiceRequired('source', choices)
    chosen = next((r for r in choices if r['source_member'] == requested), None) if requested is not None else choices[0]
    if chosen is None:
        raise ValueError('unknown source_member; select an exact listed JSON member')
    if chosen['uncompressed_bytes'] > max_bytes:
        raise EvidenceUnavailable(f'selected JSON exceeds input byte budget ({max_bytes} bytes)', reason_code='SOURCE_BYTE_BUDGET')
    return chosen['source_member'], choices


@dataclass(frozen=True)
class InputSession:
    metadata: dict
    fingerprints: frozenset


def input_sessions(bundle, source_member):
    # Reuse the existing project gap; it is not a fitted traffic-light threshold.
    from app.core.reconstruction import DEFAULT_SESSION_GAP_SECONDS
    gap_ms = DEFAULT_SESSION_GAP_SECONDS * 1000
    tracks = {}
    for event in bundle.temporal_events:
        p = event.provenance
        if p.get('source') != source_member:
            raise EvidenceUnavailable('event bundle contains a different source namespace',
                                      reason_code='MIXED_SOURCE_EVENT_BUNDLE')
        key = p['track_fingerprint']
        start, end = p['track_range_ms']
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                   for x in (start, end)) or end < start:
            raise EvidenceUnavailable('invalid track observation support', reason_code='INVALID_SESSION_SUPPORT')
        if (p.get('max_detection_gap_ms') or 0) > gap_ms:
            raise EvidenceUnavailable('a track spans an unobserved session-size gap; association needs review',
                                      reason_code='AMBIGUOUS_TRACK_SESSION_GAP')
        tracks[key] = start, end
    ordered = sorted((a, b, key) for key, (a, b) in tracks.items())
    groups = []
    for start, end, key in ordered:
        if not groups or start-groups[-1]['end'] > gap_ms:
            groups.append(dict(start=start, end=end, keys=set()))
        groups[-1]['end'] = max(groups[-1]['end'], end)
        groups[-1]['keys'].add(key)
    sessions = []
    if len(groups) > MAX_SOURCE_CHOICES:
        raise EvidenceUnavailable('session choice budget exceeded', reason_code='SESSION_COUNT_BUDGET')
    for index, group in enumerate(groups):
        identity = json.dumps([source_member, sorted(group['keys'])], separators=(',', ':')).encode()
        metadata = dict(session_id=hashlib.sha256(identity).hexdigest()[:24], session_number=index+1,
                        source_member=source_member, track_count=len(group['keys']),
                        observation_start_ms=group['start'], observation_end_ms=group['end'],
                        split_gap_seconds=DEFAULT_SESSION_GAP_SECONDS,
                        semantics='trajectory-support partition_NOT_camera_coverage_or_signal_regime')
        sessions.append(InputSession(metadata, frozenset(group['keys'])))
    return sessions


def choose_session(bundle, source_member, requested=None):
    sessions = input_sessions(bundle, source_member)
    choices = [s.metadata for s in sessions]
    if requested is None and len(sessions) > 1:
        raise ScopeChoiceRequired('session', choices, source_member=source_member)
    selected = next((s for s in sessions if s.metadata['session_id'] == requested), None) if requested else (
        sessions[0] if sessions else None)
    if selected is None:
        raise ValueError('unknown or unavailable session_id for selected source')
    if len(sessions) == 1:
        return bundle, selected.metadata, choices  # unchanged accepted single-session inputs
    from .events import _pack_temporal_events
    subset = [e for e in bundle.temporal_events if e.provenance['track_fingerprint'] in selected.fingerprints]
    scoped = _pack_temporal_events(subset, [source_member], len(selected.fingerprints),
                                   selected.metadata['observation_start_ms'], {})
    scoped.diagnostics['quality_counter_scope'] = 'selected usable tracks; global discarded-track counters not attributable'
    scoped.diagnostics['source_global_track_quality_counts'] = bundle.diagnostics.get('track_quality_counts', {})
    return scoped, selected.metadata, choices


def attach_input_scope(result, source_member, selected_session, sessions, *, source_count=1):
    result['input_scope'] = dict(status='SELECTED_SESSION_ONLY', source_member=source_member,
                                selected_session=selected_session, source_count=source_count,
                                source_session_count=len(sessions), other_sources_analysed=False,
                                other_sessions_analysed=False, complete_intersection_identity='UNKNOWN',
                                analysis_scope=('REPRESENTATIVE_WINDOW_ONLY' if
                                    (result.get('regime_detection') or {}).get('method') == 'hourly_local_period_consensus'
                                    else 'SELECTED_SESSION'),
                                semantics='input partition; not proof of signal regime or camera coverage')
    return result
