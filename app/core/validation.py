from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from collections.abc import Callable
import json
from pathlib import Path
import statistics
import time
import tracemalloc
from typing import Sequence
import zipfile

from app.core.anomaly_inference import AnomalyAwareSignalInference
from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.event_cycle_estimator import EventCycleEstimate, estimate_event_cycle
from app.core.event_phase_discovery import EventPhase, EventPhaseDiscovery, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file, load_trajectory_payload
from app.core.realtime_inference import RealtimeSignalInferenceEngine
from app.core.signal_state_estimator import SignalState, SignalStateEstimator
from app.core.reconstruction import extract_events_from_trajectories


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ValidationDataset:
    name: str
    path: str
    kind: str = "scenario"
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 4)


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    items = sorted(float(value) for value in values)
    if len(items) == 1:
        return round(items[0], 4)
    pos = q * (len(items) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(items) - 1)
    return round(items[lo] + (items[hi] - items[lo]) * (pos - lo), 4)


def load_events(path: Path) -> list[TrajectoryEvent]:
    if path.suffix.lower() == ".json":
        return _sorted_events(extract_events_from_trajectories(load_trajectory_file(path)))

    if path.suffix.lower() != ".zip":
        raise ValueError(f"unsupported validation input: {path}")

    events: list[TrajectoryEvent] = []
    with zipfile.ZipFile(path) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and member.filename.lower().endswith(".json")
        ]
        if not members:
            raise ValueError(f"validation archive contains no JSON files: {path}")

        for member in members:
            with archive.open(member) as handle:
                payload = json.load(handle)
            events.extend(
                extract_events_from_trajectories(
                    load_trajectory_payload(payload)
                )
            )
    return events


@dataclass(frozen=True)
class _EventWindowIndex:
    events: tuple[TrajectoryEvent, ...]
    timestamps_ms: tuple[int, ...]

    @classmethod
    def build(cls, events: Sequence[TrajectoryEvent]) -> "_EventWindowIndex":
        ordered = tuple(
            sorted(
                events,
                key=lambda event: (
                    event.timestamp_ms,
                    event.event_type.value,
                    event.approach,
                    event.movement,
                ),
            )
        )
        return cls(
            events=ordered,
            timestamps_ms=tuple(event.timestamp_ms for event in ordered),
        )

    def between(self, lower_ms: int, upper_ms: int) -> tuple[TrajectoryEvent, ...]:
        left = bisect_left(self.timestamps_ms, lower_ms)
        right = bisect_right(self.timestamps_ms, upper_ms)
        return self.events[left:right]


def _sorted_events(events: Sequence[TrajectoryEvent]) -> list[TrajectoryEvent]:
    return list(_EventWindowIndex.build(events).events)


def _phase_at(
    phases: Sequence[EventPhase],
    position: float,
    cycle_seconds: float,
) -> EventPhase | None:
    for phase in phases:
        start = float(phase.phase_start) % cycle_seconds
        end = float(phase.phase_end) % cycle_seconds
        inside = (
            start <= position < end
            if start <= end
            else position >= start or position < end
        )
        if inside:
            return phase
    return None


def _circular_distance(
    value: float,
    target: float,
    cycle_seconds: float,
) -> float:
    distance = abs(value - target)
    return min(distance, cycle_seconds - distance)


def _cycle_consistency(
    phase_model: EventPhaseDiscoveryResult,
    events: Sequence[TrajectoryEvent],
) -> float | None:
    selected = [
        event
        for event in events
        if event.event_type in {EventType.RELEASE, EventType.CROSSING}
        and event.approach in {"N", "S", "E", "W"}
    ]
    if not selected:
        return None
    origin_ms = int(
        getattr(
            phase_model,
            "origin_timestamp_ms",
            min(event.timestamp_ms for event in selected),
        )
    )
    supporting = 0.0
    total = 0.0
    phase_groups = {
        phase.phase_id: set(phase.active_approaches)
        for phase in phase_model.phases
    }
    for event in selected:
        position = (
            (event.timestamp_ms - origin_ms) / 1000.0
        ) % phase_model.cycle_seconds
        phase = _phase_at(
            phase_model.phases,
            position,
            phase_model.cycle_seconds,
        )
        if phase is None:
            continue
        weight = 1.0 if event.event_type == EventType.RELEASE else 0.5
        total += weight
        expected = phase_groups.get(phase.phase_id, set())
        if event.approach in expected:
            supporting += weight
    return round(supporting / total, 4) if total else None


def validate_cycle(
    events: Sequence[TrajectoryEvent],
    reference_period: float | None,
) -> tuple[dict[str, object], EventCycleEstimate | None]:
    try:
        result = estimate_event_cycle(events)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}, None
    candidate = (
        result.estimate.candidate_periods[0]
        if result.estimate.candidate_periods
        else None
    )
    error = (
        abs(result.estimate.cycle_seconds - reference_period)
        if reference_period is not None
        else None
    )
    return {
        "status": "ok",
        "period_seconds": result.estimate.cycle_seconds,
        "confidence": result.estimate.confidence,
        "stability": candidate.stability if candidate else None,
        "repetitions": candidate.repetitions if candidate else None,
        "candidate_count": len(result.estimate.candidate_periods),
        "reference_period_seconds": reference_period,
        "reference_error_seconds": round(error, 4) if error is not None else None,
    }, result


def validate_phase(
    events: Sequence[TrajectoryEvent],
    cycle_seconds: float,
) -> tuple[dict[str, object], EventPhaseDiscoveryResult | None]:
    try:
        model = EventPhaseDiscovery().discover(
            events,
            cycle_seconds=cycle_seconds,
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}, None
    total = model.supporting_event_count + model.contradictory_event_count
    return {
        "status": "ok",
        "phase_count": len(model.phases),
        "phase_coverage": model.cycle_coverage,
        "overlap": model.overlap,
        "cycle_consistency": _cycle_consistency(model, events),
        "event_support_count": model.supporting_event_count,
        "event_contradictory_count": model.contradictory_event_count,
        "event_support_ratio": (
            round(model.supporting_event_count / total, 4) if total else None
        ),
        "event_contradictory_ratio": (
            round(model.contradictory_event_count / total, 4) if total else None
        ),
        "phases": [phase.to_dict() for phase in model.phases],
    }, model


def _sample_times(
    events: Sequence[TrajectoryEvent],
    sample_seconds: float,
    *,
    origin_ms: int | None = None,
) -> tuple[int, list[float]]:
    origin = int(
        origin_ms
        if origin_ms is not None
        else min(event.timestamp_ms for event in events)
    )
    duration = max(
        0.0,
        (max(event.timestamp_ms for event in events) - origin) / 1000.0,
    )
    count = max(1, int(duration / sample_seconds) + 1)
    return origin, [
        min(duration, index * sample_seconds)
        for index in range(count)
    ]


def validate_signal(
    events: Sequence[TrajectoryEvent],
    phase_model: EventPhaseDiscoveryResult,
    *,
    sample_seconds: float,
    transition_tolerance_seconds: float,
    baseline: TrafficBaselineProfile | None,
) -> dict[str, object]:
    origin, times = _sample_times(
        events,
        sample_seconds,
        origin_ms=phase_model.origin_timestamp_ms,
    )
    event_index = _EventWindowIndex.build(events)
    estimator = SignalStateEstimator(
        phase_model,
        event_origin_ms=origin,
    )
    anomaly = AnomalyAwareSignalInference(phase_model, baseline)
    recent_window_seconds = 12.0

    total_states = 0
    unknown_states = 0
    confidence_sum = 0.0
    confidence_count = 0
    continuity_pairs = 0
    continuity_same = 0
    transitions = 0
    transition_consistent = 0
    boundaries = sorted(
        {
            boundary % phase_model.cycle_seconds
            for phase in phase_model.phases
            for boundary in (phase.phase_start, phase.phase_end)
        }
    )
    anomaly_scores: list[float] = []
    conditions: dict[str, int] = {}
    false_switches = 0
    state_comparisons = 0
    previous_result = None

    for timestamp_s in times:
        now_ms = origin + int(timestamp_s * 1000.0)
        window_events = event_index.between(
            now_ms - int(recent_window_seconds * 1000.0),
            now_ms,
        )
        result = estimator.estimate(timestamp_s, window_events)

        for state in result.approaches:
            total_states += 1
            unknown_states += state.state == SignalState.UNKNOWN
            confidence_sum += state.confidence
            confidence_count += 1

        if previous_result is not None:
            previous_states = {
                state.approach: state.state
                for state in previous_result.approaches
            }
            current_states = {
                state.approach: state.state
                for state in result.approaches
            }
            for approach, previous_state in previous_states.items():
                current_state = current_states[approach]
                continuity_pairs += 1
                continuity_same += previous_state == current_state
                if (
                    previous_state != current_state
                    and previous_state != SignalState.UNKNOWN
                    and current_state != SignalState.UNKNOWN
                ):
                    transitions += 1
                    distance = min(
                        _circular_distance(
                            result.cycle_phase_s,
                            boundary,
                            phase_model.cycle_seconds,
                        )
                        for boundary in boundaries
                    ) if boundaries else phase_model.cycle_seconds
                    transition_consistent += distance <= transition_tolerance_seconds

        aware_result = anomaly.estimate(
            result,
            window_events,
            current_time_s=timestamp_s,
            recent_window_s=recent_window_seconds,
            origin_ms=origin,
        )
        anomaly_scores.append(aware_result.indicators.anomaly_score)
        base_states = {
            item.approach: item.state
            for item in result.approaches
        }
        aware_states = {
            item.approach: item.state
            for item in aware_result.signal.approaches
        }
        for approach, base_state in base_states.items():
            aware_state = aware_states[approach]
            state_comparisons += 1
            if {base_state, aware_state} == {
                SignalState.GREEN,
                SignalState.RED,
            }:
                false_switches += 1
        name = aware_result.indicators.condition.value
        conditions[name] = conditions.get(name, 0) + 1
        previous_result = result

    mean_confidence = confidence_sum / confidence_count if confidence_count else None
    return {
        "status": "ok",
        "sample_count": len(times),
        "state_continuity": (
            round(continuity_same / continuity_pairs, 4)
            if continuity_pairs
            else None
        ),
        "transition_count": transitions,
        "transition_consistency": (
            round(transition_consistent / transitions, 4)
            if transitions
            else None
        ),
        "mean_state_confidence": (
            round(mean_confidence, 4)
            if mean_confidence is not None
            else None
        ),
        "unknown_rate": (
            round(unknown_states / total_states, 4)
            if total_states
            else None
        ),
        "anomaly_mean_score": _median(anomaly_scores),
        "anomaly_max_score": (
            round(max(anomaly_scores), 4) if anomaly_scores else None
        ),
        "anomaly_conditions": conditions,
        "false_state_switch_rate": (
            round(false_switches / state_comparisons, 4)
            if state_comparisons
            else None
        ),
    }


def validate_realtime(
    events: Sequence[TrajectoryEvent],
    phase_model: EventPhaseDiscoveryResult,
    *,
    agreement_limit: int = 200,
) -> dict[str, object]:
    origin = int(
        getattr(
            phase_model,
            "origin_timestamp_ms",
            min(event.timestamp_ms for event in events),
        )
    )
    ordered = _sorted_events(events)
    event_index = _EventWindowIndex.build(ordered)
    engine = RealtimeSignalInferenceEngine(
        phase_model,
        event_origin_ms=origin,
        baseline=None,
    )
    latencies: list[float] = []
    agreements = 0
    comparisons = 0
    max_buffer = 0
    step = max(1, len(ordered) // max(1, agreement_limit))
    recent_window_ms = 12_000

    tracemalloc.start()
    batch_estimator = SignalStateEstimator(
        phase_model,
        event_origin_ms=origin,
    )
    try:
        for index, event in enumerate(ordered):
            start = time.perf_counter_ns()
            snapshot = engine.ingest_event(event)
            latencies.append((time.perf_counter_ns() - start) / 1_000_000.0)
            max_buffer = max(max_buffer, snapshot.buffer_event_count)

            if index % step == 0 or index == len(ordered) - 1:
                batch_events = event_index.between(
                    event.timestamp_ms - recent_window_ms,
                    event.timestamp_ms,
                )
                batch = batch_estimator.estimate(
                    (event.timestamp_ms - origin) / 1000.0,
                    batch_events,
                )
                batch_states = {
                    state.approach: state.state.value
                    for state in batch.approaches
                }
                agreements += int(
                    snapshot.phase_id == batch.phase_id
                    and snapshot.signal_states == batch_states
                )
                comparisons += 1
    finally:
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    return {
        "status": "ok",
        "event_count": len(ordered),
        "latency_mean_ms": (
            round(sum(latencies) / len(latencies), 4)
            if latencies
            else None
        ),
        "latency_p95_ms": _quantile(latencies, 0.95),
        "peak_tracemalloc_bytes": peak_memory,
        "max_rolling_buffer_events": max_buffer,
        "batch_realtime_agreement": (
            round(agreements / comparisons, 4)
            if comparisons
            else None
        ),
        "agreement_comparisons": comparisons,
    }


def _rebase_events(
    events: Sequence[TrajectoryEvent],
    origin_ms: int,
) -> list[TrajectoryEvent]:
    return [
        TrajectoryEvent(
            event_type=event.event_type,
            timestamp_ms=event.timestamp_ms - origin_ms,
            approach=event.approach,
            movement=event.movement,
            confidence=event.confidence,
            quality=event.quality,
        )
        for event in events
    ]


class ValidationRunner:
    def __init__(
        self,
        datasets: Sequence[ValidationDataset],
        *,
        sample_seconds: float = 1.0,
        transition_tolerance_seconds: float = 3.0,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        if not datasets:
            raise ValueError("at least one dataset is required")
        if sample_seconds <= 0:
            raise ValueError("sample_seconds must be positive")
        self.datasets = tuple(datasets)
        self.sample_seconds = float(sample_seconds)
        self.transition_tolerance_seconds = float(
            transition_tolerance_seconds
        )
        self.progress = progress or (lambda _message: None)

    def run(self) -> dict[str, object]:
        reference_cycles: dict[str, float] = {}
        reference_cycle_metrics: dict[str, dict[str, object]] = {}
        reference_phase_metrics: dict[str, dict[str, object]] = {}
        reference_phase_models: dict[str, EventPhaseDiscoveryResult] = {}
        reference_profiles: list[TrafficBaselineProfile] = []
        reference_errors: dict[str, str] = {}
        reference_datasets = [
            dataset
            for dataset in self.datasets
            if dataset.kind == "reference"
        ]

        # Prepare each reference exactly once for cycle/baseline/phase data.
        # Expensive signal/realtime validation is deferred until the shared
        # reference baseline has been built, so reference datasets are not
        # fully validated twice.
        for ref_index, dataset in enumerate(reference_datasets, start=1):
            self.progress(
                f"preparing reference {ref_index}/{len(reference_datasets)}: {dataset.name}"
            )
            try:
                events = load_events(Path(dataset.path))
                cycle_metrics, cycle_estimate = validate_cycle(events, None)
                reference_cycle_metrics[dataset.name] = dict(cycle_metrics)
                if cycle_estimate is None:
                    continue

                cycle_seconds = cycle_estimate.estimate.cycle_seconds
                reference_cycles[dataset.name] = cycle_seconds

                origin = min(event.timestamp_ms for event in events)
                reference_profiles.append(
                    TrafficBaselineProfile.from_events(
                        _rebase_events(events, origin),
                        window_seconds=12.0,
                        source=f"reference:{dataset.name}",
                    )
                )

                phase_metrics, phase_model = validate_phase(
                    events,
                    cycle_seconds,
                )
                reference_phase_metrics[dataset.name] = dict(phase_metrics)
                if phase_model is not None:
                    reference_phase_models[dataset.name] = phase_model
            except Exception as exc:
                reference_errors[dataset.name] = str(exc)
                reference_cycle_metrics.setdefault(
                    dataset.name,
                    {"status": "error", "error": str(exc)},
                )

        reference_period = (
            round(statistics.median(reference_cycles.values()), 4)
            if reference_cycles
            else None
        )
        baseline = (
            TrafficBaselineProfile.aggregate(
                reference_profiles,
                source="validation_reference_pool",
            )
            if reference_profiles
            else None
        )

        self.progress(
            "reference baseline ready: "
            f"{len(reference_profiles)} profiles, period={reference_period}"
        )

        dataset_reports: list[dict[str, object]] = []
        total_datasets = len(self.datasets)
        for dataset_index, dataset in enumerate(self.datasets, start=1):
            self.progress(
                f"validating dataset {dataset_index}/{total_datasets}: {dataset.name}"
            )
            events: list[TrajectoryEvent] = []
            cycle_metrics: dict[str, object]
            cycle_seconds: float | None = None

            try:
                events = load_events(Path(dataset.path))
                if dataset.kind == "reference" and dataset.name in reference_cycles:
                    cycle_seconds = reference_cycles[dataset.name]
                    cycle_metrics = dict(
                        reference_cycle_metrics.get(
                            dataset.name,
                            {"status": "ok", "period_seconds": cycle_seconds},
                        )
                    )
                else:
                    cycle_metrics, cycle_estimate = validate_cycle(events, None)
                    cycle_seconds = (
                        cycle_estimate.estimate.cycle_seconds
                        if cycle_estimate is not None
                        else None
                    )
            except Exception as exc:
                cycle_metrics = {"status": "error", "error": str(exc)}
                reference_errors.setdefault(dataset.name, str(exc))

            if cycle_seconds is not None and reference_period is not None:
                cycle_metrics["reference_period_seconds"] = reference_period
                if dataset.kind == "reference":
                    other_reference_periods = [
                        period
                        for name, period in reference_cycles.items()
                        if name != dataset.name
                    ]
                    target_period = (
                        statistics.median(other_reference_periods)
                        if other_reference_periods
                        else None
                    )
                else:
                    target_period = reference_period
                cycle_metrics["reference_error_seconds"] = (
                    round(abs(cycle_seconds - float(target_period)), 4)
                    if target_period is not None
                    else None
                )

            phase_metrics: dict[str, object] = {"status": "not_run"}
            signal_metrics: dict[str, object] = {"status": "not_run"}
            realtime_metrics: dict[str, object] = {"status": "not_run"}
            if cycle_seconds is not None and events:
                if (
                    dataset.kind == "reference"
                    and dataset.name in reference_phase_models
                ):
                    phase_metrics = dict(
                        reference_phase_metrics.get(
                            dataset.name,
                            {"status": "ok"},
                        )
                    )
                    phase_model = reference_phase_models[dataset.name]
                else:
                    phase_metrics, phase_model = validate_phase(
                        events,
                        cycle_seconds,
                    )

                if phase_model is not None:
                    signal_metrics = validate_signal(
                        events,
                        phase_model,
                        sample_seconds=self.sample_seconds,
                        transition_tolerance_seconds=self.transition_tolerance_seconds,
                        baseline=baseline,
                    )
                    realtime_metrics = validate_realtime(events, phase_model)

            dataset_reports.append(
                {
                    "dataset": dataset.to_dict(),
                    "event_count": len(events),
                    "cycle": cycle_metrics,
                    "phase": phase_metrics,
                    "signal": signal_metrics,
                    "realtime": realtime_metrics,
                }
            )
            self.progress(
                f"finished dataset {dataset_index}/{total_datasets}: {dataset.name} "
                f"events={len(events)}"
            )

        reference_confidence_values = [
            float(item["signal"]["mean_state_confidence"])
            for item in dataset_reports
            if item["dataset"]["kind"] == "reference"
            and item["signal"].get("mean_state_confidence") is not None
        ]
        reference_confidence = (
            statistics.median(reference_confidence_values)
            if reference_confidence_values
            else None
        )

        for item in dataset_reports:
            signal_metrics = item["signal"]
            if not isinstance(signal_metrics, dict):
                continue
            if (
                reference_confidence is not None
                and signal_metrics.get("mean_state_confidence") is not None
            ):
                signal_metrics["reference_confidence_delta"] = round(
                    reference_confidence
                    - float(signal_metrics["mean_state_confidence"]),
                    4,
                )
            else:
                signal_metrics["reference_confidence_delta"] = None

        return {
            "schema_version": SCHEMA_VERSION,
            "reference_pool": {
                "dataset_count": len(reference_datasets),
                "median_period_seconds": reference_period,
                "median_signal_confidence": (
                    round(reference_confidence, 4)
                    if reference_confidence is not None
                    else None
                ),
            },
            "configuration": {
                "sample_seconds": self.sample_seconds,
                "transition_tolerance_seconds": self.transition_tolerance_seconds,
                "accuracy_claim": False,
                "accuracy_note": (
                    "Signal-state metrics are consistency/behaviour metrics, "
                    "not signal-light classification accuracy, because the "
                    "trajectory archives contain no ground-truth signal state."
                ),
            },
            "datasets": dataset_reports,
        }


def report_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Traffic Phase Validation Report",
        "",
        "Signal-state values below are consistency/behaviour metrics, not signal-light accuracy.",
        "",
        "| Dataset | Kind | Period | Cycle conf | Ref error | Phase coverage | Overlap | Cycle consistency | Support ratio | Contradiction ratio | State continuity | Transition consistency | Mean confidence | UNKNOWN rate | RT agreement | RT p95 ms | Mean anomaly | False switch |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["datasets"]:
        dataset = item["dataset"]
        cycle = item["cycle"]
        phase = item["phase"]
        signal = item["signal"]
        realtime = item["realtime"]
        lines.append(
            "| {name} | {kind} | {period} | {cc} | {err} | {coverage} | {overlap} | {consistency} | {support} | {contradiction} | {continuity} | {transition} | {confidence} | {unknown} | {agreement} | {p95} | {anomaly} | {switch} |".format(
                name=dataset["name"],
                kind=dataset["kind"],
                period=cycle.get("period_seconds"),
                cc=cycle.get("confidence"),
                err=cycle.get("reference_error_seconds"),
                coverage=phase.get("phase_coverage"),
                overlap=phase.get("overlap"),
                consistency=phase.get("cycle_consistency"),
                support=phase.get("event_support_ratio"),
                contradiction=phase.get("event_contradictory_ratio"),
                continuity=signal.get("state_continuity"),
                transition=signal.get("transition_consistency"),
                confidence=signal.get("mean_state_confidence"),
                unknown=signal.get("unknown_rate"),
                agreement=realtime.get("batch_realtime_agreement"),
                p95=realtime.get("latency_p95_ms"),
                anomaly=signal.get("anomaly_mean_score"),
                switch=signal.get("false_state_switch_rate"),
            )
        )
    lines.extend(
        [
            "",
            "## Reference pool",
            "",
            f"Reference datasets: {report['reference_pool']['dataset_count']}",
            f"Median reference period: {report['reference_pool']['median_period_seconds']}",
            f"Median reference state confidence: {report['reference_pool']['median_signal_confidence']}",
            "",
            "## Metric interpretation",
            "",
            "Cycle and phase metrics measure temporal and event consistency.",
            "Signal metrics measure continuity, transition behaviour, confidence and UNKNOWN usage.",
            "Realtime agreement compares batch and stateful realtime inference on the same event stream.",
            "Anomaly metrics are indicators; the supplied archives do not provide labelled anomaly intervals or labelled controller states.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(
    report: dict[str, object],
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "validation_report.json"
    markdown_path = output_dir / "validation_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        report_markdown(report),
        encoding="utf-8",
    )
    return json_path, markdown_path
