from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.core.event_phase_discovery import EventPhase, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent

APPROACHES = ("N", "S", "E", "W")


def _event_evidence(events: Iterable[TrajectoryEvent], current_time_s: float, origin_ms: int, window_s: float = 6.0) -> dict[str, dict[str, float]]:
    lower_ms = origin_ms + int((current_time_s - window_s) * 1000.0)
    upper_ms = origin_ms + int(current_time_s * 1000.0)
    result = {approach: {"moving": 0.0, "stopped": 0.0, "flow": 0.0} for approach in APPROACHES}
    for event in events:
        if not (lower_ms <= event.timestamp_ms <= upper_ms):
            continue
        if event.event_type not in {EventType.RELEASE, EventType.CROSSING}:
            continue
        result[event.approach]["moving"] += 1.0 if event.event_type == EventType.RELEASE else 0.5
        result[event.approach]["flow"] += 1.0
    return result


def _support_status(phase_active: set[str], evidence: dict[str, dict[str, float]]) -> str:
    active_moving = sum(evidence[a]["moving"] for a in phase_active)
    inactive_moving = sum(evidence[a]["moving"] for a in APPROACHES if a not in phase_active)
    moving_total = active_moving + inactive_moving
    if moving_total == 0: return "NO_RECENT_EVIDENCE"
    active_share = active_moving / moving_total
    if active_share >= 0.65: return "STRONG"
    if active_share >= 0.50: return "SUPPORTING"
    if active_share <= 0.35: return "CONTRADICTORY"
    return "MIXED"


def _phase_at(phase_model: EventPhaseDiscoveryResult, cycle_phase_s: float) -> EventPhase | None:
    for phase in phase_model.phases:
        start = phase.phase_start % phase_model.cycle_seconds
        end = phase.phase_end % phase_model.cycle_seconds
        if start <= end and start <= cycle_phase_s < end: return phase
        if start > end and (cycle_phase_s >= start or cycle_phase_s < end): return phase
    return None


def review_summary(events: Iterable[TrajectoryEvent], phase_model: EventPhaseDiscoveryResult, timeline: Iterable[dict[str, object]], *, cycle_confidence: float) -> dict[str, object]:
    items = list(timeline)
    event_list = list(events)
    cycle = float(phase_model.cycle_seconds)
    bins = max(1, int(round(cycle / float(phase_model.bin_seconds))))
    covered = [False] * bins
    overlap_bins = 0
    for phase in phase_model.phases:
        start = int(round((phase.phase_start % cycle) / phase_model.bin_seconds)) % bins
        end = int(round((phase.phase_end % cycle) / phase_model.bin_seconds)) % bins
        if start == end: indices = set(range(bins))
        elif start < end: indices = set(range(start, end))
        else: indices = set(range(start, bins)) | set(range(0, end))
        for index in indices:
            if covered[index]: overlap_bins += 1
            covered[index] = True
    coverage_ratio = sum(covered) / bins
    overlap_ratio = overlap_bins / bins
    assigned = contradictory = strong_or_supporting = 0
    for item in items:
        phase = _phase_at(phase_model, float(item["cycle_phase_s"]))
        if phase is None: continue
        assigned += 1
        status = _support_status(
            set(phase.active_approaches),
            _event_evidence(event_list, float(item["timestamp_s"]), phase_model.origin_timestamp_ms),
        )
        contradictory += status == "CONTRADICTORY"
        strong_or_supporting += status in {"STRONG", "SUPPORTING"}
    contradiction_ratio = contradictory / assigned if assigned else 1.0
    supporting_ratio = strong_or_supporting / assigned if assigned else 0.0
    structural_ok = bool(phase_model.phases) and overlap_bins == 0
    checks = [
        {"name": "phase_structure", "status": "PASS" if structural_ok else "FAIL", "details": f"phases={len(phase_model.phases)} non_overlapping={overlap_bins == 0}"},
        {"name": "cycle_confidence", "status": "PASS" if cycle_confidence >= 0.45 else "WARN", "details": f"confidence={cycle_confidence:.4f}"},
        {"name": "cycle_coverage", "status": "PASS" if coverage_ratio >= 0.65 else "WARN" if coverage_ratio >= 0.45 else "FAIL", "details": f"covered={coverage_ratio:.3f} overlap={overlap_ratio:.3f}"},
        {"name": "traffic_consistency", "status": "PASS" if contradiction_ratio <= 0.20 else "WARN" if contradiction_ratio <= 0.40 else "FAIL", "details": f"contradictory={contradiction_ratio:.3f} supporting={supporting_ratio:.3f}"},
    ]
    score = 25.0 * (1.0 if structural_ok else 0.0)
    score += 20.0 * min(1.0, coverage_ratio / 0.65)
    score += 35.0 * max(0.0, 1.0 - contradiction_ratio)
    score += 20.0 * min(1.0, max(0.0, cycle_confidence / 0.45))
    failed = any(check["status"] == "FAIL" for check in checks)
    warned = any(check["status"] == "WARN" for check in checks)
    return {
        "status": "FAIL" if failed else "WARN" if warned else "PASS",
        "score": round(score, 1),
        "checks": checks,
        "metrics": {
            "phase_count": len(phase_model.phases),
            "cycle_confidence": round(float(cycle_confidence), 4),
            "cycle_coverage_ratio": round(coverage_ratio, 4),
            "phase_overlap_ratio": round(overlap_ratio, 4),
            "assigned_snapshot_count": assigned,
            "contradictory_ratio": round(contradiction_ratio, 4),
            "supporting_ratio": round(supporting_ratio, 4),
        },
    }


def build_review_log(events: Iterable[TrajectoryEvent], phase_model: EventPhaseDiscoveryResult, timeline: Iterable[dict[str, object]], *, source_path: Path, cycle_seconds: float, cycle_confidence: float, sample_every_s: float = 10.0) -> str:
    items = list(timeline)
    event_list = list(events)
    if not items: return "RECONSTRUCTION REVIEW LOG\nNo playback snapshots available."
    summary = review_summary(event_list, phase_model, items, cycle_confidence=cycle_confidence)
    selected = []
    next_sample = 0.0
    for item in items:
        timestamp_s = float(item["timestamp_s"])
        if timestamp_s + 1e-9 >= next_sample:
            selected.append(item)
            next_sample += sample_every_s
    if selected[-1] is not items[-1]: selected.append(items[-1])
    lines = [
        "RECONSTRUCTION REVIEW LOG",
        f"source={source_path.name}",
        "ground_truth=UNAVAILABLE",
        "model=event_based_inference",
        "purpose=internal_consistency_and_traffic_evidence_review",
        f"event_count={len(event_list)}",
        f"cycle_s={cycle_seconds:.3f}",
        f"cycle_confidence={cycle_confidence:.4f}",
        f"overall={summary['status']} score={summary['score']:.1f}",
        f"phase_count={len(phase_model.phases)}",
        "",
        "AUTOMATIC REVIEW",
    ]
    for check in summary["checks"]: lines.append(f"{check['status']} {check['name']}: {check['details']}")
    lines.extend(["", "PHASE MODEL"])
    for phase in phase_model.phases:
        active = ",".join(phase.active_approaches) or "NONE"
        lines.append(f"phase={phase.phase_id} start={phase.phase_start:.2f}s end={phase.phase_end:.2f}s active={active} confidence={phase.confidence:.4f}")
    lines.extend(["", "PLAYBACK CHECKS", "Columns: t_s | millis | phase | active | states | release/crossing evidence | support"])
    for item in selected:
        phase = _phase_at(phase_model, float(item["cycle_phase_s"]))
        phase_active = set(phase.active_approaches) if phase else set()
        evidence = _event_evidence(event_list, float(item["timestamp_s"]), phase_model.origin_timestamp_ms)
        states = item["approaches"]
        state_text = ",".join(f"{a}:{states[a]['state']}" for a in APPROACHES)
        evidence_text = ",".join(f"{a}:r{evidence[a]['moving']:.1f}/f{evidence[a]['flow']:.0f}" for a in APPROACHES)
        support = _support_status(phase_active, evidence) if phase else "NO_PHASE"
        active_text = ",".join(sorted(phase_active)) or "NONE"
        lines.append(f"t={float(item['timestamp_s']):7.3f}s | millis={int(item['timestamp_ms'])} | phase={item['phase_id']} | active={active_text} | states={state_text} | evidence={evidence_text} | support={support}")
    lines.extend([
        "",
        "REVIEW RULES",
        "RELEASE/CROSSING events are positive traffic evidence for the active phase; STOP and APPROACH are not direct RED evidence.",
        "No recent release/crossing evidence is reported as NO_RECENT_EVIDENCE, not as proof of RED.",
        "Signal colors are inferred model states. They are not measurements of a physical traffic controller.",
        "These checks do not establish signal-light classification accuracy because the source archives do not contain labeled controller states.",
    ])
    return "\n".join(lines)