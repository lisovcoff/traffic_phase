from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.core.intersection_topology import (
    IntersectionTopology,
    SignalFamily,
)


SIGNAL_COLORS = frozenset({"RED", "YELLOW", "GREEN"})
ARROW_DIRECTIONS = frozenset({"left", "straight", "right", "uturn"})


def _normalize_pair(left: str, right: str) -> tuple[str, str]:
    first = str(left).strip()
    second = str(right).strip()
    return tuple(sorted((first, second)))


@dataclass(frozen=True)
class Movement:
    """A single logical vehicle movement through the intersection."""

    id: str
    approach: str
    destination: str
    kind: str = "through"

    def __post_init__(self) -> None:
        movement_id = str(self.id).strip()
        approach = str(self.approach).strip()
        destination = str(self.destination).strip()
        kind = str(self.kind).strip().lower()

        if not movement_id:
            raise ValueError("movement id must not be empty")
        if not approach:
            raise ValueError("movement approach must not be empty")
        if not destination:
            raise ValueError("movement destination must not be empty")
        if not kind:
            raise ValueError("movement kind must not be empty")

        object.__setattr__(self, "id", movement_id)
        object.__setattr__(self, "approach", approach)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "kind", kind)

    @classmethod
    def from_id(
        cls,
        movement_id: str,
        *,
        kind: str = "through",
    ) -> "Movement":
        value = str(movement_id).strip()
        if "->" not in value:
            raise ValueError(
                "movement id must use '<approach>-><destination>' format"
            )
        approach, destination = value.split("->", 1)
        return cls(
            id=value,
            approach=approach,
            destination=destination,
            kind=kind,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "approach": self.approach,
            "destination": self.destination,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class SignalHead:
    """A physical signal group, including optional additional sections."""

    id: str
    approach: str
    movement_ids: tuple[str, ...]
    additional: bool = False
    arrows: tuple[str, ...] = ()
    colors: tuple[str, ...] = ("RED", "YELLOW", "GREEN")

    def __post_init__(self) -> None:
        head_id = str(self.id).strip()
        approach = str(self.approach).strip()
        movement_ids = tuple(
            dict.fromkeys(str(value).strip() for value in self.movement_ids)
        )
        arrows = tuple(
            dict.fromkeys(str(value).strip().lower() for value in self.arrows)
        )
        colors = tuple(
            dict.fromkeys(str(value).strip().upper() for value in self.colors)
        )

        if not head_id:
            raise ValueError("signal head id must not be empty")
        if not approach:
            raise ValueError("signal head approach must not be empty")
        if not movement_ids:
            raise ValueError("signal head must control at least one movement")
        if any(not value for value in movement_ids):
            raise ValueError("signal head movement ids must not be empty")
        if any(value not in ARROW_DIRECTIONS for value in arrows):
            raise ValueError(
                "signal head arrows must be one of: "
                + ", ".join(sorted(ARROW_DIRECTIONS))
            )
        if not colors:
            raise ValueError("signal head must support at least one color")
        if any(value not in SIGNAL_COLORS for value in colors):
            raise ValueError(
                "signal head colors must be a subset of RED/YELLOW/GREEN"
            )

        object.__setattr__(self, "id", head_id)
        object.__setattr__(self, "approach", approach)
        object.__setattr__(self, "movement_ids", movement_ids)
        object.__setattr__(self, "additional", bool(self.additional))
        object.__setattr__(self, "arrows", arrows)
        object.__setattr__(self, "colors", colors)

    @property
    def is_primary(self) -> bool:
        return not self.additional

    def controls(self, movement_id: str) -> bool:
        return str(movement_id).strip() in self.movement_ids

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "approach": self.approach,
            "movement_ids": list(self.movement_ids),
            "additional": self.additional,
            "arrows": list(self.arrows),
            "colors": list(self.colors),
        }


@dataclass(frozen=True)
class IntersectionConfig:
    """Complete declarative configuration of one signalized intersection.

    IntersectionTopology remains the compatibility layer consumed by the
    existing inference engine. This configuration adds movement and signal-head
    semantics without changing that engine in this step.
    """

    intersection_id: str
    families: tuple[SignalFamily, ...]
    movements: tuple[Movement, ...]
    signal_heads: tuple[SignalHead, ...]
    family_conflicts: tuple[tuple[str, str], ...] = ()
    movement_conflicts: tuple[tuple[str, str], ...] = ()
    movement_compatibilities: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        intersection_id = str(self.intersection_id).strip()
        if not intersection_id:
            raise ValueError("intersection_id must not be empty")
        if not self.families:
            raise ValueError("intersection config requires signal families")
        if not self.movements:
            raise ValueError("intersection config requires movements")
        if not self.signal_heads:
            raise ValueError("intersection config requires signal heads")

        family_names = [str(item.name).strip() for item in self.families]
        if any(not name for name in family_names):
            raise ValueError("signal family names must not be empty")
        if len(set(family_names)) != len(family_names):
            raise ValueError("signal family names must be unique")

        approaches = {
            str(approach).strip()
            for family in self.families
            for approach in family.approaches
        }
        if any(not approach for approach in approaches):
            raise ValueError("approach names must not be empty")

        movements_by_id = {}
        for movement in self.movements:
            if movement.id in movements_by_id:
                raise ValueError(
                    f"movement ids must be unique: {movement.id}"
                )
            movements_by_id[movement.id] = movement
            if movement.approach not in approaches:
                raise ValueError(
                    f"movement {movement.id!r} references unknown approach "
                    f"{movement.approach!r}"
                )

        heads_by_id = {}
        for head in self.signal_heads:
            if head.id in heads_by_id:
                raise ValueError(
                    f"signal head ids must be unique: {head.id}"
                )
            heads_by_id[head.id] = head
            if head.approach not in approaches:
                raise ValueError(
                    f"signal head {head.id!r} references unknown approach "
                    f"{head.approach!r}"
                )
            unknown_movements = [
                movement_id
                for movement_id in head.movement_ids
                if movement_id not in movements_by_id
            ]
            if unknown_movements:
                raise ValueError(
                    f"signal head {head.id!r} references unknown movements: "
                    + ", ".join(unknown_movements)
                )
            for movement_id in head.movement_ids:
                if movements_by_id[movement_id].approach != head.approach:
                    raise ValueError(
                        f"signal head {head.id!r} controls movement "
                        f"{movement_id!r} from another approach"
                    )

        controlled = {
            movement_id
            for head in self.signal_heads
            for movement_id in head.movement_ids
        }
        uncontrolled = sorted(set(movements_by_id) - controlled)
        if uncontrolled:
            raise ValueError(
                "every movement must be controlled by at least one signal "
                "head: " + ", ".join(uncontrolled)
            )

        family_conflicts = {
            _normalize_pair(left, right)
            for left, right in self.family_conflicts
        }
        for left, right in family_conflicts:
            if left == right:
                raise ValueError("signal family cannot conflict with itself")
            if left not in family_names or right not in family_names:
                raise ValueError(
                    "family conflict references an unknown signal family"
                )

        movement_conflicts = {
            _normalize_pair(left, right)
            for left, right in self.movement_conflicts
        }
        movement_compatibilities = {
            _normalize_pair(left, right)
            for left, right in self.movement_compatibilities
        }
        movement_names = set(movements_by_id)
        for left, right in (
            movement_conflicts | movement_compatibilities
        ):
            if left not in movement_names or right not in movement_names:
                raise ValueError(
                    "movement conflict/compatibility references an unknown "
                    f"movement: {left}, {right}"
                )
        if movement_conflicts & movement_compatibilities:
            raise ValueError(
                "a movement pair cannot be both conflicting and compatible"
            )

        object.__setattr__(self, "intersection_id", intersection_id)
        object.__setattr__(
            self,
            "family_conflicts",
            tuple(sorted(family_conflicts)),
        )
        object.__setattr__(
            self,
            "movement_conflicts",
            tuple(sorted(movement_conflicts)),
        )
        object.__setattr__(
            self,
            "movement_compatibilities",
            tuple(sorted(movement_compatibilities)),
        )

    @property
    def approaches(self) -> tuple[str, ...]:
        return tuple(
            approach
            for family in self.families
            for approach in family.approaches
        )

    @property
    def movement_ids(self) -> tuple[str, ...]:
        return tuple(movement.id for movement in self.movements)

    @property
    def primary_signal_heads(self) -> tuple[SignalHead, ...]:
        return tuple(
            head for head in self.signal_heads if head.is_primary
        )

    @property
    def additional_signal_heads(self) -> tuple[SignalHead, ...]:
        return tuple(
            head for head in self.signal_heads if head.additional
        )

    def movement(self, movement_id: str) -> Movement:
        key = str(movement_id).strip()
        for movement in self.movements:
            if movement.id == key:
                return movement
        raise KeyError(key)

    def signal_head(self, head_id: str) -> SignalHead:
        key = str(head_id).strip()
        for head in self.signal_heads:
            if head.id == key:
                return head
        raise KeyError(key)

    def signal_heads_for_movement(
        self,
        movement_id: str,
    ) -> tuple[SignalHead, ...]:
        return tuple(
            head
            for head in self.signal_heads
            if head.controls(movement_id)
        )

    def movements_for_signal_head(
        self,
        head_id: str,
    ) -> tuple[Movement, ...]:
        head = self.signal_head(head_id)
        return tuple(self.movement(item) for item in head.movement_ids)

    def family_for_approach(self, approach: str) -> str | None:
        key = str(approach).strip()
        for family in self.families:
            if key in family.approaches:
                return family.name
        return None

    def to_topology(self) -> IntersectionTopology:
        """Build the legacy topology consumed by existing production code."""
        return IntersectionTopology(
            families=self.families,
            family_conflicts=self.family_conflicts,
            movement_conflicts=self.movement_conflicts,
            movement_compatibilities=self.movement_compatibilities,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "intersection_id": self.intersection_id,
            "families": [family.to_dict() for family in self.families],
            "movements": [
                movement.to_dict() for movement in self.movements
            ],
            "signal_heads": [
                head.to_dict() for head in self.signal_heads
            ],
            "family_conflicts": [
                list(pair) for pair in self.family_conflicts
            ],
            "movement_conflicts": [
                list(pair) for pair in self.movement_conflicts
            ],
            "movement_compatibilities": [
                list(pair)
                for pair in self.movement_compatibilities
            ],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "IntersectionConfig":
        if not isinstance(payload, Mapping):
            raise ValueError("intersection config must be an object")

        intersection_id = str(payload.get("intersection_id", "")).strip()

        raw_families = payload.get("families")
        if not isinstance(raw_families, list):
            raise ValueError("intersection config families must be a list")
        families = tuple(
            SignalFamily(
                name=str(item.get("name", "")),
                approaches=tuple(
                    str(value)
                    for value in item.get("approaches", [])
                ),
            )
            for item in raw_families
            if isinstance(item, Mapping)
        )
        if len(families) != len(raw_families):
            raise ValueError("intersection config family must be an object")

        raw_movements = payload.get("movements")
        if not isinstance(raw_movements, list):
            raise ValueError("intersection config movements must be a list")
        movements: list[Movement] = []
        for item in raw_movements:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "intersection config movement must be an object"
                )
            movements.append(
                Movement(
                    id=str(item.get("id", "")),
                    approach=str(item.get("approach", "")),
                    destination=str(item.get("destination", "")),
                    kind=str(item.get("kind", "through")),
                )
            )

        raw_heads = payload.get("signal_heads")
        if not isinstance(raw_heads, list):
            raise ValueError(
                "intersection config signal_heads must be a list"
            )
        heads: list[SignalHead] = []
        for item in raw_heads:
            if not isinstance(item, Mapping):
                raise ValueError(
                    "intersection config signal head must be an object"
                )
            heads.append(
                SignalHead(
                    id=str(item.get("id", "")),
                    approach=str(item.get("approach", "")),
                    movement_ids=tuple(
                        str(value)
                        for value in item.get("movement_ids", [])
                    ),
                    additional=bool(item.get("additional", False)),
                    arrows=tuple(
                        str(value) for value in item.get("arrows", [])
                    ),
                    colors=tuple(
                        str(value)
                        for value in item.get(
                            "colors",
                            ("RED", "YELLOW", "GREEN"),
                        )
                    ),
                )
            )

        def pairs(key: str) -> tuple[tuple[str, str], ...]:
            raw = payload.get(key, [])
            if not isinstance(raw, list):
                raise ValueError(f"intersection config {key} must be a list")
            result: list[tuple[str, str]] = []
            for item in raw:
                if (
                    not isinstance(item, (list, tuple))
                    or len(item) != 2
                ):
                    raise ValueError(
                        f"intersection config {key} entries must contain two "
                        "names"
                    )
                result.append((str(item[0]), str(item[1])))
            return tuple(result)

        return cls(
            intersection_id=intersection_id,
            families=families,
            movements=tuple(movements),
            signal_heads=tuple(heads),
            family_conflicts=pairs("family_conflicts"),
            movement_conflicts=pairs("movement_conflicts"),
            movement_compatibilities=pairs(
                "movement_compatibilities"
            ),
        )


def _default_movements() -> tuple[Movement, ...]:
    approaches = ("N", "S", "E", "W")
    destinations = approaches
    return tuple(
        Movement(
            id=f"{approach}->{destination}",
            approach=approach,
            destination=destination,
            kind=(
                "uturn"
                if approach == destination
                else "through"
                if (
                    (approach, destination) in {
                        ("N", "S"),
                        ("S", "N"),
                        ("E", "W"),
                        ("W", "E"),
                    }
                )
                else "turn"
            ),
        )
        for approach in approaches
        for destination in destinations
    )


def _default_signal_heads() -> tuple[SignalHead, ...]:
    movements = _default_movements()
    by_approach: dict[str, list[str]] = {}
    for movement in movements:
        by_approach.setdefault(movement.approach, []).append(movement.id)
    return tuple(
        SignalHead(
            id=f"{approach}_MAIN",
            approach=approach,
            movement_ids=tuple(by_approach[approach]),
        )
        for approach in ("N", "S", "E", "W")
    )


DEFAULT_INTERSECTION_CONFIG = IntersectionConfig(
    intersection_id="default-four-way",
    families=(
        SignalFamily("NS", ("N", "S")),
        SignalFamily("EW", ("E", "W")),
    ),
    movements=_default_movements(),
    signal_heads=_default_signal_heads(),
    family_conflicts=(("NS", "EW"),),
)


__all__ = [
    "ARROW_DIRECTIONS",
    "DEFAULT_INTERSECTION_CONFIG",
    "IntersectionConfig",
    "Movement",
    "SIGNAL_COLORS",
    "SignalHead",
]
