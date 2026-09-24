from __future__ import annotations

import pytest

from app.core.intersection_config import (
    DEFAULT_INTERSECTION_CONFIG,
    IntersectionConfig,
    Movement,
    SignalHead,
)
from app.core.intersection_topology import SignalFamily


def test_default_four_way_config_preserves_legacy_topology():
    config = DEFAULT_INTERSECTION_CONFIG

    assert config.intersection_id == "default-four-way"
    assert config.approaches == ("N", "S", "E", "W")
    assert len(config.movements) == 16
    assert {head.id for head in config.primary_signal_heads} == {
        "N_MAIN",
        "S_MAIN",
        "E_MAIN",
        "W_MAIN",
    }
    assert config.additional_signal_heads == ()

    topology = config.to_topology()
    assert topology.to_dict() == {
        "families": [
            {"name": "NS", "approaches": ["N", "S"]},
            {"name": "EW", "approaches": ["E", "W"]},
        ],
        "family_conflicts": [["EW", "NS"]],
        "movement_conflicts": [],
        "movement_compatibilities": [],
    }


def test_additional_arrow_signal_head_is_supported():
    config = IntersectionConfig(
        intersection_id="arrow-crossing",
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        movements=(
            Movement("N->S", "N", "S"),
            Movement("N->E", "N", "E", kind="left"),
            Movement("S->N", "S", "N"),
            Movement("E->W", "E", "W"),
            Movement("W->E", "W", "E"),
        ),
        signal_heads=(
            SignalHead(
                "N_MAIN",
                "N",
                ("N->S",),
            ),
            SignalHead(
                "N_LEFT",
                "N",
                ("N->E",),
                additional=True,
                arrows=("left",),
            ),
            SignalHead(
                "S_MAIN",
                "S",
                ("S->N",),
            ),
            SignalHead("E_MAIN", "E", ("E->W",)),
            SignalHead("W_MAIN", "W", ("W->E",)),
        ),
        family_conflicts=(("NS", "EW"),),
        movement_conflicts=(("N->E", "S->N"),),
    )

    assert config.additional_signal_heads == (
        config.signal_head("N_LEFT"),
    )
    assert config.signal_head("N_LEFT").arrows == ("left",)
    assert config.signal_heads_for_movement("N->E")[0].additional is True
    assert config.movement("N->E").kind == "left"


def test_movement_conflict_and_compatibility_are_mutually_exclusive():
    with pytest.raises(ValueError, match="both conflicting and compatible"):
        IntersectionConfig(
            intersection_id="invalid",
            families=(SignalFamily("NS", ("N", "S")),),
            movements=(
                Movement("N->S", "N", "S"),
                Movement("N->N", "N", "N"),
            ),
            signal_heads=(
                SignalHead("N_MAIN", "N", ("N->S", "N->N")),
            ),
            movement_conflicts=(("N->S", "N->N"),),
            movement_compatibilities=(("N->S", "N->N"),),
        )


def test_invalid_head_reference_is_rejected():
    with pytest.raises(
        ValueError,
        match="references unknown movements",
    ):
        IntersectionConfig(
            intersection_id="invalid-head",
            families=(SignalFamily("NS", ("N", "S")),),
            movements=(
                Movement("N->S", "N", "S"),
            ),
            signal_heads=(
                SignalHead(
                    "N_MAIN",
                    "N",
                    ("N->S", "N->E"),
                ),
            ),
        )


def test_config_round_trip_preserves_additional_section():
    original = IntersectionConfig(
        intersection_id="round-trip",
        families=(
            SignalFamily("NS", ("N", "S")),
            SignalFamily("EW", ("E", "W")),
        ),
        movements=(
            Movement("N->S", "N", "S"),
            Movement("N->E", "N", "E", kind="left"),
            Movement("S->N", "S", "N"),
            Movement("E->W", "E", "W"),
            Movement("W->E", "W", "E"),
        ),
        signal_heads=(
            SignalHead("N_MAIN", "N", ("N->S",)),
            SignalHead(
                "N_LEFT",
                "N",
                ("N->E",),
                additional=True,
                arrows=("left",),
                colors=("RED", "YELLOW", "GREEN"),
            ),
            SignalHead("S_MAIN", "S", ("S->N",)),
            SignalHead("E_MAIN", "E", ("E->W",)),
            SignalHead("W_MAIN", "W", ("W->E",)),
        ),
        family_conflicts=(("NS", "EW"),),
    )

    restored = IntersectionConfig.from_dict(original.to_dict())

    assert restored == original
