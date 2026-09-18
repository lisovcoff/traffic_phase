from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc
from typing import Sequence
import zipfile

from app.core.anomaly_inference import AnomalyAwareSignalInference
from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.event_cycle_estimator import EventCycleEstimate, estimate_event_cycle
from app.core.event_phase_discovery import EventPhase, EventPhaseDiscovery, EventPhaseDiscoveryResult
from app.core.models import EventType, TrajectoryEvent
from app.core.preprocessing import load_trajectory_file
from app.core.realtime_inference import RealtimeSignalInferenceEngine
from app.core.signal_state_estimator import SignalState, SignalStateEstimator
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import build_trajectory_geometry


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
        trajectories = load_trajectory_file(path)
        events: list[TrajectoryEvent] = []
        for trajectory in trajectories:
            events.extend(
                extract_trajectory_events(
                    trajectory,
                    build_trajectory_geometry(trajectory.to_record()),
                )
            )
        return events

    if path.suffix.lower() != ".zip":
        raise ValueError(f"unsupported validation input: {path}")

    events: list[TrajectoryEvent] = []
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.lower().endswith(".json"):
                continue
            with archive.open(member) as handle:
                payload = json.load(handle)
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                encoding="utf-8",
                delete=False,
            ) as tmp:
                json.dump(payload, tmp)
                temporary_path = Path(tmp.name)
            try:
                trajectories = load_trajectory_file(temporary_path)
                for trajectory in trajectories:
                    events.extend(
                        extract_trajectory_events(
                            trajectory,
                            build_trajectory_geometry(trajectory.to_record()),
                        )
                    )
            finally:
                temporary_path.unlink(missing_ok=True)
    return events


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
    origin_ms = min(event.timestamp_ms for event in selected)
    supporting = 0.0
    total = 0.0
    groups = {"N": "NS", "S": "NS", "E": "EW", "W": "EW"}
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
        elif groups[event.approach] == "NS" and {"N", "S"}.issubset(expected):
            supporting += 0.0
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
) -> tuple[int, list[float]]:
    origin = min(event.timestamp_ms for event in events)
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
    origin, times = _sample_times(events, sample_seconds)
    estimator = SignalStateEstimator(
        phase_model,
        event_origin_ms=origin,
    )
    anomaly = AnomalyAwareSignalInference(phase_model, baseline)
    results = [
        estimator.estimate(timestamp_s, events)
        for timestamp_s in times
    ]
    total_states = 0
    unknown_states = 0
    confidence_values: list[float] = []
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
    for result in results:
        for state in result.approaches:
            total_states += 1
            unknown_states += state.state == SignalState.UNKNOWN
            confidence_values.append(state.confidence)

    for previous, current in zip(results, results[1:]):
        previous_states = {
            state.approach: state.state
            for state in previous.approaches
        }
        current_states = {
            state.approach: state.state
            for state in current.approaches
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
                        current.cycle_phase_s,
                        boundary,
                        phase_model.cycle_seconds,
                    )
                    for boundary in boundaries
                ) if boundaries else phase_model.cycle_seconds
                transition_consistent += distance <= transition_tolerance_seconds

    anomaly_results = [
        anomaly.estimate(
            result,
            events,
            current_time_s=times[index],
            recent_window_s=12.0,
            origin_ms=origin,
        )
        for index, result in enumerate(results)
    ]
    anomaly_scores = [
        item.indicators.anomaly_score
        for item in anomaly_results
    ]
    conditions: dict[str, int] = {}
    false_switches = 0
    state_comparisons = 0
    for base_result, aware_result in zip(results, anomaly_results):
        base_states = {
            item.approach: item.state
            for item in base_result.approaches
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

    mean_confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values
        else None
    )
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
    origin = min(event.timestamp_ms for event in events)
    ordered = sorted(
        events,
        key=lambda event: (
            event.timestamp_ms,
            event.event_type.value,
            event.approach,
            event.movement,
        ),
    )
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

    tracemalloc.start()
    for index, event in enumerate(ordered):
        start = time.perf_counter_ns()
        snapshot = engine.ingest_event(event)
        latencies.append((time.perf_counter_ns() - start) / 1_000_000.0)
        max_buffer = max(max_buffer, snapshot.buffer_event_count)

        if index % step == 0 or index == len(ordered) - 1:
            prefix = [
                item for item in ordered
                if item.timestamp_ms <= event.timestamp_ms
            ]
            batch = SignalStateEstimator(
                phase_model,
                event_origin_ms=origin,
            ).estimate(
                (event.timestamp_ms - origin) / 1000.0,
                prefix,
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


class ValidationRunner:
    def __init__(
        self,
        datasets: Sequence[ValidationDataset],
        *,
        sample_seconds: float = 1.0,
        transition_tolerance_seconds: float = 3.0,
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

    def run(self) -> dict[str, object]:
        loaded: dict[str, tuple[ValidationDataset, list[TrajectoryEvent], dict[str, object], EventCycleEstimate | None]] = {}
        reference_cycles: list[float] = []

        for dataset in self.datasets:
            try:
                events = load_events(Path(dataset.path))
                cycle_metrics, cycle_estimate = validate_cycle(events, None)
                loaded[dataset.name] = (
                    dataset,
                    events,
                    cycle_metrics,
                    cycle_estimate,
                )
                if dataset.kind == "reference" and cycle_estimate is not None:
                    reference_cycles.append(
                        cycle_estimate.estimate.cycle_seconds
                    )
            except Exception as exc:
                loaded[dataset.name] = (
                    dataset,
                    [],
                    {"status": "error", "error": str(exc)},
                    None,
                )

        reference_period = (
            round(statistics.median(reference_cycles), 4)
            if reference_cycles
            else None
        )

        reference_events = [
            event
            for dataset, events, _, _ in loaded.values()
            if dataset.kind == "reference"
            for event in events
        ]
        baseline = None
        if reference_events:
            try:
                baseline = TrafficBaselineProfile.from_events(
                    reference_events,
                    window_seconds=12.0,
                    source="validation_reference_pool",
                )
            except Exception:
                baseline = None

        reference_confidence_values: list[float] = []
        phase_cache: dict[str, EventPhaseDiscoveryResult] = {}
        for dataset, events, _, cycle_estimate in loaded.values():
            if dataset.kind != "reference" or cycle_estimate is None:
                continue
            _, phase_model = validate_phase(
                events,
                cycle_estimate.estimate.cycle_seconds,
            )
            if phase_model is None:
                continue
            phase_cache[dataset.name] = phase_model
            signal_metrics = validate_signal(
                events,
                phase_model,
                sample_seconds=self.sample_seconds,
                transition_tolerance_seconds=self.transition_tolerance_seconds,
                baseline=None,
            )
            value = signal_metrics.get("mean_state_confidence")
            if value is not None:
                reference_confidence_values.append(float(value))

        reference_confidence = (
            statistics.median(reference_confidence_values)
            if reference_confidence_values
            else None
        )

        dataset_reports = []
        for dataset, events, cycle_metrics, cycle_estimate in loaded.values():
            cycle_metrics = dict(cycle_metrics)
            if cycle_estimate is not None:
                if dataset.kind != "reference" and reference_period is not None:
                    cycle_metrics["reference_period_seconds"] = reference_period
                    cycle_metrics["reference_error_seconds"] = round(
                        abs(
                            cycle_estimate.estimate.cycle_seconds
                            - reference_period
                        ),
                        4,
                    )

            phase_metrics: dict[str, object] = {"status": "not_run"}
            signal_metrics: dict[str, object] = {"status": "not_run"}
            realtime_metrics: dict[str, object] = {"status": "not_run"}

            if cycle_estimate is not None and events:
                phase_metrics, phase_model = validate_phase(
                    events,
                    cycle_estimate.estimate.cycle_seconds,
                )
                if phase_model is not None:
                    phase_cache[dataset.name] = phase_model
                    signal_metrics = validate_signal(
                        events,
                        phase_model,
                        sample_seconds=self.sample_seconds,
                        transition_tolerance_seconds=self.transition_tolerance_seconds,
                        baseline=baseline,
                    )
                    realtime_metrics = validate_realtime(
                        events,
                        phase_model,
                    )

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

        return {
            "schema_version": SCHEMA_VERSION,
            "reference_pool": {
                "dataset_count": sum(
                    1 for dataset in self.datasets
                    if dataset.kind == "reference"
                ),
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
