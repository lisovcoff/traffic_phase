from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.cycle_estimator import CycleEstimator
from app.core.models import EventType
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import build_trajectory_geometry
from app.core.models import Trajectory
from app.core.trajectory_geometry import build_trajectory_model


APPROACHES = ("N", "S", "E", "W")
EVENT_TYPES = tuple(item.value for item in EventType)
FLOW_EVENT_TYPES = {EventType.RELEASE, EventType.CROSSING}


@dataclass
class RunningNumeric:
    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value: float) -> None:
        value = float(value)
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def mean(self) -> float | None:
        return self.total / self.count if self.count else None


@dataclass
class ArchiveAudit:
    archive: str
    archive_size_bytes: int
    json_members: int = 0
    json_errors: int = 0

    trajectory_records: int = 0
    car_trajectories: int = 0
    non_car_trajectories: int = 0
    unusable_trajectories: int = 0
    missing_zone_in: int = 0
    missing_zone_out: int = 0
    missing_trajectory_millis: int = 0

    detection_total: int = 0
    detection_valid: int = 0
    detection_invalid: int = 0
    trajectories_with_no_valid_detections: int = 0
    raw_nonmonotonic_detection_edges: int = 0
    detection_gap_over_2s: int = 0
    detection_gap_total_edges: int = 0
    detection_gap_max_s: float = 0.0

    timestamp_ms_min: int | None = None
    timestamp_ms_max: int | None = None
    trajectory_millis_min: int | None = None
    trajectory_millis_max: int | None = None

    zone_in: Counter[str] = None  # type: ignore[assignment]
    zone_out: Counter[str] = None  # type: ignore[assignment]
    normalized_zone_in: Counter[str] = None  # type: ignore[assignment]
    normalized_zone_out: Counter[str] = None  # type: ignore[assignment]
    movements: Counter[str] = None  # type: ignore[assignment]
    categories: Counter[str] = None  # type: ignore[assignment]

    event_counts: Counter[str] = None  # type: ignore[assignment]
    event_by_approach: dict[str, Counter[str]] = None  # type: ignore[assignment]

    selected_event_count: int = 0
    selected_event_min_ms: int | None = None
    selected_event_max_ms: int | None = None

    flow_sampling_seconds: float = 2.0
    flow: dict[str, list[float]] = None  # type: ignore[assignment]
    flow_start_ms: int | None = None
    flow_end_ms: int | None = None

    def __post_init__(self) -> None:
        if self.zone_in is None:
            self.zone_in = Counter()
        if self.zone_out is None:
            self.zone_out = Counter()
        if self.normalized_zone_in is None:
            self.normalized_zone_in = Counter()
        if self.normalized_zone_out is None:
            self.normalized_zone_out = Counter()
        if self.movements is None:
            self.movements = Counter()
        if self.categories is None:
            self.categories = Counter()
        if self.event_counts is None:
            self.event_counts = Counter()
        if self.event_by_approach is None:
            self.event_by_approach = {a: Counter() for a in APPROACHES}
        if self.flow is None:
            self.flow = {
                "N": [],
                "S": [],
                "E": [],
                "W": [],
                "NS_signed": [],
                "event_count": [],
            }

    def add_timestamp(self, value: int, *, trajectory: bool = False) -> None:
        if trajectory:
            self.trajectory_millis_min = (
                value
                if self.trajectory_millis_min is None
                else min(self.trajectory_millis_min, value)
            )
            self.trajectory_millis_max = (
                value
                if self.trajectory_millis_max is None
                else max(self.trajectory_millis_max, value)
            )
        else:
            self.timestamp_ms_min = (
                value
                if self.timestamp_ms_min is None
                else min(self.timestamp_ms_min, value)
            )
            self.timestamp_ms_max = (
                value
                if self.timestamp_ms_max is None
                else max(self.timestamp_ms_max, value)
            )

    def add_event_time(self, value: int) -> None:
        self.selected_event_count += 1
        self.selected_event_min_ms = (
            value
            if self.selected_event_min_ms is None
            else min(self.selected_event_min_ms, value)
        )
        self.selected_event_max_ms = (
            value
            if self.selected_event_max_ms is None
            else max(self.selected_event_max_ms, value)
        )

    def ensure_flow_size(self, index: int) -> None:
        while len(self.flow["N"]) <= index:
            for key in self.flow:
                self.flow[key].append(0.0)

    def add_flow_event(
        self,
        approach: str,
        event_type: EventType,
        timestamp_ms: int,
    ) -> None:
        bin_ms = int(round(self.flow_sampling_seconds * 1000.0))

        if bin_ms <= 0:
            raise ValueError("flow_sampling_seconds must be positive")

        # Первый event задает начальную точку временной шкалы.
        if self.flow_start_ms is None:
            self.flow_start_ms = timestamp_ms
            self.flow_end_ms = timestamp_ms

        # ZIP members / JSON files не обязаны идти строго по времени.
        # Если обнаружили более раннее событие — сдвигаем начало шкалы.
        elif timestamp_ms < self.flow_start_ms:
            shift_ms = self.flow_start_ms - timestamp_ms
            prepend_bins = int(np.ceil(shift_ms / bin_ms))

            if prepend_bins > 0:
                for key in self.flow:
                    self.flow[key] = [0.0] * prepend_bins + self.flow[key]

                self.flow_start_ms -= prepend_bins * bin_ms

            self.flow_end_ms = max(
                self.flow_end_ms or timestamp_ms,
                timestamp_ms,
            )

        else:
            self.flow_end_ms = max(
                self.flow_end_ms or timestamp_ms,
                timestamp_ms,
            )

        index = int(
            (timestamp_ms - self.flow_start_ms) / bin_ms
        )

        # Безопасно расширяем временной ряд вправо.
        while len(self.flow["NS_signed"]) <= index:
            for key in self.flow:
                self.flow[key].append(0.0)

        weight = (
            1.0
            if event_type == EventType.RELEASE
            else 0.5
        )

        self.flow[approach][index] += weight
        self.flow["event_count"][index] += 1.0

        if approach in {"N", "S"}:
            self.flow["NS_signed"][index] += weight
        else:
            self.flow["NS_signed"][index] -= weight
  
    def to_dict(self) -> dict[str, Any]:
        return {
            "archive": self.archive,
            "archive_size_bytes": self.archive_size_bytes,
            "json_members": self.json_members,
            "json_errors": self.json_errors,
            "trajectories": {
                "records": self.trajectory_records,
                "cars": self.car_trajectories,
                "non_cars": self.non_car_trajectories,
                "unusable": self.unusable_trajectories,
                "missing_zone_in": self.missing_zone_in,
                "missing_zone_out": self.missing_zone_out,
                "missing_millis": self.missing_trajectory_millis,
            },
            "detections": {
                "total": self.detection_total,
                "valid": self.detection_valid,
                "invalid": self.detection_invalid,
                "invalid_ratio": (
                    self.detection_invalid / self.detection_total
                    if self.detection_total
                    else None
                ),
                "trajectories_without_valid_detections": self.trajectories_with_no_valid_detections,
                "raw_nonmonotonic_edges": self.raw_nonmonotonic_detection_edges,
                "gap_edges": self.detection_gap_total_edges,
                "gap_over_2s": self.detection_gap_over_2s,
                "gap_over_2s_ratio": (
                    self.detection_gap_over_2s / self.detection_gap_total_edges
                    if self.detection_gap_total_edges
                    else None
                ),
                "max_gap_s": self.detection_gap_max_s,
            },
            "time": {
                "trajectory_millis_min": self.trajectory_millis_min,
                "trajectory_millis_max": self.trajectory_millis_max,
                "detection_millis_min": self.timestamp_ms_min,
                "detection_millis_max": self.timestamp_ms_max,
                "selected_event_millis_min": self.selected_event_min_ms,
                "selected_event_millis_max": self.selected_event_max_ms,
                "detection_span_s": (
                    (self.timestamp_ms_max - self.timestamp_ms_min) / 1000.0
                    if self.timestamp_ms_min is not None and self.timestamp_ms_max is not None
                    else None
                ),
                "selected_event_span_s": (
                    (self.selected_event_max_ms - self.selected_event_min_ms) / 1000.0
                    if self.selected_event_min_ms is not None and self.selected_event_max_ms is not None
                    else None
                ),
            },
            "zones": {
                "zone_in_top20": self.zone_in.most_common(20),
                "zone_out_top20": self.zone_out.most_common(20),
                "normalized_zone_in": dict(self.normalized_zone_in),
                "normalized_zone_out": dict(self.normalized_zone_out),
                "unknown_approach": sum(
                    count
                    for name, count in self.normalized_zone_in.items()
                    if name not in APPROACHES
                ),
            },
            "movements_top50": self.movements.most_common(50),
            "categories": dict(self.categories),
            "events": {
                "counts": dict(self.event_counts),
                "by_approach": {
                    approach: dict(counter)
                    for approach, counter in self.event_by_approach.items()
                },
                "selected_release_crossing": self.selected_event_count,
            },
        }


def normalized_zone(value: Any) -> str:
    if value is None:
        return ""
    return str(value).lstrip("_").upper()


def update_min_max(current_min: int | None, current_max: int | None, value: int) -> tuple[int, int]:
    if current_min is None:
        return value, value
    return min(current_min, value), max(current_max or value, value)


def detect_gap_stats(audit: ArchiveAudit, detections_raw: list[Any]) -> None:
    previous_ms: int | None = None
    for item in detections_raw:
        if not isinstance(item, dict):
            continue
        millis = item.get("millis")
        if not isinstance(millis, (int, float)) or isinstance(millis, bool):
            continue
        if not math.isfinite(float(millis)):
            continue
        millis = int(float(millis))
        if previous_ms is not None:
            if millis <= previous_ms:
                audit.raw_nonmonotonic_detection_edges += 1
            elif millis > previous_ms:
                gap_s = (millis - previous_ms) / 1000.0
                audit.detection_gap_total_edges += 1
                audit.detection_gap_over_2s += int(gap_s > 2.0)
                audit.detection_gap_max_s = max(audit.detection_gap_max_s, gap_s)
        previous_ms = millis


def process_json_payload(audit: ArchiveAudit, payload: Any) -> None:
    if not isinstance(payload, list):
        audit.json_errors += 1
        return

    audit.trajectory_records += len(payload)

    for item in payload:
        if not isinstance(item, dict):
            audit.unusable_trajectories += 1
            continue

        category = str(item.get("category_name", "<missing>"))
        audit.categories[category] += 1
        if category != "car":
            audit.non_car_trajectories += 1
            continue

        audit.car_trajectories += 1
        zone_in_raw = item.get("zone_in")
        zone_out_raw = item.get("zone_out")
        millis_raw = item.get("millis")

        if not zone_in_raw:
            audit.missing_zone_in += 1
        if not zone_out_raw:
            audit.missing_zone_out += 1
        if millis_raw is None:
            audit.missing_trajectory_millis += 1

        if not zone_in_raw or not zone_out_raw or millis_raw is None:
            audit.unusable_trajectories += 1
            continue

        try:
            trajectory_millis = int(millis_raw)
        except (TypeError, ValueError):
            audit.unusable_trajectories += 1
            continue

        audit.add_timestamp(trajectory_millis, trajectory=True)
        zone_in = str(zone_in_raw)
        zone_out = str(zone_out_raw)
        norm_in = normalized_zone(zone_in)
        norm_out = normalized_zone(zone_out)
        audit.zone_in[zone_in] += 1
        audit.zone_out[zone_out] += 1
        audit.normalized_zone_in[norm_in] += 1
        audit.normalized_zone_out[norm_out] += 1
        audit.movements[f"{zone_in}->{zone_out}"] += 1

        detections_raw = item.get("detections") or []
        if not isinstance(detections_raw, list):
            detections_raw = []
        audit.detection_total += len(detections_raw)
        detect_gap_stats(audit, detections_raw)

        geometry = build_trajectory_geometry(item)
        audit.detection_valid += len(geometry.detections)
        audit.detection_invalid += geometry.invalid_detection_count
        if not geometry.detections:
            audit.trajectories_with_no_valid_detections += 1
            continue

        for detection in geometry.detections:
            audit.add_timestamp(detection.millis)

        trajectory = build_trajectory_model(item)
        events = extract_trajectory_events(
            trajectory,
            geometry,
        )
        for event in events:
            audit.event_counts[event.event_type.value] += 1
            if event.approach in audit.event_by_approach:
                audit.event_by_approach[event.approach][event.event_type.value] += 1
            if event.event_type in FLOW_EVENT_TYPES and event.approach in APPROACHES:
                audit.add_event_time(event.timestamp_ms)
                audit.add_flow_event(event.approach, event.event_type, event.timestamp_ms)


def make_signal(audit: ArchiveAudit) -> np.ndarray:
    if not audit.flow["NS_signed"]:
        return np.array([], dtype=float)
    return np.asarray(audit.flow["NS_signed"], dtype=float)


def cycle_estimate(signal: np.ndarray, sampling_seconds: float) -> dict[str, Any]:
    if signal.size < 8:
        return {"status": "not_enough_samples", "samples": int(signal.size)}
    try:
        estimate = CycleEstimator().estimate(signal, sampling_seconds=sampling_seconds)
        return {"status": "ok", **estimate.to_dict()}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "samples": int(signal.size)}


def contiguous_event_segments(audit: ArchiveAudit, max_gap_minutes: float = 30.0) -> list[tuple[int, int, int]]:
    """Return selected-event sessions as (start_ms, end_ms, event_count)."""
    # Reconstruct timestamps from the compact flow arrays. This is enough for
    # session detection because the arrays are already indexed by 2-second bins.
    if audit.flow_start_ms is None or not audit.flow["NS_signed"]:
        return []

    nonzero = np.flatnonzero(np.asarray(audit.flow["N"]) + np.asarray(audit.flow["S"]) + np.asarray(audit.flow["E"]) + np.asarray(audit.flow["W"]) > 0)
    if nonzero.size == 0:
        return []

    max_gap_bins = max(1, int(max_gap_minutes * 60.0 / audit.flow_sampling_seconds))
    segments: list[tuple[int, int, int]] = []
    start_idx = int(nonzero[0])
    previous_idx = start_idx
    event_count = 0
    for idx in nonzero:
        idx = int(idx)
        bin_count = int(audit.flow["event_count"][idx])
        if idx - previous_idx > max_gap_bins:
            start_ms = audit.flow_start_ms + int(start_idx * audit.flow_sampling_seconds * 1000)
            end_ms = audit.flow_start_ms + int(previous_idx * audit.flow_sampling_seconds * 1000)
            segments.append((start_ms, end_ms, event_count))
            start_idx = idx
            event_count = 0
        event_count += bin_count
        previous_idx = idx
    start_ms = audit.flow_start_ms + int(start_idx * audit.flow_sampling_seconds * 1000)
    end_ms = audit.flow_start_ms + int(previous_idx * audit.flow_sampling_seconds * 1000)
    segments.append((start_ms, end_ms, event_count))
    return segments


def window_cycle_estimates(signal: np.ndarray, sampling_seconds: float, window_minutes: float) -> list[float]:
    samples_per_window = max(8, int(window_minutes * 60.0 / sampling_seconds))
    values: list[float] = []
    if signal.size < samples_per_window:
        return values
    step = samples_per_window
    for start in range(0, signal.size - samples_per_window + 1, step):
        chunk = signal[start : start + samples_per_window]
        try:
            estimate = CycleEstimator().estimate(chunk, sampling_seconds=sampling_seconds)
        except Exception:
            continue
        values.append(float(estimate.cycle_seconds))
    return values


def add_time_metrics(audit: ArchiveAudit) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if audit.selected_event_min_ms is None or audit.selected_event_max_ms is None:
        result["sessions"] = []
        return result

    sessions = contiguous_event_segments(audit)
    result["sessions"] = [
        {
            "start_ms": start,
            "end_ms": end,
            "duration_s": round((end - start) / 1000.0, 2),
            "selected_event_count": count,
        }
        for start, end, count in sessions
    ]
    result["session_count"] = len(sessions)
    result["largest_inter_session_gap_s"] = 0.0
    if len(sessions) >= 2:
        gaps = [
            max(0.0, (sessions[i + 1][0] - sessions[i][1]) / 1000.0)
            for i in range(len(sessions) - 1)
        ]
        result["largest_inter_session_gap_s"] = max(gaps)
        result["median_inter_session_gap_s"] = statistics.median(gaps)
    return result


def write_flow_csv(audit: ArchiveAudit, output_dir: Path, output_bin_seconds: float = 10.0) -> Path | None:
    if audit.flow_start_ms is None or not audit.flow["NS_signed"]:
        return None

    source = np.asarray(audit.flow["NS_signed"], dtype=float)
    n_source = len(source)
    factor = max(1, int(round(output_bin_seconds / audit.flow_sampling_seconds)))
    rows = []
    for start_idx in range(0, n_source, factor):
        end_idx = min(n_source, start_idx + factor)
        timestamp_ms = audit.flow_start_ms + int(start_idx * audit.flow_sampling_seconds * 1000)
        rows.append(
            {
                "timestamp_ms": timestamp_ms,
                "relative_s": round((timestamp_ms - audit.flow_start_ms) / 1000.0, 3),
                "N_weight": round(sum(audit.flow["N"][start_idx:end_idx]), 4),
                "S_weight": round(sum(audit.flow["S"][start_idx:end_idx]), 4),
                "E_weight": round(sum(audit.flow["E"][start_idx:end_idx]), 4),
                "W_weight": round(sum(audit.flow["W"][start_idx:end_idx]), 4),
                "NS_signed": round(float(np.sum(source[start_idx:end_idx])), 4),
                "event_count": int(sum(audit.flow["event_count"][start_idx:end_idx])),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = audit.archive.replace(" ", "_").replace("/", "_").replace("\\", "_")
    path = output_dir / f"flow_{safe_name}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def finalize_archive(audit: ArchiveAudit) -> dict[str, Any]:
    signal = make_signal(audit)
    report = audit.to_dict()
    report["flow"] = {
        "sampling_seconds": audit.flow_sampling_seconds,
        "samples": int(signal.size),
        "start_ms": audit.flow_start_ms,
        "end_ms": audit.flow_end_ms,
        "cycle_estimate": cycle_estimate(signal, audit.flow_sampling_seconds),
        "window_cycle_estimates_60m": window_cycle_estimates(
            signal,
            audit.flow_sampling_seconds,
            window_minutes=60.0,
        ),
    }
    report["temporal_sessions"] = add_time_metrics(audit)

    window_cycles = report["flow"]["window_cycle_estimates_60m"]
    if window_cycles:
        median = statistics.median(window_cycles)
        mad = statistics.median(abs(v - median) for v in window_cycles)
        report["flow"]["window_cycle_summary"] = {
            "count": len(window_cycles),
            "median_s": round(float(median), 3),
            "mad_s": round(float(mad), 3),
            "min_s": min(window_cycles),
            "max_s": max(window_cycles),
        }
    else:
        report["flow"]["window_cycle_summary"] = None

    return report


def audit_archive(path: Path, *, flow_sampling_seconds: float = 2.0) -> tuple[ArchiveAudit, float]:
    audit = ArchiveAudit(
        archive=path.name,
        archive_size_bytes=path.stat().st_size,
        flow_sampling_seconds=flow_sampling_seconds,
    )
    started = time.perf_counter()
    with zipfile.ZipFile(path) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".json")
        ]
        audit.json_members = len(members)
        for index, member in enumerate(members, start=1):
            if index == 1 or index % 25 == 0 or index == len(members):
                print(
                    f"    json {index}/{len(members)}: {member.filename}",
                    flush=True,
                )
            try:
                with archive.open(member) as handle:
                    payload = json.load(handle)
                process_json_payload(audit, payload)
            except Exception as exc:
                audit.json_errors += 1
                print(f"    ERROR {member.filename}: {type(exc).__name__}: {exc}", flush=True)
                import traceback
                traceback.print_exc()
    return audit, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the supplied traffic trajectory ZIP archives without extracting them. "
            "The script produces compact data-quality, event-flow and cycle-stability reports."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="directory containing the ZIP archives (default: data)",
    )
    parser.add_argument(
        "--archive",
        action="append",
        dest="archives",
        help="explicit archive path; repeat to select several files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("audit_output"),
    )
    parser.add_argument(
        "--flow-output-bin-seconds",
        type=float,
        default=10.0,
        help="bin size for saved flow CSVs; cycle estimation still uses 2-second bins",
    )
    args = parser.parse_args()

    if args.flow_output_bin_seconds <= 0:
        raise SystemExit("--flow-output-bin-seconds must be positive")

    if args.archives:
        archive_paths = [Path(item) for item in args.archives]
    else:
        archive_paths = sorted(args.data_dir.glob("*.zip"))

    if not archive_paths:
        raise SystemExit(f"No ZIP archives found in {args.data_dir}")

    print(f"Found {len(archive_paths)} archive(s):", flush=True)
    for path in archive_paths:
        print(f"  - {path}", flush=True)
    if len(archive_paths) != 6:
        print(
            "WARNING: expected 6 archives from the current task context, "
            f"but found {len(archive_paths)}.",
            flush=True,
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    timings: dict[str, float] = {}
    csv_paths: list[str] = []

    overall_started = time.perf_counter()
    for number, path in enumerate(archive_paths, start=1):
        print(f"\n[{number}/{len(archive_paths)}] AUDIT {path.name}", flush=True)
        if not path.exists():
            print(f"  MISSING: {path}", flush=True)
            continue
        audit, elapsed = audit_archive(path)
        report = finalize_archive(audit)
        reports.append(report)
        timings[path.name] = round(elapsed, 3)
        csv_path = write_flow_csv(audit, args.output_dir / "flows", args.flow_output_bin_seconds)
        if csv_path:
            csv_paths.append(str(csv_path))
        print(
            f"  done in {elapsed / 60.0:.1f} min | cars={audit.car_trajectories} "
            f"detections={audit.detection_valid} events={audit.selected_event_count}",
            flush=True,
        )

    summary = {
        "schema_version": 1,
        "generated_at_epoch_s": time.time(),
        "archive_count": len(reports),
        "archives": reports,
        "timings_seconds": timings,
        "flow_csvs": csv_paths,
        "notes": [
            "Archives are read directly from ZIP without extracting them to disk.",
            "Only category_name == 'car' is treated as usable, matching the supplied dataset documentation.",
            "Cycle estimation mirrors the production 2-second signed NS-vs-EW flow signal construction.",
            "The audit intentionally reports large temporal gaps because multi-day reference archives may contain long idle gaps that can affect a global autocorrelation cycle estimate.",
            "This audit does not claim traffic-light accuracy; it measures observability and internal evidence quality.",
        ],
    }

    json_path = args.output_dir / "audit_report.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# Traffic Dataset Audit",
        "",
        f"Archives processed: **{len(reports)}**",
        "",
        "> The audit reads ZIP members directly and does not extract the archives.",
        "> It is an observability/data-quality audit, not a traffic-light accuracy measurement.",
        "",
        "## Archive summary",
        "",
        "| Archive | JSON | Cars | Detections valid | Invalid % | APPROACH | STOP | RELEASE | CROSSING | Selected flow events | Cycle | Cycle conf. | 60m median cycle | 60m MAD | Sessions | Largest gap s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for item in reports:
        det = item["detections"]
        events = item["events"]
        flow = item["flow"]
        cycle = flow["cycle_estimate"]
        summary_60 = flow.get("window_cycle_summary") or {}
        sessions = item.get("temporal_sessions", {})
        md_lines.append(
            "| {archive} | {jsons} | {cars} | {valid} | {invalid_pct:.3f} | {approach} | {stop} | {release} | {crossing} | {selected} | {cycle} | {conf} | {median60} | {mad60} | {sessions_count} | {gap} |".format(
                archive=item["archive"],
                jsons=item["json_members"],
                cars=item["trajectories"]["cars"],
                valid=det["valid"],
                invalid_pct=(det["invalid_ratio"] or 0.0) * 100.0,
                approach=events["counts"].get("APPROACH", 0),
                stop=events["counts"].get("STOP", 0),
                release=events["counts"].get("RELEASE", 0),
                crossing=events["counts"].get("CROSSING", 0),
                selected=events["selected_release_crossing"],
                cycle=cycle.get("cycle_seconds"),
                conf=cycle.get("confidence"),
                median60=summary_60.get("median_s"),
                mad60=summary_60.get("mad_s"),
                sessions_count=sessions.get("session_count"),
                gap=round(sessions.get("largest_inter_session_gap_s", 0.0), 1),
            )
        )

    md_lines.extend([
        "",
        "## Key data-quality checks",
        "",
        "| Archive | Unknown approach | Raw non-monotonic detection edges | Gap >2s | Gap >2s % | Cars without valid detections | JSON errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for item in reports:
        zones = item["zones"]
        det = item["detections"]
        md_lines.append(
            "| {archive} | {unknown} | {nonmono} | {gap2} | {gap2pct:.3f} | {nodet} | {jsonerr} |".format(
                archive=item["archive"],
                unknown=zones["unknown_approach"],
                nonmono=det["raw_nonmonotonic_edges"],
                gap2=det["gap_over_2s"],
                gap2pct=(det["gap_over_2s_ratio"] or 0.0) * 100.0,
                nodet=det["trajectories_without_valid_detections"],
                jsonerr=item["json_errors"],
            )
        )

    md_lines.extend([
        "",
        "## What this audit is intended to answer",
        "",
        "1. Whether the six archives actually contain enough clean car trajectories for phase inference.",
        "2. Whether N/S/E/W coverage is balanced and consistent with the current two-group NS/EW model.",
        "3. How many STOP/RELEASE/CROSSING events the production extractor really produces.",
        "4. Whether the traffic flow has a stable recurring cycle or only a weak/global periodicity.",
        "5. Whether large gaps, multi-day sessions, missing data or timestamp irregularities can bias the current cycle/phase inference.",
        "6. Whether reference and anomaly archives differ in the expected event/flow characteristics.",
        "",
        "## Output files",
        "",
        f"- `{json_path.name}` — complete machine-readable audit.",
        "- `flows/*.csv` — compact 10-second flow series for visual/temporal analysis.",
        "",
        "## Important limitation",
        "",
        "The dataset documentation does not provide labelled physical traffic-light controller states. Therefore these results can establish data quality, periodicity and internal evidence for phase reconstruction, but not controller-state classification accuracy.",
    ])

    md_path = args.output_dir / "audit_report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print("\nAUDIT COMPLETE", flush=True)
    print(f"Total time: {(time.perf_counter() - overall_started) / 60.0:.1f} min", flush=True)
    print(f"JSON report: {json_path}", flush=True)
    print(f"Markdown report: {md_path}", flush=True)
    print(f"Flow CSV directory: {args.output_dir / 'flows'}", flush=True)


if __name__ == "__main__":
    main()
