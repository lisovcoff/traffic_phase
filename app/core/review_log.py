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
        f"phase_count={len(phase_model.phases)}",
        "",
        "PHASE MODEL",
    ]

    for phase in phase_model.phases:
        active = ",".join(phase.active_approaches) or "NONE"
        movements = ",".join(phase.active_movements) or "NONE"
        lines.append(
            f"phase={phase.phase_id} start={phase.phase_start:.2f}s end={phase.phase_end:.2f}s "
            f"active={active} movements={movements} confidence={phase.confidence:.4f}"
        )

    lines.extend([
        "",
        "PLAYBACK CHECKS",
        "Columns: t_s | millis | phase | active | states | evidence | support",
    ])

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
            f"t={timestamp_s:7.3f}s | millis={int(item['timestamp_ms'])} | "
            f"phase={item['phase_id']} | active={active_text} | "
            f"states={state_text} | evidence={evidence_text} | support={support}"
        )

    lines.extend([
        "",
        "REVIEW RULES",
        "GREEN/YELLOW should belong to phase.active_approaches; RED should belong to inactive approaches.",
        "STRONG/SUPPORTING means recent traffic is broadly compatible with the inferred phase; MIXED needs manual inspection; CONTRADICTORY is a red flag.",
        "These checks do not establish true signal-light correctness because no labeled controller state is available in the source data.",
    ])
    return "\n".join(lines)
