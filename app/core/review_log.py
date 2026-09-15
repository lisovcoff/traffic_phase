from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from app.core.phase_discovery import APPROACHES, PhaseDiscoveryResult


def _evidence(frame: pd.DataFrame, current_time_s: float, window_s: float = 12.0) -> dict[str, dict[str, float]]:
    lower = current_time_s - window_s
    recent = frame[(frame["t_s"] >= lower) & (frame["t_s"] <= current_time_s)]
    result: dict[str, dict[str, float]] = {}
    for approach in APPROACHES:
        group = recent[recent["zone_in"] == approach]
        result[approach] = {
            "release": float(group["release_weight"].sum()),
            "stopped": float(group["stopped"].sum()),
            "flow": float(len(group)),
        }
    return result


def _support_status(phase_active: set[str], evidence: dict[str, dict[str, float]]) -> str:
    active_release = sum(evidence[a]["release"] for a in phase_active)
    inactive_release = sum(evidence[a]["release"] for a in APPROACHES if a not in phase_active)
    active_stopped = sum(evidence[a]["stopped"] for a in phase_active)
    inactive_stopped = sum(evidence[a]["stopped"] for a in APPROACHES if a not in phase_active)

    if active_release == 0 and inactive_release == 0 and active_stopped == 0 and inactive_stopped == 0:
        return "NO_RECENT_EVIDENCE"
    if active_release > inactive_release * 1.2 and inactive_stopped >= active_stopped:
        return "STRONG"
    if active_release > inactive_release and active_stopped <= inactive_stopped:
        return "SUPPORTING"
    if inactive_release > active_release * 1.5:
        return "CONTRADICTORY"
    return "MIXED"


def _phase_at(phase_model: PhaseDiscoveryResult, cycle_phase_s: float):
    for phase in phase_model.phases:
        start = phase.phase_start % phase_model.cycle_seconds
        end = phase.phase_end % phase_model.cycle_seconds
        if start <= end and start <= cycle_phase_s < end:
            return phase
        if start > end and (cycle_phase_s >= start or cycle_phase_s < end):
            return phase
    return None


def review_summary(
    frame: pd.DataFrame,
    phase_model: PhaseDiscoveryResult,
    timeline: Iterable[dict[str, object]],
    *,
    cycle_confidence: float,
) -> dict[str, object]:
    items = list(timeline)
    cycle = float(phase_model.cycle_seconds)
    bins = max(1, int(round(cycle / float(phase_model.bin_seconds))))
    covered = [False] * bins
    overlap_bins = 0

    for phase in phase_model.phases:
        start = int(round((phase.phase_start % cycle) / phase_model.bin_seconds)) % bins
        end = int(round((phase.phase_end % cycle) / phase_model.bin_seconds)) % bins
        if start == end:
            indices = set(range(bins))
        elif start < end:
            indices = set(range(start, end))
        else:
            indices = set(range(start, bins)) | set(range(0, end))
        for index in indices:
            if covered[index]:
                overlap_bins += 1
            covered[index] = True

    coverage_ratio = sum(covered) / bins
    overlap_ratio = overlap_bins / bins

    assigned = 0
    contradictory = 0
    strong_or_supporting = 0
    for item in items:
        phase = _phase_at(phase_model, float(item["cycle_phase_s"]))
        if phase is None:
            continue
        assigned += 1
        evidence = _evidence(frame, float(item["timestamp_s"]))
        status = _support_status(set(phase.active_approaches), evidence)
        if status == "CONTRADICTORY":
            contradictory += 1
        if status in {"STRONG", "SUPPORTING"}:
            strong_or_supporting += 1

    contradiction_ratio = contradictory / assigned if assigned else 1.0
    supporting_ratio = strong_or_supporting / assigned if assigned else 0.0
    non_overlapping = overlap_bins == 0
    structural_ok = bool(phase_model.phases) and non_overlapping

    checks = [
        {
            "name": "phase_structure",
            "status": "PASS" if structural_ok else "FAIL",
            "details": f"phases={len(phase_model.phases)} non_overlapping={non_overlapping}",
        },
        {
            "name": "cycle_confidence",
            "status": "PASS" if cycle_confidence >= 0.45 else "WARN",
            "details": f"confidence={cycle_confidence:.4f}",
        },
        {
            "name": "cycle_coverage",
            "status": "PASS" if coverage_ratio >= 0.65 else "WARN" if coverage_ratio >= 0.45 else "FAIL",
            "details": f"covered={coverage_ratio:.3f} overlap={overlap_ratio:.3f}",
        },
        {
            "name": "traffic_consistency",
            "status": "PASS" if contradiction_ratio <= 0.20 else "WARN" if contradiction_ratio <= 0.40 else "FAIL",
            "details": f"contradictory={contradiction_ratio:.3f} supporting={supporting_ratio:.3f}",
        },
    ]

    score = 25.0 * (1.0 if structural_ok else 0.0)
    score += 20.0 * min(1.0, coverage_ratio / 0.65)
    score += 35.0 * max(0.0, 1.0 - contradiction_ratio)
    score += 20.0 * min(1.0, max(0.0, cycle_confidence / 0.45))
    failed = any(check["status"] == "FAIL" for check in checks)
    warned = any(check["status"] == "WARN" for check in checks)
    overall = "FAIL" if failed else "WARN" if warned else "PASS"

    return {
        "status": overall,
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


def build_review_log(
    frame: pd.DataFrame,
    phase_model: PhaseDiscoveryResult,
    timeline: Iterable[dict[str, object]],
    *,
    source_path: Path,
    cycle_seconds: float,
    cycle_confidence: float,
    sample_every_s: float = 10.0,
) -> str:
    items = list(timeline)
    if not items:
        return "RECONSTRUCTION REVIEW LOG\nNo playback snapshots available."

    summary = review_summary(frame, phase_model, items, cycle_confidence=cycle_confidence)
    selected: list[dict[str, object]] = []
    next_sample = 0.0
    for item in items:
        timestamp_s = float(item["timestamp_s"])
        if timestamp_s + 1e-9 >= next_sample:
            selected.append(item)
            next_sample += sample_every_s
    if selected[-1] is not items[-1]:
        selected.append(items[-1])

    lines = [
        "RECONSTRUCTION REVIEW LOG",
        f"source={source_path.name}",
        "ground_truth=UNAVAILABLE",
        "purpose=internal_consistency_and_traffic_evidence_review",
        f"duration_s={float(frame['t_s'].max()):.3f}",
        f"cycle_s={cycle_seconds:.3f}",
        f"cycle_confidence={cycle_confidence:.4f}",
        f"overall={summary['status']} score={summary['score']:.1f}",
        f"phase_count={len(phase_model.phases)}",
        "",
        "AUTOMATIC REVIEW",
    ]
    for check in summary["checks"]:
        lines.append(f"{check['status']} {check['name']}: {check['details']}")
    lines.extend(["", "PHASE MODEL"])

    for phase in phase_model.phases:
        active = ",".join(phase.active_approaches) or "NONE"
        movements = ",".join(phase.active_movements) or "NONE"
        lines.append(
            f"phase={phase.phase_id} start={phase.phase_start:.2f}s end={phase.phase_end:.2f}s "
            f"active={active} movements={movements} confidence={phase.confidence:.4f}"
        )

    lines.extend(["", "PLAYBACK CHECKS", "Columns: t_s | millis | phase | active | states | evidence | support"])
    for item in selected:
        timestamp_s = float(item["timestamp_s"])
        cycle_phase_s = float(item["cycle_phase_s"])
        phase = _phase_at(phase_model, cycle_phase_s)
        phase_active = set(phase.active_approaches) if phase else set()
        evidence = _evidence(frame, timestamp_s)
        states = item["approaches"]
        state_text = ",".join(f"{a}:{states[a]['state']}" for a in APPROACHES)
        evidence_text = ",".join(
            f"{a}:r{evidence[a]['release']:.1f}/s{evidence[a]['stopped']:.0f}/f{evidence[a]['flow']:.0f}"
            for a in APPROACHES
        )
        support = _support_status(phase_active, evidence) if phase else "NO_PHASE"
        active_text = ",".join(sorted(phase_active)) or "NONE"
        lines.append(
            f"t={timestamp_s:7.3f}s | millis={int(item['timestamp_ms'])} | phase={item['phase_id']} | "
            f"active={active_text} | states={state_text} | evidence={evidence_text} | support={support}"
        )

    lines.extend([
        "",
        "REVIEW RULES",
        "GREEN/YELLOW should belong to phase.active_approaches; RED should belong to inactive approaches.",
        "STRONG/SUPPORTING means recent traffic is broadly compatible with the inferred phase; MIXED needs manual inspection; CONTRADICTORY is a red flag.",
        "These checks do not establish true signal-light correctness because no labeled controller state is available in the source data.",
    ])
    return "\n".join(lines)
