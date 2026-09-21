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
from app.core.reconstruction import (
    SessionReconstruction,
    extract_events_from_trajectories,
    phase_model_ambiguity_reason,
    reconstruct_event_sessions,
)


SCHEMA_VERSION = 3


@dataclass(frozen=True)
class ValidationDataset:
    name: str
    path: str
    intersection_id: str
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


def _phase_metrics_from_model(
    events: Sequence[TrajectoryEvent],
    model: EventPhaseDiscoveryResult,
) -> dict[str, object]:
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
        "origin_timestamp_ms": model.origin_timestamp_ms,
        "phases": [phase.to_dict() for phase in model.phases],
    }


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
    ambiguity = phase_model_ambiguity_reason(model)
    if ambiguity is not None:
        return {
            "status": "ambiguous",
            "error": ambiguity,
            "origin_timestamp_ms": model.origin_timestamp_ms,
        }, None
    return _phase_metrics_from_model(events, model), model


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
        base_result = estimator.estimate(timestamp_s, window_events)
        aware_result = anomaly.estimate(
            base_result,
            window_events,
            current_time_s=timestamp_s,
            recent_window_s=recent_window_seconds,
            origin_ms=origin,
        )
        result = aware_result.signal

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

        anomaly_scores.append(aware_result.indicators.anomaly_score)
        base_states = {
            item.approach: item.state
            for item in base_result.approaches
        }
        aware_states = {
            item.approach: item.state
            for item in result.approaches
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
                batch_time_s = max(
                    0.0,
                    (event.timestamp_ms - origin) / 1000.0,
                )
                batch = batch_estimator.estimate(
                    batch_time_s,
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


def _events_for_reconstruction(
    event_index: _EventWindowIndex,
    reconstruction: SessionReconstruction,
) -> tuple[TrajectoryEvent, ...]:
    return event_index.between(
        reconstruction.start_timestamp_ms,
        reconstruction.end_timestamp_ms,
    )


def _cycle_metrics_from_reconstruction(
    reconstruction: SessionReconstruction,
    reference_period: float | None,
) -> dict[str, object]:
    if reconstruction.cycle is None:
        return {
            "status": reconstruction.status,
            "error": reconstruction.error_reason,
            "period_seconds": None,
            "confidence": 0.0,
            "reference_period_seconds": reference_period,
            "reference_error_seconds": None,
        }
    result = reconstruction.cycle
    candidate = (
        result.estimate.candidate_periods[0]
        if result.estimate.candidate_periods
        else None
    )
    period = float(result.estimate.cycle_seconds)
    return {
        "status": "ok",
        "period_seconds": period,
        "confidence": result.estimate.confidence,
        "stability": candidate.stability if candidate else None,
        "repetitions": candidate.repetitions if candidate else None,
        "candidate_count": len(result.estimate.candidate_periods),
        "reference_period_seconds": reference_period,
        "reference_error_seconds": (
            round(abs(period - reference_period), 4)
            if reference_period is not None
            else None
        ),
    }


def _median_metric(
    reports: Sequence[dict[str, object]],
    key: str,
) -> float | None:
    values = [
        float(report[key])
        for report in reports
        if report.get(key) is not None
    ]
    return _median(values)


def _sum_metric(
    reports: Sequence[dict[str, object]],
    key: str,
) -> int:
    return sum(
        int(report.get(key) or 0)
        for report in reports
    )


def _nearest_reference_period(
    period: float | None,
    options: Sequence[float],
) -> float | None:
    if not options:
        return None
    if period is None:
        return _median(options)
    return min(
        (float(value) for value in options),
        key=lambda value: abs(value - period),
    )


def _aggregate_cycle_metrics(
    reports: Sequence[dict[str, object]],
    *,
    reference_options: Sequence[float],
    session_count: int,
    regime_count: int,
    ambiguous_count: int,
) -> dict[str, object]:
    successful = [
        report
        for report in reports
        if report.get("period_seconds") is not None
    ]
    periods = [
        float(report["period_seconds"])
        for report in successful
    ]
    period = _median(periods)
    reference_period = _nearest_reference_period(
        period,
        reference_options,
    )
    return {
        "status": "ok" if successful else "error",
        "period_seconds": period,
        "periods_seconds": [round(item, 4) for item in periods],
        "confidence": _median_metric(successful, "confidence"),
        "stability": _median_metric(successful, "stability"),
        "repetitions": _sum_metric(successful, "repetitions"),
        "candidate_count": _sum_metric(successful, "candidate_count"),
        "reference_period_seconds": reference_period,
        "reference_period_options_seconds": [
            round(float(value), 4)
            for value in reference_options
        ],
        "reference_error_seconds": (
            round(abs(float(period) - reference_period), 4)
            if period is not None and reference_period is not None
            else None
        ),
        "session_count": session_count,
        "regime_count": regime_count,
        "ambiguous_regime_count": ambiguous_count,
    }


def _aggregate_phase_metrics(
    reports: Sequence[dict[str, object]],
    *,
    ambiguous_count: int,
) -> dict[str, object]:
    successful = [
        report
        for report in reports
        if report.get("status") == "ok"
    ]
    if not successful:
        return {
            "status": "ambiguous" if ambiguous_count else "not_run",
            "phase_count": None,
            "phase_coverage": None,
            "overlap": None,
            "cycle_consistency": None,
            "event_support_count": 0,
            "event_contradictory_count": 0,
            "event_support_ratio": None,
            "event_contradictory_ratio": None,
            "model_count": 0,
            "ambiguous_regime_count": ambiguous_count,
            "phases": None,
            "origin_timestamp_ms": None,
        }

    support = _sum_metric(successful, "event_support_count")
    contradiction = _sum_metric(
        successful,
        "event_contradictory_count",
    )
    total = support + contradiction
    return {
        "status": "ok",
        "phase_count": _median_metric(successful, "phase_count"),
        "phase_coverage": _median_metric(successful, "phase_coverage"),
        "overlap": _median_metric(successful, "overlap"),
        "cycle_consistency": _median_metric(
            successful,
            "cycle_consistency",
        ),
        "event_support_count": support,
        "event_contradictory_count": contradiction,
        "event_support_ratio": (
            round(support / total, 4) if total else None
        ),
        "event_contradictory_ratio": (
            round(contradiction / total, 4) if total else None
        ),
        "model_count": len(successful),
        "ambiguous_regime_count": ambiguous_count,
        # Origins and physical phase intervals remain in the per-regime
        # records below. They are intentionally never averaged together.
        "phases": None,
        "origin_timestamp_ms": None,
    }


def _aggregate_signal_metrics(
    reports: Sequence[dict[str, object]],
) -> dict[str, object]:
    successful = [
        report
        for report in reports
        if report.get("status") == "ok"
    ]
    if not successful:
        return {"status": "not_run"}
    return {
        "status": "ok",
        "sample_count": _sum_metric(successful, "sample_count"),
        "state_continuity": _median_metric(
            successful,
            "state_continuity",
        ),
        "transition_count": _sum_metric(
            successful,
            "transition_count",
        ),
        "transition_consistency": _median_metric(
            successful,
            "transition_consistency",
        ),
        "mean_state_confidence": _median_metric(
            successful,
            "mean_state_confidence",
        ),
        "unknown_rate": _median_metric(successful, "unknown_rate"),
        "anomaly_mean_score": _median_metric(
            successful,
            "anomaly_mean_score",
        ),
        "anomaly_max_score": max(
            (
                float(report["anomaly_max_score"])
                for report in successful
                if report.get("anomaly_max_score") is not None
            ),
            default=None,
        ),
        "false_state_switch_rate": _median_metric(
            successful,
            "false_state_switch_rate",
        ),
        "regime_metric_count": len(successful),
    }


def _aggregate_realtime_metrics(
    reports: Sequence[dict[str, object]],
) -> dict[str, object]:
    successful = [
        report
        for report in reports
        if report.get("status") == "ok"
    ]
    if not successful:
        return {"status": "not_run"}
    comparisons = _sum_metric(
        successful,
        "agreement_comparisons",
    )
    weighted_agreements = sum(
        float(report.get("batch_realtime_agreement") or 0.0)
        * int(report.get("agreement_comparisons") or 0)
        for report in successful
    )
    return {
        "status": "ok",
        "event_count": _sum_metric(successful, "event_count"),
        "latency_mean_ms": _median_metric(
            successful,
            "latency_mean_ms",
        ),
        "latency_p95_ms": _median_metric(
            successful,
            "latency_p95_ms",
        ),
        "peak_tracemalloc_bytes": max(
            (
                int(report.get("peak_tracemalloc_bytes") or 0)
                for report in successful
            ),
            default=0,
        ),
        "max_rolling_buffer_events": max(
            (
                int(report.get("max_rolling_buffer_events") or 0)
                for report in successful
            ),
            default=0,
        ),
        "batch_realtime_agreement": (
            round(weighted_agreements / comparisons, 4)
            if comparisons
            else None
        ),
        "agreement_comparisons": comparisons,
        "regime_metric_count": len(successful),
    }


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
        if any(not dataset.intersection_id for dataset in datasets):
            raise ValueError(
                "every validation dataset requires intersection_id"
            )
        if sample_seconds <= 0:
            raise ValueError("sample_seconds must be positive")
        self.datasets = tuple(datasets)
        self.sample_seconds = float(sample_seconds)
        self.transition_tolerance_seconds = float(
            transition_tolerance_seconds
        )
        self.progress = progress or (lambda _message: None)

    def _reconstruct(
        self,
        events: Sequence[TrajectoryEvent],
    ) -> tuple[SessionReconstruction, ...]:
        # This is intentionally the same authoritative production path used
        # by archive analysis: physical sessions first, stable regimes next.
        return reconstruct_event_sessions(events)

    def run(self) -> dict[str, object]:
        reference_names: dict[str, list[str]] = {}
        reference_period_options: dict[str, list[float]] = {}
        reference_profiles: dict[
            str,
            list[TrafficBaselineProfile],
        ] = {}

        reference_datasets = [
            dataset
            for dataset in self.datasets
            if dataset.kind == "reference"
        ]

        for ref_index, dataset in enumerate(
            reference_datasets,
            start=1,
        ):
            self.progress(
                f"preparing reference {ref_index}/"
                f"{len(reference_datasets)}: "
                f"{dataset.name} [{dataset.intersection_id}]"
            )
            reference_names.setdefault(
                dataset.intersection_id,
                [],
            ).append(dataset.name)
            try:
                events = load_events(Path(dataset.path))
                reconstructions = self._reconstruct(events)
                index = _EventWindowIndex.build(events)
                for reconstruction in reconstructions:
                    if reconstruction.cycle is not None:
                        reference_period_options.setdefault(
                            dataset.intersection_id,
                            [],
                        ).append(
                            float(
                                reconstruction.cycle.estimate.cycle_seconds
                            )
                        )
                    regime_events = _events_for_reconstruction(
                        index,
                        reconstruction,
                    )
                    if not regime_events:
                        continue
                    reference_profiles.setdefault(
                        dataset.intersection_id,
                        [],
                    ).append(
                        TrafficBaselineProfile.from_events(
                            _rebase_events(
                                regime_events,
                                reconstruction.start_timestamp_ms,
                            ),
                            window_seconds=12.0,
                            source=(
                                f"reference:{dataset.name}:"
                                f"session{reconstruction.session_index}:"
                                f"regime{reconstruction.regime_index}"
                            ),
                        )
                    )
            except Exception as exc:
                self.progress(
                    f"reference preparation error: "
                    f"{dataset.name}: {exc}"
                )

        baselines: dict[str, TrafficBaselineProfile] = {}
        reference_pools: dict[str, dict[str, object]] = {}
        for intersection_id, names in reference_names.items():
            periods = sorted(
                float(value)
                for value in reference_period_options.get(
                    intersection_id,
                    [],
                )
            )
            profiles = reference_profiles.get(
                intersection_id,
                [],
            )
            if profiles:
                baselines[
                    intersection_id
                ] = TrafficBaselineProfile.aggregate(
                    profiles,
                    source=(
                        "validation_reference_pool:"
                        f"{intersection_id}"
                    ),
                )
            reference_pools[intersection_id] = {
                "dataset_count": len(names),
                "dataset_names": list(names),
                "periods_seconds": [
                    round(value, 4)
                    for value in periods
                ],
                "median_period_seconds": _median(periods),
                "median_signal_confidence": None,
            }
            self.progress(
                "reference baseline ready: "
                f"intersection={intersection_id}, "
                f"profiles={len(profiles)}, "
                f"periods={reference_pools[intersection_id]['periods_seconds']}"
            )

        dataset_reports: list[dict[str, object]] = []
        total_datasets = len(self.datasets)

        for dataset_index, dataset in enumerate(
            self.datasets,
            start=1,
        ):
            self.progress(
                f"validating dataset {dataset_index}/{total_datasets}: "
                f"{dataset.name} [{dataset.intersection_id}]"
            )
            events: list[TrajectoryEvent] = []
            regime_reports: list[dict[str, object]] = []
            cycle_reports: list[dict[str, object]] = []
            phase_reports: list[dict[str, object]] = []
            signal_reports: list[dict[str, object]] = []
            realtime_reports: list[dict[str, object]] = []
            reconstruction_error: str | None = None

            options = reference_period_options.get(
                dataset.intersection_id,
                [],
            )
            baseline = baselines.get(
                dataset.intersection_id,
            )
            matching_reference_names = reference_names.get(
                dataset.intersection_id,
                [],
            )

            try:
                events = load_events(Path(dataset.path))
                event_index = _EventWindowIndex.build(events)
                reconstructions = self._reconstruct(events)
                for reconstruction in reconstructions:
                    regime_events = _events_for_reconstruction(
                        event_index,
                        reconstruction,
                    )
                    own_period = (
                        float(
                            reconstruction.cycle.estimate.cycle_seconds
                        )
                        if reconstruction.cycle is not None
                        else None
                    )
                    nearest_reference = _nearest_reference_period(
                        own_period,
                        options,
                    )
                    cycle_metrics = (
                        _cycle_metrics_from_reconstruction(
                            reconstruction,
                            nearest_reference,
                        )
                    )
                    cycle_reports.append(cycle_metrics)

                    if reconstruction.status == "ambiguous":
                        phase_metrics = {
                            "status": "ambiguous",
                            "error": reconstruction.error_reason,
                            "phase_count": None,
                            "origin_timestamp_ms": None,
                            "phases": None,
                        }
                        signal_metrics = {"status": "not_run"}
                        realtime_metrics = {"status": "not_run"}
                    elif reconstruction.phase_model is not None:
                        phase_metrics = _phase_metrics_from_model(
                            regime_events,
                            reconstruction.phase_model,
                        )
                        signal_metrics = validate_signal(
                            regime_events,
                            reconstruction.phase_model,
                            sample_seconds=self.sample_seconds,
                            transition_tolerance_seconds=(
                                self.transition_tolerance_seconds
                            ),
                            baseline=baseline,
                        )
                        realtime_metrics = validate_realtime(
                            regime_events,
                            reconstruction.phase_model,
                        )
                    else:
                        phase_metrics = {
                            "status": reconstruction.status,
                            "error": reconstruction.error_reason,
                            "phase_count": None,
                            "origin_timestamp_ms": None,
                            "phases": None,
                        }
                        signal_metrics = {"status": "not_run"}
                        realtime_metrics = {"status": "not_run"}

                    phase_reports.append(phase_metrics)
                    signal_reports.append(signal_metrics)
                    realtime_reports.append(realtime_metrics)
                    regime_reports.append(
                        {
                            "session_index": (
                                reconstruction.session_index
                            ),
                            "regime_index": (
                                reconstruction.regime_index
                            ),
                            "regime_count": (
                                reconstruction.regime_count
                            ),
                            "start_timestamp_ms": (
                                reconstruction.start_timestamp_ms
                            ),
                            "end_timestamp_ms": (
                                reconstruction.end_timestamp_ms
                            ),
                            "duration_s": reconstruction.duration_s,
                            "status": reconstruction.status,
                            "confidence": reconstruction.confidence,
                            "error_reason": (
                                reconstruction.error_reason
                            ),
                            "rolling_period_seconds": (
                                reconstruction.rolling_period_seconds
                            ),
                            "rolling_window_count": (
                                reconstruction.rolling_window_count
                            ),
                            "event_count": len(regime_events),
                            "cycle": cycle_metrics,
                            "phase": phase_metrics,
                            "signal": signal_metrics,
                            "realtime": realtime_metrics,
                        }
                    )
            except Exception as exc:
                reconstruction_error = str(exc)

            session_count = len(
                {
                    item["session_index"]
                    for item in regime_reports
                }
            )
            ambiguous_count = sum(
                item["status"] == "ambiguous"
                for item in regime_reports
            )
            cycle_metrics = _aggregate_cycle_metrics(
                cycle_reports,
                reference_options=options,
                session_count=session_count,
                regime_count=len(regime_reports),
                ambiguous_count=ambiguous_count,
            )
            if reconstruction_error is not None:
                cycle_metrics = {
                    "status": "error",
                    "error": reconstruction_error,
                    "period_seconds": None,
                    "reference_period_seconds": (
                        _median(options)
                    ),
                    "reference_error_seconds": None,
                    "session_count": 0,
                    "regime_count": 0,
                    "ambiguous_regime_count": 0,
                }

            phase_metrics = _aggregate_phase_metrics(
                phase_reports,
                ambiguous_count=ambiguous_count,
            )
            signal_metrics = _aggregate_signal_metrics(
                signal_reports
            )
            realtime_metrics = _aggregate_realtime_metrics(
                realtime_reports
            )
            reference_period = cycle_metrics.get(
                "reference_period_seconds"
            )

            dataset_reports.append(
                {
                    "dataset": dataset.to_dict(),
                    "reference": {
                        "intersection_id": dataset.intersection_id,
                        "dataset_names": list(
                            matching_reference_names
                        ),
                        "period_seconds": reference_period,
                        "period_options_seconds": [
                            round(float(value), 4)
                            for value in options
                        ],
                        "baseline_source": (
                            baseline.source
                            if baseline is not None
                            else None
                        ),
                    },
                    "event_count": len(events),
                    "session_count": session_count,
                    "regime_count": len(regime_reports),
                    "ambiguous_regime_count": ambiguous_count,
                    "cycle": cycle_metrics,
                    "phase": phase_metrics,
                    "signal": signal_metrics,
                    "realtime": realtime_metrics,
                    "regimes": regime_reports,
                }
            )
            self.progress(
                f"finished dataset {dataset_index}/{total_datasets}: "
                f"{dataset.name} events={len(events)} "
                f"sessions={session_count} "
                f"regimes={len(regime_reports)} "
                f"ambiguous={ambiguous_count}"
            )

        for intersection_id, pool in reference_pools.items():
            confidence_values = [
                float(item["signal"]["mean_state_confidence"])
                for item in dataset_reports
                if item["dataset"]["kind"] == "reference"
                and item["dataset"]["intersection_id"] == intersection_id
                and item["signal"].get(
                    "mean_state_confidence"
                ) is not None
            ]
            pool["median_signal_confidence"] = (
                _median(confidence_values)
            )

        for item in dataset_reports:
            signal_metrics = item["signal"]
            intersection_id = item["dataset"][
                "intersection_id"
            ]
            reference_confidence = reference_pools.get(
                intersection_id,
                {},
            ).get("median_signal_confidence")
            if (
                reference_confidence is not None
                and signal_metrics.get(
                    "mean_state_confidence"
                ) is not None
            ):
                signal_metrics[
                    "reference_confidence_delta"
                ] = round(
                    float(reference_confidence)
                    - float(
                        signal_metrics[
                            "mean_state_confidence"
                        ]
                    ),
                    4,
                )
            else:
                signal_metrics[
                    "reference_confidence_delta"
                ] = None

        return {
            "schema_version": SCHEMA_VERSION,
            "reference_summary": {
                "dataset_count": len(reference_datasets),
                "intersection_count": len(reference_pools),
            },
            "reference_pools": reference_pools,
            "configuration": {
                "sample_seconds": self.sample_seconds,
                "transition_tolerance_seconds": (
                    self.transition_tolerance_seconds
                ),
                "accuracy_claim": False,
                "accuracy_note": (
                    "Signal-state metrics are consistency/behaviour "
                    "metrics, not signal-light classification accuracy, "
                    "because the trajectory archives contain no "
                    "ground-truth signal state."
                ),
                "reconstruction_path": (
                    "production session/regime reconstruction"
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
        "| Dataset | Intersection | Kind | Sessions | Regimes | Ambiguous | Reference | Period | Ref period | Ref error | Phase coverage | Overlap | Cycle consistency | Support ratio | Contradiction ratio | State continuity | Transition consistency | Mean confidence | UNKNOWN rate | RT agreement | RT p95 ms | Mean anomaly | False switch |",
        "|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["datasets"]:
        dataset = item["dataset"]
        reference = item.get("reference", {})
        cycle = item["cycle"]
        phase = item["phase"]
        signal = item["signal"]
        realtime = item["realtime"]
        reference_names = ", ".join(reference.get("dataset_names", [])) or "-"
        lines.append(
            "| {name} | {intersection} | {kind} | {sessions} | {regimes} | {ambiguous} | {reference} | {period} | {ref_period} | {err} | {coverage} | {overlap} | {consistency} | {support} | {contradiction} | {continuity} | {transition} | {confidence} | {unknown} | {agreement} | {p95} | {anomaly} | {switch} |".format(
                name=dataset["name"],
                intersection=dataset["intersection_id"],
                kind=dataset["kind"],
                sessions=item.get("session_count", 0),
                regimes=item.get("regime_count", 0),
                ambiguous=item.get("ambiguous_regime_count", 0),
                reference=reference_names,
                period=cycle.get("period_seconds"),
                ref_period=cycle.get("reference_period_seconds"),
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

    summary = report.get("reference_summary", {})
    lines.extend(
        [
            "",
            "## Reference pools by intersection",
            "",
            f"Reference datasets: {summary.get('dataset_count', 0)}",
            f"Intersections with references: {summary.get('intersection_count', 0)}",
            "",
        ]
    )
    for intersection_id, pool in report.get("reference_pools", {}).items():
        names = ", ".join(pool.get("dataset_names", [])) or "-"
        lines.extend(
            [
                f"### {intersection_id}",
                "",
                f"Reference datasets: {names}",
                f"Reference regime periods: {pool.get('periods_seconds', [])}",
                f"Median reference period: {pool.get('median_period_seconds')}",
                f"Median reference state confidence: {pool.get('median_signal_confidence')}",
                "",
            ]
        )

    lines.extend(
        [
            "## Metric interpretation",
            "",
            "Cycle and phase metrics measure temporal and event consistency.",
            "Long gaps create independent sessions; confirmed rolling period changes create independent regimes.",
            "Phase origins and physical phase intervals are reported per regime and are never averaged across regimes.",
            "A minimum-duration phase with weak/conflicting evidence is reported as ambiguous rather than as a physical phase.",
            "Reference comparisons and anomaly baselines are scoped to the same physical intersection.",
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
