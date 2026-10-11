from __future__ import annotations

import argparse
from collections import Counter
import heapq
import json
from pathlib import Path
import pickle
import shutil
import tempfile
import time
from typing import BinaryIO, Iterator
import zipfile

from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.archive_analysis import (
    SegmentEventStore,
    _stream_members_into_store,
)
from app.core.intersection_config import DEFAULT_INTERSECTION_CONFIG
from app.core.preprocessing import _trajectory_from_dict
from app.core.validation import (
    ValidationDataset,
    _aggregate_cycle_metrics,
    _aggregate_phase_metrics,
    _aggregate_realtime_metrics,
    _aggregate_signal_metrics,
    _nearest_reference_period,
    _phase_metrics_from_model,
    _rebase_events,
    validate_realtime,
    validate_signal,
)

DEFAULT_CHUNK_TRAJECTORIES = 500
DEFAULT_JSON_CHUNK_BYTES = 64 * 1024
DEFAULT_MAX_OBJECT_CHARS = 16 * 1024 * 1024
DEFAULT_SAMPLE_SECONDS = 1.0
DEFAULT_TRANSITION_TOLERANCE_SECONDS = 3.0

MANIFEST_DATASETS = (
    ("reference_lenina_sverdlovsky", "Ленина-Свердловский 11.02.25-19.02.25.zip", "Ленина-Свердловский", "reference"),
    ("accident_lenina_sverdlovsky", "Ленина-Свердловский 27.02.25.zip", "Ленина-Свердловский", "accident"),
    ("reference_lenina_entuziastov", "Ленина-Энтузиастов 10.02.25-17.02.25.zip", "Ленина-Энтузиастов", "reference"),
    ("accident_lenina_entuziastov", "Ленина-Энтузиастов 05.10.24.zip", "Ленина-Энтузиастов", "accident"),
    ("reference_chicherina", "Чичерина-40 Лет Победы 12.04.24.zip", "Чичерина-40 Лет Победы", "reference"),
    ("lane_closure_chicherina", "Чичерина-40 Лет Победы 19.04.24.zip", "Чичерина-40 Лет Победы", "lane_closure"),
)

def _iter_json_objects(stream: BinaryIO, *, chunk_size: int = DEFAULT_JSON_CHUNK_BYTES, max_object_chars: int = DEFAULT_MAX_OBJECT_CHARS) -> Iterator[object]:
    import codecs
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    eof = False
    started = False
    expect_value = True

    def fill() -> bool:
        nonlocal buffer, eof
        if eof:
            return False
        chunk = stream.read(chunk_size)
        if not chunk:
            buffer += utf8.decode(b"", final=True) if not isinstance(chunk, str) else chunk
            eof = True
            return False
        buffer += chunk if isinstance(chunk, str) else utf8.decode(chunk, final=False)
        return True

    while True:
        if not started:
            while True:
                buffer = buffer.lstrip()
                if buffer:
                    if not buffer.startswith("["):
                        raise ValueError("trajectory JSON root must be a list")
                    buffer = buffer[1:]
                    started = True
                    break
                if not fill():
                    raise ValueError("trajectory JSON root must be a list")
        buffer = buffer.lstrip()
        if not buffer:
            if eof:
                raise ValueError("unterminated trajectory JSON array")
            fill()
            continue
        if expect_value:
            if buffer[0] == "]":
                buffer = buffer[1:]
                return
            while True:
                try:
                    value, end_index = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise ValueError(f"invalid trajectory JSON: {exc.msg} at char {exc.pos}") from exc
                    if len(buffer) > max_object_chars:
                        raise ValueError("trajectory JSON object exceeds bounded streaming size") from exc
                    fill()
            buffer = buffer[end_index:]
            expect_value = False
            yield value
            continue
        buffer = buffer.lstrip()
        if not buffer:
            if eof:
                raise ValueError("unterminated trajectory JSON array")
            fill()
            continue
        if buffer[0] == ",":
            buffer = buffer[1:]
            expect_value = True
            continue
        if buffer[0] == "]":
            buffer = buffer[1:]
            while not eof:
                if not buffer.strip():
                    if not fill():
                        break
                else:
                    raise ValueError("unexpected data after trajectory JSON array")
            if buffer.strip():
                raise ValueError("unexpected data after trajectory JSON array")
            return
        raise ValueError("expected ',' or ']' in trajectory JSON array")

def _iter_pickle_records(stream: BinaryIO) -> Iterator[tuple[int, int, dict]]:
    while True:
        try:
            yield pickle.load(stream)
        except EOFError:
            return

def _write_sorted_json_array(chunks: list[Path], output: BinaryIO) -> int:
    iterators = []
    handles = []
    try:
        for chunk in chunks:
            handle = chunk.open("rb")
            handles.append(handle)
            iterators.append(_iter_pickle_records(handle))
        merged = heapq.merge(*iterators, key=lambda item: (int(item[0]), int(item[1])))
        output.write(b"[")
        count = 0
        for _timestamp, _ordinal, item in merged:
            if count:
                output.write(b",")
            output.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            count += 1
        output.write(b"]")
        output.seek(0)
        return count
    finally:
        for handle in handles:
            handle.close()

class MemberAudit:
    def __init__(self, name: str) -> None:
        self.name = name
        self.record_count = 0
        self.usable_car_count = 0
        self.detection_count = 0
        self.invalid_or_skipped_count = 0
        self.missing_millis_count = 0
        self.missing_zone_in_count = 0
        self.order_violation_count = 0
        self.duplicate_id_count = 0
        self.category_counts: Counter[str] = Counter()
        self.first_millis: int | None = None
        self.last_millis: int | None = None
        self._seen_ids: set[str] = set()
        self._last_start_ms: int | None = None
        self.error: str | None = None

    def accept(self, item: object) -> dict | None:
        self.record_count += 1
        if not isinstance(item, dict):
            self.invalid_or_skipped_count += 1
            return None
        category = str(item.get("category_name") or "")
        self.category_counts[category] += 1
        millis = None
        if item.get("millis") is None:
            self.missing_millis_count += 1
        else:
            try:
                millis = int(item["millis"])
            except (TypeError, ValueError):
                self.invalid_or_skipped_count += 1
            if millis is not None:
                self.first_millis = millis if self.first_millis is None else min(self.first_millis, millis)
                self.last_millis = millis if self.last_millis is None else max(self.last_millis, millis)
        if not item.get("zone_in"):
            self.missing_zone_in_count += 1
        identifier = item.get("id")
        if identifier is not None:
            key = str(identifier)
            if key in self._seen_ids:
                self.duplicate_id_count += 1
            else:
                self._seen_ids.add(key)
        detections = item.get("detections")
        if isinstance(detections, list):
            self.detection_count += len(detections)
        trajectory = _trajectory_from_dict(item)
        if trajectory is None:
            self.invalid_or_skipped_count += 1
            return None

        trajectory_start_ms = (
            trajectory.detections[0].millis
            if trajectory.detections
            else trajectory.timestamp_ms
        )
        if (
            self._last_start_ms is not None
            and trajectory_start_ms < self._last_start_ms
        ):
            self.order_violation_count += 1
        self._last_start_ms = int(trajectory_start_ms)

        self.usable_car_count += 1
        return item

    def to_dict(self) -> dict[str, object]:
        return {
            "member": self.name,
            "record_count": self.record_count,
            "usable_car_count": self.usable_car_count,
            "detection_count": self.detection_count,
            "invalid_or_skipped_count": self.invalid_or_skipped_count,
            "missing_millis_count": self.missing_millis_count,
            "missing_zone_in_count": self.missing_zone_in_count,
            "order_violation_count": self.order_violation_count,
            "duplicate_id_count": self.duplicate_id_count,
            "category_counts": dict(self.category_counts),
            "first_millis": self.first_millis,
            "last_millis": self.last_millis,
            "duration_s": (
                round((self.last_millis - self.first_millis) / 1000.0, 3)
                if self.first_millis is not None and self.last_millis is not None
                else None
            ),
            "error": self.error,
        }

def prepare_sorted_member(
    stream: BinaryIO,
    *,
    name: str,
    work_dir: Path,
    chunk_trajectories: int = DEFAULT_CHUNK_TRAJECTORIES,
    max_trajectories: int | None = None,
) -> tuple[BinaryIO, MemberAudit]:
    if chunk_trajectories <= 0:
        raise ValueError("chunk_trajectories must be positive")
    if max_trajectories is not None and max_trajectories <= 0:
        raise ValueError("max_trajectories must be positive when provided")
    work_dir.mkdir(parents=True, exist_ok=True)
    audit = MemberAudit(name)
    chunks: list[Path] = []
    chunk_records: list[tuple[int, int, dict]] = []
    ordinal = 0
    try:
        for value in _iter_json_objects(stream):
            item = audit.accept(value)
            if item is None:
                continue
            trajectory = _trajectory_from_dict(item)
            if trajectory is None:
                continue
            # Production session reconstruction requires trajectory order by
            # interval start, which is the first detection timestamp. The
            # top-level trajectory millis is the exit time and is unsuitable.
            trajectory_start_ms = (
                trajectory.detections[0].millis
                if trajectory.detections
                else trajectory.timestamp_ms
            )
            chunk_records.append((int(trajectory_start_ms), ordinal, item))
            ordinal += 1
            if max_trajectories is not None and ordinal >= max_trajectories:
                break
            if len(chunk_records) >= chunk_trajectories:
                chunk_records.sort(key=lambda x: (x[0], x[1]))
                chunk_path = work_dir / f"chunk_{len(chunks):05d}.pkl"
                with chunk_path.open("wb") as handle:
                    for record in chunk_records:
                        pickle.dump(record, handle, protocol=5)
                chunks.append(chunk_path)
                chunk_records.clear()
        if chunk_records:
            chunk_records.sort(key=lambda x: (x[0], x[1]))
            chunk_path = work_dir / f"chunk_{len(chunks):05d}.pkl"
            with chunk_path.open("wb") as handle:
                for record in chunk_records:
                    pickle.dump(record, handle, protocol=5)
            chunks.append(chunk_path)
            chunk_records.clear()
        output = tempfile.TemporaryFile(mode="w+b")
        _write_sorted_json_array(chunks, output)
        return output, audit
    except Exception as exc:
        audit.error = str(exc)
        for chunk in chunks:
            chunk.unlink(missing_ok=True)
        raise

def _empty_json_stream() -> BinaryIO:
    stream = tempfile.TemporaryFile(mode="w+b")
    stream.write(b"[]")
    stream.seek(0)
    return stream

def discover_datasets(data_dir: Path) -> list[ValidationDataset]:
    datasets: list[ValidationDataset] = []
    missing: list[str] = []
    for name, filename, intersection_id, kind in MANIFEST_DATASETS:
        path = data_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        datasets.append(ValidationDataset(
            name=name,
            path=str(path.resolve()),
            intersection_id=intersection_id,
            kind=kind,
            description="Local real-data validation dataset",
        ))
    if missing:
        raise FileNotFoundError("missing required local archives:\n  " + "\n  ".join(missing))
    return datasets

def _aggregate_audits(audits: list[dict[str, object]]) -> dict[str, object]:
    category_counts: Counter[str] = Counter()
    first_values = [int(item["first_millis"]) for item in audits if item.get("first_millis") is not None]
    last_values = [int(item["last_millis"]) for item in audits if item.get("last_millis") is not None]
    for item in audits:
        category_counts.update({str(key): int(value) for key, value in dict(item.get("category_counts", {})).items()})
    return {
        "json_members": len(audits),
        "records": sum(int(item["record_count"]) for item in audits),
        "usable_car_trajectories": sum(int(item["usable_car_count"]) for item in audits),
        "detections": sum(int(item["detection_count"]) for item in audits),
        "invalid_or_skipped": sum(int(item["invalid_or_skipped_count"]) for item in audits),
        "missing_millis": sum(int(item["missing_millis_count"]) for item in audits),
        "missing_zone_in": sum(int(item["missing_zone_in_count"]) for item in audits),
        "order_violations": sum(int(item["order_violation_count"]) for item in audits),
        "duplicate_ids": sum(int(item["duplicate_id_count"]) for item in audits),
        "category_counts": dict(category_counts),
        "first_millis": min(first_values) if first_values else None,
        "last_millis": max(last_values) if last_values else None,
        "duration_s": (
            round((max(last_values) - min(first_values)) / 1000.0, 3)
            if first_values and last_values
            else None
        ),
    }

def _member_streams(
    archive_path: Path,
    work_root: Path,
    audit_sink: list[dict[str, object]],
    *,
    chunk_trajectories: int,
    max_trajectories_per_member: int | None = None,
    max_members: int | None = None,
) -> tuple[int, Iterator[tuple[int, str, BinaryIO]]]:
    if max_trajectories_per_member is not None and max_trajectories_per_member <= 0:
        raise ValueError("max_trajectories_per_member must be positive when provided")
    if max_members is not None and max_members <= 0:
        raise ValueError("max_members must be positive when provided")
    archive = zipfile.ZipFile(archive_path)
    members = [
        member for member in archive.infolist()
        if not member.is_dir() and member.filename.lower().endswith(".json")
    ]
    if max_members is not None:
        members = members[:max_members]

    def iterator() -> Iterator[tuple[int, str, BinaryIO]]:
        try:
            for index, member in enumerate(members):
                member_dir = work_root / f"member_{index:04d}"
                prepared: BinaryIO | None = None
                audit: MemberAudit | None = None
                try:
                    with archive.open(member) as raw:
                        prepared, audit = prepare_sorted_member(
                            raw,
                            name=member.filename,
                            work_dir=member_dir,
                            chunk_trajectories=chunk_trajectories,
                            max_trajectories=max_trajectories_per_member,
                        )
                    audit_sink.append(audit.to_dict())
                except Exception as exc:
                    if audit is None:
                        audit = MemberAudit(member.filename)
                    audit.error = str(exc)
                    audit_sink.append(audit.to_dict())
                    prepared = _empty_json_stream()
                try:
                    yield index, member.filename, prepared
                finally:
                    prepared.close()
                    shutil.rmtree(member_dir, ignore_errors=True)
        finally:
            archive.close()

    return len(members), iterator()

def analyze_local_archive(
    dataset: ValidationDataset,
    *,
    work_root: Path,
    sample_seconds: float,
    transition_tolerance_seconds: float,
    baseline: TrafficBaselineProfile | None,
    chunk_trajectories: int,
    max_trajectories_per_member: int | None = None,
    max_members: int | None = None,
) -> tuple[dict[str, object], object]:
    audit_sink: list[dict[str, object]] = []
    started = time.perf_counter()
    member_count, members = _member_streams(
        Path(dataset.path),
        work_root,
        audit_sink,
        chunk_trajectories=chunk_trajectories,
        max_trajectories_per_member=max_trajectories_per_member,
        max_members=max_members,
    )
    store = SegmentEventStore()
    analysis = _stream_members_into_store(
        store,
        members,
        total_members=member_count,
        session_gap_seconds=300.0,
        progress_callback=None,
        isolate_member_errors=True,
        filename=Path(dataset.path).name,
        source_format="zip",
        intersection_config=DEFAULT_INTERSECTION_CONFIG,
    )

    regime_reports: list[dict[str, object]] = []
    cycle_reports: list[dict[str, object]] = []
    phase_reports: list[dict[str, object]] = []
    signal_reports: list[dict[str, object]] = []
    realtime_reports: list[dict[str, object]] = []

    for session_index, session in enumerate(analysis.sessions):
        regime_events = analysis.segment_events[session_index] if session_index < len(analysis.segment_events) else ()

        if session.cycle is not None:
            cycle = session.cycle
            candidate = cycle.estimate.candidate_periods[0] if cycle.estimate.candidate_periods else None
            cycle_reports.append({
                "period_seconds": cycle.estimate.cycle_seconds,
                "confidence": cycle.estimate.confidence,
                "stability": candidate.stability if candidate else None,
                "repetitions": candidate.repetitions if candidate else 0,
                "candidate_count": len(cycle.estimate.candidate_periods),
            })
        else:
            cycle_reports.append({
                "period_seconds": None,
                "confidence": 0.0,
                "stability": None,
                "repetitions": 0,
                "candidate_count": 0,
            })

        if session.phase_model is not None:
            phase_reports.append(_phase_metrics_from_model(regime_events, session.phase_model))
            signal_reports.append(validate_signal(
                regime_events,
                session.phase_model,
                sample_seconds=sample_seconds,
                transition_tolerance_seconds=transition_tolerance_seconds,
                baseline=baseline,
            ))
            realtime_reports.append(validate_realtime(regime_events, session.phase_model))
        else:
            phase_reports.append({
                "status": session.status,
                "phase_count": None,
                "phase_coverage": None,
                "cycle_consistency": None,
                "overlap": None,
                "event_support_count": 0,
                "event_contradictory_count": 0,
            })
            signal_reports.append({"status": "not_run"})
            realtime_reports.append({"status": "not_run"})

        regime_reports.append({
            "session_index": session.session_index,
            "regime_index": session.regime_index,
            "regime_count": session.regime_count,
            "start_timestamp_ms": session.start_timestamp_ms,
            "end_timestamp_ms": session.end_timestamp_ms,
            "duration_s": session.duration_s,
            "status": session.status,
            "confidence": session.confidence,
            "event_count": len(regime_events),
            "cycle": cycle_reports[-1],
            "phase": phase_reports[-1],
            "signal": signal_reports[-1],
            "realtime": realtime_reports[-1],
        })

    report = {
        "dataset": dataset.to_dict(),
        "source": {
            "archive": str(Path(dataset.path).resolve()),
            "analysis_seconds": round(time.perf_counter() - started, 3),
            "production_progress": analysis.progress.to_dict() if analysis.progress is not None else None,
        },
        "audit": {
            "aggregate": _aggregate_audits(audit_sink),
            "members": audit_sink,
        },
        "cycle": _aggregate_cycle_metrics(
            cycle_reports,
            reference_options=(),
            session_count=len({item["session_index"] for item in regime_reports}),
            regime_count=len(regime_reports),
            ambiguous_count=sum(item["status"] == "ambiguous" for item in regime_reports),
        ),
        "phase": _aggregate_phase_metrics(
            phase_reports,
            ambiguous_count=sum(item["status"] == "ambiguous" for item in regime_reports),
        ),
        "signal": _aggregate_signal_metrics(signal_reports),
        "realtime": _aggregate_realtime_metrics(realtime_reports),
        "regimes": regime_reports,
    }
    return report, analysis

def _build_reference_baseline(records: list[tuple[ValidationDataset, object]]) -> dict[str, TrafficBaselineProfile]:
    profiles_by_intersection: dict[str, list[TrafficBaselineProfile]] = {}
    for dataset, analysis in records:
        for index, session in enumerate(analysis.sessions):
            if index >= len(analysis.segment_events):
                continue
            events = analysis.segment_events[index]
            if not events:
                continue
            profiles_by_intersection.setdefault(dataset.intersection_id, []).append(
                TrafficBaselineProfile.from_events(
                    _rebase_events(events, session.start_timestamp_ms),
                    window_seconds=12.0,
                    source=(
                        f"local_reference:{dataset.name}:"
                        f"session{session.session_index}:regime{session.regime_index}"
                    ),
                )
            )
    return {
        intersection_id: TrafficBaselineProfile.aggregate(
            profiles,
            source=f"local_reference_pool:{intersection_id}",
        )
        for intersection_id, profiles in profiles_by_intersection.items()
        if profiles
    }

def _attach_reference_context(report: dict[str, object], *, reference_periods: dict[str, list[float]], baselines: dict[str, TrafficBaselineProfile]) -> None:
    intersection_id = str(report["dataset"]["intersection_id"])
    periods = reference_periods.get(intersection_id, [])
    report["reference"] = {
        "intersection_id": intersection_id,
        "dataset_names": [
            name for name, _filename, item_intersection, kind in MANIFEST_DATASETS
            if item_intersection == intersection_id and kind == "reference"
        ],
        "period_options_seconds": [round(item, 4) for item in periods],
        "baseline_source": baselines[intersection_id].source if intersection_id in baselines else None,
    }

def _write_markdown(summary: dict[str, object], reports: list[dict[str, object]], path: Path) -> None:
    lines = [
        "# Full local validation report",
        "",
        f"- Generated: {summary['generated_at']}",
        f"- Dataset count: {summary['dataset_count']}",
        f"- Night dataset: {summary['night_traffic']['status']}",
        "",
        "## Corpus audit",
        "",
    ]
    for report in reports:
        audit = report["audit"]["aggregate"]
        lines.append(
            f"- **{report['dataset']['name']}**: "
            f"{audit['usable_car_trajectories']} car trajectories, "
            f"{audit['detections']} detections, "
            f"{audit['order_violations']} ordering violations, "
            f"{audit['duplicate_ids']} duplicate IDs, "
            f"{audit['json_members']} JSON members."
        )
    lines.extend(["", "## Production results", ""])
    for report in reports:
        dataset = report["dataset"]
        cycle = report["cycle"]
        signal = report["signal"]
        realtime = report["realtime"]
        lines.append(
            f"- **{dataset['name']}**: "
            f"cycle={cycle.get('period_seconds')}, "
            f"cycle_confidence={cycle.get('confidence')}, "
            f"unknown_rate={signal.get('unknown_rate')}, "
            f"anomaly_max_score={signal.get('anomaly_max_score')}, "
            f"batch_realtime_agreement={realtime.get('batch_realtime_agreement')}, "
            f"p95_ms={realtime.get('latency_p95_ms')}."
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "These are consistency, behaviour, scenario, and runtime measurements.",
        "They are not controller-state accuracy because the supplied corpus has no labelled signal-controller ground truth.",
        "The six supplied archives cover reference, accident, and lane-closure scenarios.",
        "Night traffic is unavailable in the supplied local corpus.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def main() -> int:
    parser = argparse.ArgumentParser(description="Run streaming validation on the six supplied local archives.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("validation_output_local"))
    parser.add_argument("--sample-seconds", type=float, default=DEFAULT_SAMPLE_SECONDS)
    parser.add_argument("--transition-tolerance-seconds", type=float, default=DEFAULT_TRANSITION_TOLERANCE_SECONDS)
    parser.add_argument("--chunk-trajectories", type=int, default=DEFAULT_CHUNK_TRAJECTORIES)
    parser.add_argument(
        "--max-trajectories-per-member",
        type=int,
        default=None,
        help="stop after this many usable car trajectories in each JSON member",
    )
    parser.add_argument(
        "--max-members",
        type=int,
        default=None,
        help="process only the first N JSON members of each ZIP",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="quick real-data smoke: first JSON member and first 750 usable car trajectories per dataset",
    )
    args = parser.parse_args()

    if args.sample_seconds <= 0:
        raise SystemExit("--sample-seconds must be positive")
    if args.transition_tolerance_seconds < 0:
        raise SystemExit("--transition-tolerance-seconds must be non-negative")
    if args.chunk_trajectories <= 0:
        raise SystemExit("--chunk-trajectories must be positive")
    if args.max_trajectories_per_member is not None and args.max_trajectories_per_member <= 0:
        raise SystemExit("--max-trajectories-per-member must be positive")
    if args.max_members is not None and args.max_members <= 0:
        raise SystemExit("--max-members must be positive")
    if args.quick and (args.max_trajectories_per_member is not None or args.max_members is not None):
        raise SystemExit("--quick cannot be combined with explicit --max-trajectories-per-member/--max-members")

    max_trajectories_per_member = 750 if args.quick else args.max_trajectories_per_member
    max_members = 1 if args.quick else args.max_members

    data_dir = args.data_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_root = output_dir / ".work"
    if work_root.exists():
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    datasets = discover_datasets(data_dir)
    references = [dataset for dataset in datasets if dataset.kind == "reference"]
    scenarios = [dataset for dataset in datasets if dataset.kind != "reference"]

    reports: list[dict[str, object]] = []
    reference_records: list[tuple[ValidationDataset, object]] = []
    reference_periods: dict[str, list[float]] = {}

    print(f"[validation] found {len(datasets)} local datasets", flush=True)

    for index, dataset in enumerate(references, start=1):
        print(f"[validation] reference {index}/{len(references)}: {dataset.name}", flush=True)
        report, analysis = analyze_local_archive(
            dataset,
            work_root=work_root / dataset.name,
            sample_seconds=args.sample_seconds,
            transition_tolerance_seconds=args.transition_tolerance_seconds,
            baseline=None,
            chunk_trajectories=args.chunk_trajectories,
            max_trajectories_per_member=max_trajectories_per_member,
            max_members=max_members,
        )
        reports.append(report)
        reference_records.append((dataset, analysis))
        reference_periods[dataset.intersection_id] = [
            float(session.cycle.estimate.cycle_seconds)
            for session in analysis.sessions
            if session.cycle is not None
        ]

    baselines = _build_reference_baseline(reference_records)

    for _dataset, analysis in reference_records:
        if isinstance(analysis.segment_events, SegmentEventStore):
            analysis.segment_events.close()

    for index, dataset in enumerate(scenarios, start=1):
        print(f"[validation] scenario {index}/{len(scenarios)}: {dataset.name}", flush=True)
        report, analysis = analyze_local_archive(
            dataset,
            work_root=work_root / dataset.name,
            sample_seconds=args.sample_seconds,
            transition_tolerance_seconds=args.transition_tolerance_seconds,
            baseline=baselines.get(dataset.intersection_id),
            chunk_trajectories=args.chunk_trajectories,
            max_trajectories_per_member=max_trajectories_per_member,
            max_members=max_members,
        )
        reference_options = reference_periods.get(dataset.intersection_id, [])
        report["cycle"]["reference_period_options_seconds"] = [round(float(value), 4) for value in reference_options]
        report["cycle"]["reference_period_seconds"] = _nearest_reference_period(
            report["cycle"].get("period_seconds"),
            reference_options,
        )
        period = report["cycle"].get("period_seconds")
        ref_period = report["cycle"].get("reference_period_seconds")
        report["cycle"]["reference_error_seconds"] = (
            round(abs(float(period) - float(ref_period)), 4)
            if period is not None and ref_period is not None
            else None
        )
        _attach_reference_context(
            report,
            reference_periods=reference_periods,
            baselines=baselines,
        )
        reports.append(report)
        if isinstance(analysis.segment_events, SegmentEventStore):
            analysis.segment_events.close()

    summary = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data_dir": str(data_dir),
        "dataset_count": len(reports),
        "datasets": [report["dataset"]["name"] for report in reports],
        "night_traffic": {
            "status": "not_available",
            "message": "No night archive is present in the supplied six-archive corpus.",
        },
        "ground_truth": "UNAVAILABLE",
        "interpretation": "Consistency, behaviour, scenario and runtime measurements; not controller-state accuracy.",
        "totals": {
            "car_trajectories": sum(int(report["audit"]["aggregate"]["usable_car_trajectories"]) for report in reports),
            "detections": sum(int(report["audit"]["aggregate"]["detections"]) for report in reports),
            "ordering_violations": sum(int(report["audit"]["aggregate"]["order_violations"]) for report in reports),
            "duplicate_ids": sum(int(report["audit"]["aggregate"]["duplicate_ids"]) for report in reports),
        },
        "validation_mode": "quick_sample" if args.quick else "full",
        "limits": {
            "max_members": max_members,
            "max_trajectories_per_member": max_trajectories_per_member,
        },
        "scenario_counts": {
            kind: sum(1 for report in reports if report["dataset"]["kind"] == kind)
            for kind in ("reference", "accident", "lane_closure")
        },
    }

    summary_path = output_dir / "summary.json"
    datasets_path = output_dir / "datasets.json"
    report_path = output_dir / "report.md"
    summary_path.write_text(
        json.dumps({"summary": summary, "reports": reports}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    datasets_path.write_text(
        json.dumps(
            [report["dataset"] | {"audit": report["audit"]["aggregate"]} for report in reports],
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    _write_markdown(summary, reports, report_path)
    shutil.rmtree(work_root, ignore_errors=True)
    print(f"[validation] summary={summary_path}", flush=True)
    print(f"[validation] report={report_path}", flush=True)
    print(f"[validation] datasets={datasets_path}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
