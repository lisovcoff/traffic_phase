from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from app.core.intersection_config import (
    DEFAULT_INTERSECTION_CONFIG,
    IntersectionConfig,
    SignalHead,
)
from app.core.signal_state_estimator import ApproachState, SignalState


class RendererSignalState(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    RED_YELLOW = "RED_YELLOW"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"


class RendererSignalSource(str, Enum):
    OBSERVED_EVIDENCE = "OBSERVED_EVIDENCE"
    MODELLED_TRANSITION = "MODELLED_TRANSITION"
    INFERRED_MODEL = "INFERRED_MODEL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SignalSectionRenderData:
    id: str
    kind: str
    movement: str
    movement_ids: tuple[str, ...]
    arrows: tuple[str, ...]
    state: RendererSignalState
    confidence: float
    source: RendererSignalSource

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "movement": self.movement,
            "movement_ids": list(self.movement_ids),
            "arrows": list(self.arrows),
            "state": self.state.value,
            "confidence": round(max(0.0, min(1.0, self.confidence)), 4),
            "source": self.source.value,
        }


@dataclass(frozen=True)
class SignalHeadRenderData:
    id: str
    approach: str
    kind: str
    sections: tuple[SignalSectionRenderData, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "approach": self.approach,
            "kind": self.kind,
            "sections": [section.to_dict() for section in self.sections],
        }


@dataclass(frozen=True)
class IntersectionSignalRendererData:
    renderer_version: str
    intersection_id: str
    approaches: tuple[str, ...]
    heads: tuple[SignalHeadRenderData, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "renderer_version": self.renderer_version,
            "intersection_id": self.intersection_id,
            "approaches": list(self.approaches),
            "layout": {
                "approach_count": len(self.approaches),
                "mode": (
                    "radial"
                    if len(self.approaches) >= 4
                    else "compact"
                    if len(self.approaches) == 3
                    else "linear"
                ),
            },
            "heads": [head.to_dict() for head in self.heads],
        }


def _state(value: object) -> RendererSignalState:
    raw = value.value if isinstance(value, Enum) else str(value or "UNKNOWN").upper()
    try:
        return RendererSignalState(raw)
    except ValueError:
        return RendererSignalState.UNKNOWN


def _source(
    state: ApproachState | None,
    *,
    explicit_source: object | None = None,
) -> RendererSignalSource:
    if explicit_source is not None:
        raw = (
            explicit_source.value
            if isinstance(explicit_source, Enum)
            else str(explicit_source)
        )
        try:
            return RendererSignalSource(raw)
        except ValueError:
            pass
    if state is None or state.state is SignalState.UNKNOWN:
        return RendererSignalSource.UNKNOWN
    if state.transition is not None:
        return RendererSignalSource.MODELLED_TRANSITION
    if state.supporting_event_count > 0:
        return RendererSignalSource.OBSERVED_EVIDENCE
    return RendererSignalSource.INFERRED_MODEL


def build_signal_renderer_data(
    config: IntersectionConfig | None = None,
    states: Sequence[ApproachState] = (),
    *,
    state_by_head: Mapping[str, object] | None = None,
    confidence: float | None = None,
    source: RendererSignalSource | str | None = None,
) -> dict[str, object]:
    """Build the frontend contract for physical signal heads.

    This is presentation data only. It does not infer or change signal state.
    The physical structure always comes from IntersectionConfig.
    """
    config = config or DEFAULT_INTERSECTION_CONFIG
    by_head = {item.signal_head_id: item for item in states if item.signal_head_id}
    explicit = state_by_head or {}
    heads: list[SignalHeadRenderData] = []

    for head in config.signal_heads:
        approach_state = by_head.get(head.id)
        raw_state = explicit.get(head.id)
        if raw_state is None:
            raw_state = approach_state.state if approach_state is not None else RendererSignalState.UNKNOWN
        current_state = _state(raw_state)
        section_confidence = (
            float(approach_state.confidence)
            if approach_state is not None
            else float(confidence or 0.0)
        )
        section_source = _source(approach_state, explicit_source=source)
        kind = "additional_section" if head.additional else "main"

        sections = (
            SignalSectionRenderData(
                id=head.id,
                kind=kind,
                movement=", ".join(head.movement_ids),
                movement_ids=head.movement_ids,
                arrows=head.arrows,
                state=current_state,
                confidence=section_confidence,
                source=section_source,
            ),
        )
        heads.append(
            SignalHeadRenderData(
                id=head.id,
                approach=head.approach,
                kind="additional" if head.additional else "main",
                sections=sections,
            )
        )

    return IntersectionSignalRendererData(
        renderer_version="1",
        intersection_id=config.intersection_id,
        approaches=config.approaches,
        heads=tuple(heads),
    ).to_dict()


__all__ = [
    "IntersectionSignalRendererData",
    "RendererSignalSource",
    "RendererSignalState",
    "SignalHeadRenderData",
    "SignalSectionRenderData",
    "build_signal_renderer_data",
]
