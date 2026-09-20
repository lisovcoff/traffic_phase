from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import statistics
import zipfile

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PROJECT_ROOT))

from app.core.event_cycle_estimator import estimate_event_cycle
from app.core.event_phase_discovery import EventPhase, EventPhaseDiscovery
from app.core.models import EventType, TrajectoryEvent
from app.core.preprocessing import load_trajectory_payload
from app.core.reconstruction import extract_events_from_trajectories


APPROACH_GROUP = {
    "N": "NS",
    "S": "NS",
    "E": "EW",
    "W": "EW",
}


@dataclass(frozen=True)
class CycleBoundaryRow:
    archive: str
    session_index: int
    cycle_index: int
    cycle_start_ms: int
    cycle_end_ms: int
    cycle_seconds: float
    event_count: int
    evidence_weight: float
    status: str
    confidence: float | None
    phase_a_group: str | None
    phase_a_start_s: float | None
    phase_a_end_s: float | None
    phase_a_duration_s: float | None
    phase_b_group: str | None
    phase_b_start_s: float | None
    phase_b_end_s: float | None
    phase_b_duration_s: float | None
    ns_to_ew_s: float | None
    ew_to_ns_s: float | None
    ns_to_ew_delta_s: float | None
    ew_to_ns_delta_s: float | None


@dataclass(frozen=True)
class SessionSummary:
    archive: str
    session_index: int
    session_start_ms: int
    session_end_ms: int
    session_duration_s: float
    production_cycle_s: float | None
    production_cycle_confidence: float | None
    template_phase_count: int
    template_phase_boundaries_s: tuple[dict[str, object], ...]
    complete_cycles: int
    insufficient_cycles: int
    median_ns_to_ew_s: float | None
    mad_ns_to_ew_s: float | None
    median_ew_to_ns_s: float | None
    mad_ew_to_ns_s: float | None
    median_ns_to_ew_delta_s: float | None
    mad_ns_to_ew_delta_s: float | None
    median_ew_to_ns_delta_s: float | None
    mad_ew_to_ns_delta_s: float | None
    median_ns_duration_s: float | None
    mad_ns_duration_s: float | None
    median_ew_duration_s: float | None
    mad_ew_duration_s: float | None
    median_cycle_confidence: float | None


def load_report(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_events_from_zip(path: Path) -> list[TrajectoryEvent]:
    """Reuse the production trajectory -> event extraction path."""
    events: list[TrajectoryEvent] = []
    with zipfile.ZipFile(path) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".json")
        ]
        if not members:
            raise ValueError(f"archive contains no JSON members: {path}")

        for member in members:
            with archive.open(member) as handle:
                payload = json.load(handle)
            trajectories = load_trajectory_payload(payload)
            for event in extract_events_from_trajectories(trajectories):
                if event.event_type in {EventType.RELEASE, EventType.CROSSING} and event.approach in APPROACH_GROUP:
                    events.append(event)
    events.sort(key=lambda event: (event.timestamp_ms, event.event_type.value, event.approach))
    return events


def session_events(
    events: list[TrajectoryEvent],
    start_ms: int,
    end_ms: int,
) -> list[TrajectoryEvent]:
    return [event for event in events if start_ms <= event.timestamp_ms <= end_ms]


def only_release(events: list[TrajectoryEvent]) -> list[TrajectoryEvent]:
    return [event for event in events if event.event_type == EventType.RELEASE]


def signed_group_weight(event: TrajectoryEvent) -> float:
    base = 1.0 if event.event_type == EventType.RELEASE else 0.5
    return base if APPROACH_GROUP[event.approach] == "NS" else -base


def robust_median(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 3) if values else None


def robust_mad(values: list[float]) -> float | None:
    if not values:
        return None
    center = statistics.median(values)
    return round(float(statistics.median(abs(value - center) for value in values)), 3)


def circular_delta(value: float, target: float, cycle_seconds: float) -> float:
    delta = (value - target) % cycle_seconds
    if delta > cycle_seconds / 2.0:
        delta -= cycle_seconds
    return delta


def phase_template_boundaries(phase_model) -> tuple[dict[str, object], ...]:
    """Convert the production two-phase model into labelled boundaries."""
    phases = list(phase_model.phases)
    if len(phases) != 2:
        return tuple()

    labels: list[dict[str, object]] = []
    for index, phase in enumerate(phases):
        previous = phases[index - 1]
        current_group = "NS" if set(phase.active_approaches) <= {"N", "S"} else "EW"
        previous_group = "NS" if set(previous.active_approaches) <= {"N", "S"} else "EW"
        transition = f"{previous_group}_TO_{current_group}"
        labels.append(
            {
                "transition": transition,
                "position_s": round(float(phase.phase_start) % phase_model.cycle_seconds, 3),
            }
        )
    # A two-phase model has two unique boundaries. Sort by transition name for stable output.
    return tuple(sorted(labels, key=lambda item: str(item["transition"])))


def phase_group_name(phase: EventPhase) -> str:
    return "NS" if set(phase.active_approaches) <= {"N", "S"} else "EW"


def fit_cycle_schedule(
    events: list[TrajectoryEvent],
    cycle_seconds: float,
    origin_ms: int,
    bin_seconds: float = 2.0,
    min_phase_seconds: float = 8.0,
) -> dict[str, object] | None:
    """Fit the best two-group schedule independently inside one observed cycle."""
    n_bins = int(round(cycle_seconds / bin_seconds))
    if n_bins < 2 * int(round(min_phase_seconds / bin_seconds)):
        return None

    ns = np.zeros(n_bins, dtype=float)
    ew = np.zeros(n_bins, dtype=float)
    total_events = 0

    for event in events:
        rel_s = (event.timestamp_ms - origin_ms) / 1000.0
        if rel_s < 0 or rel_s >= cycle_seconds:
            continue
        index = min(n_bins - 1, int(rel_s / bin_seconds))
        if APPROACH_GROUP[event.approach] == "NS":
            ns[index] += 1.0 if event.event_type == EventType.RELEASE else 0.5
        else:
            ew[index] += 1.0 if event.event_type == EventType.RELEASE else 0.5
        total_events += 1

    total_weight = float(ns.sum() + ew.sum())
    if total_events < 5 or total_weight <= 0:
        return {
            "status": "insufficient_data",
            "event_count": total_events,
            "evidence_weight": total_weight,
        }

    min_phase_bins = max(1, int(round(min_phase_seconds / bin_seconds)))
    pref_ns = np.r_[0.0, np.cumsum(np.r_[ns, ns])]
    pref_ew = np.r_[0.0, np.cumsum(np.r_[ew, ew])]
    best: tuple[float, str, int, int] | None = None

    for start in range(n_bins):
        for length in range(min_phase_bins, n_bins - min_phase_bins + 1):
            end = start + length
            ns_inside = pref_ns[end] - pref_ns[start]
            ns_outside = float(ns.sum()) - ns_inside
            ew_inside = pref_ew[end] - pref_ew[start]
            ew_outside = float(ew.sum()) - ew_inside

            score_ns = ns_inside + ew_outside
            score_ew = ew_inside + ns_outside

            if score_ns >= score_ew:
                candidate = (score_ns, "NS", start, length)
            else:
                candidate = (score_ew, "EW", start, length)

            if best is None or candidate[0] > best[0]:
                best = candidate

    if best is None:
        return None

    score, active_group, start, length = best
    end = (start + length) % n_bins
    support_ratio = score / total_weight if total_weight else 0.0

    if active_group == "NS":
        ns_duration = length * bin_seconds
        ew_duration = cycle_seconds - ns_duration
        ns_to_ew = end * bin_seconds
        ew_to_ns = start * bin_seconds
    else:
        ew_duration = length * bin_seconds
        ns_duration = cycle_seconds - ew_duration
        ew_to_ns = end * bin_seconds
        ns_to_ew = start * bin_seconds

    return {
        "status": "ok",
        "event_count": total_events,
        "evidence_weight": total_weight,
        "confidence": max(0.0, min(1.0, float(support_ratio))),
        "phase_a_group": active_group,
        "phase_a_start_s": round(start * bin_seconds, 3),
        "phase_a_end_s": round(end * bin_seconds, 3),
        "phase_a_duration_s": round(length * bin_seconds, 3),
        "phase_b_group": "EW" if active_group == "NS" else "NS",
        "phase_b_start_s": round(end * bin_seconds, 3),
        "phase_b_end_s": round(start * bin_seconds, 3),
        "phase_b_duration_s": round(cycle_seconds - length * bin_seconds, 3),
        "ns_to_ew_s": round(ns_to_ew, 3),
        "ew_to_ns_s": round(ew_to_ns, 3),
        "ns_duration_s": round(ns_duration, 3),
        "ew_duration_s": round(ew_duration, 3),
    }


def analyze_session(
    archive_name: str,
    session_index: int,
    session: dict[str, object],
    events: list[TrajectoryEvent],
    *,
    bin_seconds: float = 2.0,
) -> tuple[list[CycleBoundaryRow], SessionSummary]:
    start_ms = int(session["start_ms"])
    end_ms = int(session["end_ms"])
    selected = session_events(events, start_ms, end_ms)
    release = only_release(selected)
    if len(release) < 20:
        summary = SessionSummary(
            archive=archive_name,
            session_index=session_index,
            session_start_ms=start_ms,
            session_end_ms=end_ms,
            session_duration_s=float(session["duration_s"]),
            production_cycle_s=None,
            production_cycle_confidence=None,
            template_phase_count=0,
            template_phase_boundaries_s=tuple(),
            complete_cycles=0,
            insufficient_cycles=0,
            median_ns_to_ew_s=None,
            mad_ns_to_ew_s=None,
            median_ew_to_ns_s=None,
            mad_ew_to_ns_s=None,
            median_ns_to_ew_delta_s=None,
            mad_ns_to_ew_delta_s=None,
            median_ew_to_ns_delta_s=None,
            mad_ew_to_ns_delta_s=None,
            median_ns_duration_s=None,
            mad_ns_duration_s=None,
            median_ew_duration_s=None,
            mad_ew_duration_s=None,
            median_cycle_confidence=None,
        )
        return [], summary

    cycle_estimate = estimate_event_cycle(selected, sampling_seconds=bin_seconds)
    cycle_seconds = float(cycle_estimate.estimate.cycle_seconds)
    cycle_confidence = float(cycle_estimate.estimate.confidence)

    # The production phase model is used only as a session-level reference template.
    phase_model = EventPhaseDiscovery(bin_seconds=bin_seconds).discover(
        release,
        cycle_seconds=cycle_seconds,
    )
    template_boundaries = phase_template_boundaries(phase_model)
    if len(template_boundaries) != 2:
        raise ValueError(
            f"expected two template boundaries, got {len(template_boundaries)}"
        )

    # Do NOT rotate the cycle windows so that a template boundary is at 0s.
    # That would make one phase boundary part of the coordinate system by
    # construction and can create artificial zero-jitter results.
    #
    # Keep the production/session origin instead: this is the same raw
    # timestamp origin used to build the session phase model. The per-cycle
    # schedule is then fitted independently inside each fixed-length window
    # and both boundaries are measured from the same neutral origin.
    cycle_origin_ms = min(event.timestamp_ms for event in release)

    first_cycle_index = int(np.floor((start_ms - cycle_origin_ms) / (cycle_seconds * 1000.0)))
    last_cycle_index = int(np.ceil((end_ms - cycle_origin_ms) / (cycle_seconds * 1000.0)))

    rows: list[CycleBoundaryRow] = []
    complete_count = 0
    insufficient_count = 0
    ns_to_ew_values: list[float] = []
    ew_to_ns_values: list[float] = []
    ns_to_ew_delta: list[float] = []
    ew_to_ns_delta: list[float] = []
    ns_durations: list[float] = []
    ew_durations: list[float] = []
    confidences: list[float] = []

    template_positions = {
        item["transition"]: float(item["position_s"]) for item in template_boundaries
    }

    for cycle_index in range(first_cycle_index, last_cycle_index):
        cycle_start_ms = cycle_origin_ms + int(round(cycle_index * cycle_seconds * 1000.0))
        cycle_end_ms = cycle_start_ms + int(round(cycle_seconds * 1000.0))
        cycle_release = [
            event for event in release
            if cycle_start_ms <= event.timestamp_ms < cycle_end_ms
        ]
        schedule = fit_cycle_schedule(
            cycle_release,
            cycle_seconds,
            cycle_start_ms,
            bin_seconds=bin_seconds,
        )
        if schedule is None:
            continue

        if schedule["status"] != "ok":
            insufficient_count += 1
            rows.append(
                CycleBoundaryRow(
                    archive=archive_name,
                    session_index=session_index,
                    cycle_index=cycle_index,
                    cycle_start_ms=cycle_start_ms,
                    cycle_end_ms=cycle_end_ms,
                    cycle_seconds=cycle_seconds,
                    event_count=int(schedule["event_count"]),
                    evidence_weight=float(schedule["evidence_weight"]),
                    status="insufficient_data",
                    confidence=None,
                    phase_a_group=None,
                    phase_a_start_s=None,
                    phase_a_end_s=None,
                    phase_a_duration_s=None,
                    phase_b_group=None,
                    phase_b_start_s=None,
                    phase_b_end_s=None,
                    phase_b_duration_s=None,
                    ns_to_ew_s=None,
                    ew_to_ns_s=None,
                    ns_to_ew_delta_s=None,
                    ew_to_ns_delta_s=None,
                )
            )
            continue

        complete_count += 1
        ns_to_ew = float(schedule["ns_to_ew_s"])
        ew_to_ns = float(schedule["ew_to_ns_s"])
        d_ns_to_ew = circular_delta(ns_to_ew, template_positions["NS_TO_EW"], cycle_seconds)
        d_ew_to_ns = circular_delta(ew_to_ns, template_positions["EW_TO_NS"], cycle_seconds)

        ns_to_ew_values.append(ns_to_ew)
        ew_to_ns_values.append(ew_to_ns)
        ns_to_ew_delta.append(d_ns_to_ew)
        ew_to_ns_delta.append(d_ew_to_ns)
        ns_durations.append(float(schedule["ns_duration_s"]))
        ew_durations.append(float(schedule["ew_duration_s"]))
        confidences.append(float(schedule["confidence"]))

        rows.append(
            CycleBoundaryRow(
                archive=archive_name,
                session_index=session_index,
                cycle_index=cycle_index,
                cycle_start_ms=cycle_start_ms,
                cycle_end_ms=cycle_end_ms,
                cycle_seconds=cycle_seconds,
                event_count=int(schedule["event_count"]),
                evidence_weight=float(schedule["evidence_weight"]),
                status="ok",
                confidence=float(schedule["confidence"]),
                phase_a_group=str(schedule["phase_a_group"]),
                phase_a_start_s=float(schedule["phase_a_start_s"]),
                phase_a_end_s=float(schedule["phase_a_end_s"]),
                phase_a_duration_s=float(schedule["phase_a_duration_s"]),
                phase_b_group=str(schedule["phase_b_group"]),
                phase_b_start_s=float(schedule["phase_b_start_s"]),
                phase_b_end_s=float(schedule["phase_b_end_s"]),
                phase_b_duration_s=float(schedule["phase_b_duration_s"]),
                ns_to_ew_s=ns_to_ew,
                ew_to_ns_s=ew_to_ns,
                ns_to_ew_delta_s=d_ns_to_ew,
                ew_to_ns_delta_s=d_ew_to_ns,
            )
        )

    summary = SessionSummary(
        archive=archive_name,
        session_index=session_index,
        session_start_ms=start_ms,
        session_end_ms=end_ms,
        session_duration_s=float(session["duration_s"]),
        production_cycle_s=cycle_seconds,
        production_cycle_confidence=cycle_confidence,
        template_phase_count=len(phase_model.phases),
        template_phase_boundaries_s=template_boundaries,
        complete_cycles=complete_count,
        insufficient_cycles=insufficient_count,
        median_ns_to_ew_s=robust_median(ns_to_ew_values),
        mad_ns_to_ew_s=robust_mad(ns_to_ew_values),
        median_ew_to_ns_s=robust_median(ew_to_ns_values),
        mad_ew_to_ns_s=robust_mad(ew_to_ns_values),
        median_ns_to_ew_delta_s=robust_median(ns_to_ew_delta),
        mad_ns_to_ew_delta_s=robust_mad(ns_to_ew_delta),
        median_ew_to_ns_delta_s=robust_median(ew_to_ns_delta),
        mad_ew_to_ns_delta_s=robust_mad(ew_to_ns_delta),
        median_ns_duration_s=robust_median(ns_durations),
        mad_ns_duration_s=robust_mad(ns_durations),
        median_ew_duration_s=robust_median(ew_durations),
        mad_ew_duration_s=robust_mad(ew_durations),
        median_cycle_confidence=robust_median(confidences),
    )
    return rows, summary


def find_archive(data_dir: Path, archive_name: str) -> Path:
    direct = data_dir / archive_name
    if direct.exists():
        return direct
    candidates = [path for path in data_dir.glob("*.zip") if path.name == archive_name]
    if len(candidates) != 1:
        raise FileNotFoundError(f"could not resolve archive {archive_name!r}")
    return candidates[0]


def write_outputs(
    output_dir: Path,
    rows: list[CycleBoundaryRow],
    summaries: list[SessionSummary],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    cycle_path = output_dir / "phase_boundaries_per_cycle.csv"
    with cycle_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(CycleBoundaryRow.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    summary_path = output_dir / "phase_boundary_sessions.json"
    summary_path.write_text(
        json.dumps([asdict(summary) for summary in summaries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Phase Boundary Audit",
        "",
        "Boundary analysis uses the production trajectory/event extractor and RELEASE/CROSSING cycle estimation.",
        "Per-cycle boundaries are fitted from RELEASE evidence. They are internal consistency measurements, not controller ground truth.",
        "",
        "| Archive | Session | Production cycle, s | Cycle conf. | Complete cycles | Insufficient | NS→EW median±MAD, s | EW→NS median±MAD, s | NS duration median±MAD, s | EW duration median±MAD, s | Boundary jitter NS→EW median±MAD, s | Boundary jitter EW→NS median±MAD, s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        def fmt(a, b):
            return "—" if a is None else f"{a}±{b}"
        lines.append(
            f"| {summary.archive} | {summary.session_index} | {summary.production_cycle_s} | {summary.production_cycle_confidence} | "
            f"{summary.complete_cycles} | {summary.insufficient_cycles} | "
            f"{fmt(summary.median_ns_to_ew_s, summary.mad_ns_to_ew_s)} | "
            f"{fmt(summary.median_ew_to_ns_s, summary.mad_ew_to_ns_s)} | "
            f"{fmt(summary.median_ns_duration_s, summary.mad_ns_duration_s)} | "
            f"{fmt(summary.median_ew_duration_s, summary.mad_ew_duration_s)} | "
            f"{fmt(summary.median_ns_to_ew_delta_s, summary.mad_ns_to_ew_delta_s)} | "
            f"{fmt(summary.median_ew_to_ns_delta_s, summary.mad_ew_to_ns_delta_s)} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- `NS→EW` and `EW→NS` are the two inferred phase boundaries within each cycle.",
        "- `Boundary jitter` is the circular deviation of per-cycle boundary position from the session-level production phase template.",
        "- `MAD` is the median absolute deviation and is robust to occasional bad cycles.",
        "- The analysis intentionally operates per session rather than forcing one cycle across a multi-day archive.",
    ])
    (output_dir / "phase_boundary_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare inferred traffic-signal phase boundaries cycle-by-cycle across the supplied archives."
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--audit-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("phase_boundary_output"))
    parser.add_argument("--dataset", action="append", dest="dataset_names", default=None)
    parser.add_argument("--bin-seconds", type=float, default=2.0)
    args = parser.parse_args()

    if args.bin_seconds <= 0:
        raise SystemExit("--bin-seconds must be positive")

    report = load_report(args.audit_report)
    requested = set(args.dataset_names or [])
    available = {str(item["archive"]) for item in report["archives"]}
    unknown = requested - available
    if unknown:
        raise SystemExit("unknown dataset(s): " + ", ".join(sorted(unknown)))

    rows: list[CycleBoundaryRow] = []
    summaries: list[SessionSummary] = []

    archives = [
        item for item in report["archives"]
        if not requested or str(item["archive"]) in requested
    ]

    for index, archive in enumerate(archives, start=1):
        archive_name = str(archive["archive"])
        archive_path = find_archive(args.data_dir, archive_name)
        print(f"[{index}/{len(archives)}] extracting production events: {archive_name}", flush=True)
        all_events = load_events_from_zip(archive_path)
        print(f"    selected RELEASE/CROSSING events: {len(all_events)}", flush=True)

        sessions = archive["temporal_sessions"]["sessions"]
        for session_index, session in enumerate(sessions, start=1):
            print(
                f"    session {session_index}/{len(sessions)}: duration={session['duration_s']}s",
                flush=True,
            )
            session_rows, summary = analyze_session(
                archive_name,
                session_index,
                session,
                all_events,
                bin_seconds=args.bin_seconds,
            )
            rows.extend(session_rows)
            summaries.append(summary)
            print(
                f"      cycles={summary.complete_cycles} complete, "
                f"{summary.insufficient_cycles} insufficient, "
                f"cycle={summary.production_cycle_s}",
                flush=True,
            )

    write_outputs(args.output_dir, rows, summaries)
    print(f"DONE: {len(rows)} cycle rows across {len(summaries)} sessions", flush=True)
    print(f"CSV: {args.output_dir / 'phase_boundaries_per_cycle.csv'}", flush=True)
    print(f"MD : {args.output_dir / 'phase_boundary_report.md'}", flush=True)


if __name__ == "__main__":
    main()
