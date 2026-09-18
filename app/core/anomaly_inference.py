from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from app.core.anomaly_profile import APPROACHES, GROUPS, TrafficBaselineProfile, robust_deviation
from app.core.models import EventType, TrajectoryEvent
from app.core.signal_state_estimator import ApproachState, SignalState, SignalStateResult


class TrafficCondition(str, Enum):
    NORMAL_PHASE = "NORMAL_PHASE"
    EXPECTED_RED_SILENCE = "EXPECTED_RED_SILENCE"
    TRAFFIC_ANOMALY = "TRAFFIC_ANOMALY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    CONFLICTING_FLOW = "CONFLICTING_FLOW"


@dataclass(frozen=True)
class AnomalyIndicators:
    flow_deviation: float
    movement_imbalance: float
    unusual_stopping: float
    missing_expected_release: float
    unexpected_conflicting_flow: float
    data_sufficiency: float
    anomaly_score: float
    condition: TrafficCondition
    affected_approaches: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"condition": self.condition.value}


@dataclass(frozen=True)
class AnomalyAwareResult:
    signal: SignalStateResult
    indicators: AnomalyIndicators

    def to_dict(self) -> dict[str, object]:
        return self.signal.to_dict() | {"anomaly": self.indicators.to_dict()}


class AnomalyAwareSignalInference:
    def __init__(
        self,
        phase_model: object,
        baseline: TrafficBaselineProfile | None = None,
        *,
        unknown_confidence: float = 0.35,
        insufficient_threshold: float = 0.18,
    ) -> None:
        self.phase_model = phase_model
        self.baseline = baseline
        self.unknown_confidence = float(unknown_confidence)
        self.insufficient_threshold = float(insufficient_threshold)

    def assess(
        self,
        result: SignalStateResult,
        events: Iterable[TrajectoryEvent],
        *,
        current_time_s: float,
        recent_window_s: float,
        origin_ms: int = 0,
    ) -> AnomalyIndicators:
        if self.baseline is None:
            return AnomalyIndicators(
                0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                TrafficCondition.NORMAL_PHASE, (), ("baseline_profile_unavailable",)
            )

        events = list(events)
        lower_ms = origin_ms + int((current_time_s - recent_window_s) * 1000.0)
        upper_ms = origin_ms + int(current_time_s * 1000.0)
        recent = [event for event in events if lower_ms <= event.timestamp_ms <= upper_ms]

        counts = {
            approach: {"approach": 0.0, "stop": 0.0, "release": 0.0, "crossing": 0.0}
            for approach in APPROACHES
        }
        for event in recent:
            bucket = counts.get(event.approach)
            if bucket is None:
                continue
            if event.event_type == EventType.APPROACH:
                bucket["approach"] += 1
            elif event.event_type == EventType.STOP:
                bucket["stop"] += 1
            elif event.event_type == EventType.RELEASE:
                bucket["release"] += 1
            elif event.event_type == EventType.CROSSING:
                bucket["crossing"] += 1

        total_flow = sum(v["approach"] for v in counts.values())
        data_sufficiency = (
            min(1.0, total_flow / self.baseline.total_flow_median)
            if self.baseline.total_flow_median > 0
            else 1.0
        )
        flow_deviation = robust_deviation(
            total_flow,
            self.baseline.total_flow_median,
            self.baseline.total_flow_mad,
        )

        group_flow = {
            group: sum(counts[a]["approach"] for a in approaches)
            for group, approaches in GROUPS.items()
        }
        total_group_flow = sum(group_flow.values())
        shares = {
            group: (
                group_flow[group] / total_group_flow
                if total_group_flow
                else self.baseline.group_share_median[group]
            )
            for group in GROUPS
        }
        movement_imbalance = max(
            robust_deviation(
                shares[group],
                self.baseline.group_share_median[group],
                self.baseline.group_share_mad[group],
            )
            for group in GROUPS
        )

        phase = next(
            (p for p in getattr(self.phase_model, "phases", ()) if p.phase_id == result.phase_id),
            None,
        )
        active = set(phase.active_approaches) if phase is not None and not result.transition else set()
        active_group = next(
            (group for group, approaches in GROUPS.items() if active.intersection(approaches)),
            None,
        )
        inactive_group = (
            "EW" if active_group == "NS" else "NS"
            if active_group else None
        )

        stopping_scores = []
        for approach in active:
            flow = counts[approach]["approach"]
            if flow <= 0:
                continue
            stop_rate = counts[approach]["stop"] / flow
            stopping_scores.append(
                robust_deviation(
                    stop_rate,
                    self.baseline.approach_stop_rate_median[approach],
                    self.baseline.approach_stop_rate_mad[approach],
                )
            )
        unusual_stopping = sum(stopping_scores) / len(stopping_scores) if stopping_scores else 0.0

        active_release = (
            sum(
                counts[a]["release"] + 0.5 * counts[a]["crossing"]
                for a in GROUPS[active_group]
            )
            if active_group else 0.0
        )
        expected_release = (
            self.baseline.group_release_median.get(active_group, 0.0)
            if active_group else 0.0
        )
        missing_expected_release = (
            max(0.0, min(1.0, 1.0 - active_release / expected_release))
            if active_group and expected_release >= 0.75 and not result.transition
            else 0.0
        )

        conflicting_flow = 0.0
        affected = set()
        if inactive_group and not result.transition:
            inactive_release = sum(
                counts[a]["release"] + 0.5 * counts[a]["crossing"]
                for a in GROUPS[inactive_group]
            )
            expected_inactive = self.baseline.group_release_median.get(inactive_group, 0.0)
            if expected_inactive > 0:
                conflicting_flow = min(
                    1.0,
                    inactive_release / max(expected_inactive * 2.0, 1e-6),
                )
                if conflicting_flow >= 0.65:
                    affected.update(GROUPS[inactive_group])

        anomaly_score = min(
            1.0,
            0.20 * flow_deviation
            + 0.15 * movement_imbalance
            + 0.20 * unusual_stopping
            + 0.25 * missing_expected_release
            + 0.20 * conflicting_flow,
        )

        if data_sufficiency < self.insufficient_threshold:
            condition = TrafficCondition.INSUFFICIENT_DATA
            notes = ("rolling_evidence_below_reference_density",)
        elif conflicting_flow >= 0.78:
            condition = TrafficCondition.CONFLICTING_FLOW
            notes = ("unexpected_opposing_release_density",)
            affected.update(GROUPS[inactive_group] if inactive_group else ())
        elif anomaly_score >= 0.35:
            condition = TrafficCondition.TRAFFIC_ANOMALY
            notes = ("traffic_profile_deviation_detected",)
            affected.update(GROUPS[active_group] if active_group else APPROACHES)
        elif active_group and active_release > 0 and conflicting_flow < 0.2:
            condition = TrafficCondition.EXPECTED_RED_SILENCE
            notes = (f"inactive_group={inactive_group}",)
        else:
            condition = TrafficCondition.NORMAL_PHASE
            notes = ()

        return AnomalyIndicators(
            flow_deviation=round(flow_deviation, 4),
            movement_imbalance=round(movement_imbalance, 4),
            unusual_stopping=round(unusual_stopping, 4),
            missing_expected_release=round(missing_expected_release, 4),
            unexpected_conflicting_flow=round(conflicting_flow, 4),
            data_sufficiency=round(data_sufficiency, 4),
            anomaly_score=round(anomaly_score, 4),
            condition=condition,
            affected_approaches=tuple(sorted(affected)),
            notes=notes,
        )

    def estimate(
        self,
        result: SignalStateResult,
        events: Iterable[TrajectoryEvent],
        *,
        current_time_s: float,
        recent_window_s: float,
        origin_ms: int = 0,
    ) -> AnomalyAwareResult:
        indicators = self.assess(
            result,
            events,
            current_time_s=current_time_s,
            recent_window_s=recent_window_s,
            origin_ms=origin_ms,
        )
        if indicators.condition == TrafficCondition.INSUFFICIENT_DATA:
            return AnomalyAwareResult(
                signal=self._unknown_result(result),
                indicators=indicators,
            )

        penalty = 1.0 - 0.65 * indicators.anomaly_score
        if indicators.condition == TrafficCondition.EXPECTED_RED_SILENCE:
            penalty = 1.0

        if indicators.anomaly_score <= 0:
            signal = result
        else:
            approaches = tuple(
                self._adjust_approach(
                    state,
                    penalty=penalty,
                    affected=state.approach in indicators.affected_approaches,
                )
                for state in result.approaches
            )
            signal = SignalStateResult(
                timestamp_s=result.timestamp_s,
                cycle_phase_s=result.cycle_phase_s,
                phase_id=result.phase_id,
                transition=result.transition,
                phase_confidence=round(result.phase_confidence * penalty, 4),
                traffic_evidence_confidence=round(
                    result.traffic_evidence_confidence * penalty, 4
                ),
                approaches=approaches,
            )

        return AnomalyAwareResult(signal=signal, indicators=indicators)

    def _adjust_approach(
        self,
        state: ApproachState,
        *,
        penalty: float,
        affected: bool,
    ) -> ApproachState:
        confidence = max(0.0, min(1.0, state.confidence * penalty))
        final_state = (
            SignalState.UNKNOWN
            if affected and confidence < self.unknown_confidence
            else state.state
        )
        return ApproachState(
            approach=state.approach,
            state=final_state,
            probability=round(confidence, 4),
            confidence=round(confidence, 4),
            phase_id=state.phase_id,
            phase_confidence=state.phase_confidence,
            traffic_evidence_confidence=state.traffic_evidence_confidence,
            evidence_weight=state.evidence_weight,
            supporting_event_count=state.supporting_event_count,
            contradictory_event_count=state.contradictory_event_count,
        )

    @staticmethod
    def _unknown_result(result: SignalStateResult) -> SignalStateResult:
        return SignalStateResult(
            timestamp_s=result.timestamp_s,
            cycle_phase_s=result.cycle_phase_s,
            phase_id=result.phase_id,
            transition=result.transition,
            phase_confidence=0.0,
            traffic_evidence_confidence=0.0,
            approaches=tuple(
                ApproachState(
                    approach=state.approach,
                    state=SignalState.UNKNOWN,
                    probability=0.0,
                    confidence=0.0,
                    phase_id=state.phase_id,
                    phase_confidence=0.0,
                    traffic_evidence_confidence=0.0,
                    evidence_weight=state.evidence_weight,
                    supporting_event_count=state.supporting_event_count,
                    contradictory_event_count=state.contradictory_event_count,
                )
                for state in result.approaches
            ),
        )


def merge_reference_events(
    *event_sets: Iterable[TrajectoryEvent],
) -> list[TrajectoryEvent]:
    result: list[TrajectoryEvent] = []
    for event_set in event_sets:
        result.extend(event_set)
    return result
