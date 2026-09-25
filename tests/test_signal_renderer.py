from __future__ import annotations

import pytest

from app.core.intersection_config import (
    DEFAULT_INTERSECTION_CONFIG,
    IntersectionConfig,
    Movement,
    SignalHead,
)
from app.core.intersection_topology import SignalFamily
from app.core.signal_renderer import (
    RendererSignalSource,
    RendererSignalState,
    build_signal_renderer_data,
)
from app.core.signal_state_estimator import (
    ApproachState,
    SignalState,
    TransitionModel,
    TransitionSemantics,
)
from tests.fixtures.intersection_configs import FIXTURES


@pytest.mark.parametrize("factory", FIXTURES, ids=lambda item: item.__name__)
def test_renderer_contract_is_config_driven(factory):
    fixture = factory()
    payload = build_signal_renderer_data(fixture.config)

    assert payload["renderer_version"] == "1"
    assert payload["intersection_id"] == fixture.config.intersection_id
    assert payload["approaches"] == list(fixture.config.approaches)
    assert payload["layout"]["approach_count"] == len(fixture.config.approaches)
    assert {head["id"] for head in payload["heads"]} == {
        head.id for head in fixture.config.signal_heads
    }

    for head in payload["heads"]:
        configured = fixture.config.signal_head(head["id"])
        assert head["approach"] == configured.approach
        assert head["kind"] == (
            "additional" if configured.additional else "main"
        )
        assert len(head["sections"]) == 1
        section = head["sections"][0]
        assert section["movement"] == ", ".join(configured.movement_ids)
        assert section["movement_ids"] == list(configured.movement_ids)
        assert section["arrows"] == list(configured.arrows)
        assert section["state"] == RendererSignalState.UNKNOWN.value
        assert section["source"] == RendererSignalSource.UNKNOWN.value


def test_renderer_serializes_observed_and_modelled_sources_distinctly():
    config = DEFAULT_INTERSECTION_CONFIG
    observed = ApproachState(
        approach="N",
        signal_head_id="N_MAIN",
        state=SignalState.GREEN,
        confidence=0.83,
        supporting_event_count=4,
    )
    modelled = ApproachState(
        approach="S",
        signal_head_id="S_MAIN",
        state=SignalState.YELLOW,
        confidence=0.71,
        transition=TransitionModel(
            state=SignalState.YELLOW,
            semantics=TransitionSemantics.MODELLED_TRANSITION,
            from_state=SignalState.GREEN,
            to_state=SignalState.RED,
            duration_seconds=3.0,
        ),
    )

    payload = build_signal_renderer_data(
        config,
        (observed, modelled),
        state_by_head={
            "E_MAIN": RendererSignalState.OFF.value,
            "W_MAIN": RendererSignalState.UNKNOWN.value,
        },
    )
    by_id = {
        head["id"]: head["sections"][0]
        for head in payload["heads"]
    }

    assert by_id["N_MAIN"]["state"] == "GREEN"
    assert by_id["N_MAIN"]["source"] == "OBSERVED_EVIDENCE"
    assert by_id["N_MAIN"]["confidence"] == 0.83

    assert by_id["S_MAIN"]["state"] == "YELLOW"
    assert by_id["S_MAIN"]["source"] == "MODELLED_TRANSITION"

    assert by_id["E_MAIN"]["state"] == "OFF"
    assert by_id["W_MAIN"]["state"] == "UNKNOWN"


def _config_with_approaches(count: int) -> IntersectionConfig:
    approaches = tuple(f"A{i}" for i in range(count))
    families = tuple(
        SignalFamily(f"F{i}", (approach,))
        for i, approach in enumerate(approaches)
    )
    movements = tuple(
        Movement(f"{approach}->X", approach, "X")
        for approach in approaches
    )
    heads = tuple(
        SignalHead(f"{approach}_MAIN", approach, (f"{approach}->X",))
        for approach in approaches
    )
    return IntersectionConfig(
        intersection_id=f"layout-{count}",
        families=families,
        movements=movements,
        signal_heads=heads,
    )


@pytest.mark.parametrize(
    ("count", "mode"),
    ((2, "linear"), (3, "compact"), (4, "radial"), (6, "radial")),
)
def test_renderer_layout_mode_adapts_to_approach_count(count, mode):
    payload = build_signal_renderer_data(_config_with_approaches(count))
    assert payload["layout"]["approach_count"] == count
    assert payload["layout"]["mode"] == mode


def test_renderer_has_no_directional_physical_structure():
    fixture = next(
        factory()
        for factory in FIXTURES
        if factory().name == "complex_overlap"
    )
    payload = build_signal_renderer_data(fixture.config)
    assert payload["approaches"] == ["A1", "A2", "B1", "B2"]
    assert {head["approach"] for head in payload["heads"]} == {
        "A1", "A2", "B1", "B2"
    }
