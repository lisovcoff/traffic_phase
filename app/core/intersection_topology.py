from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


def _pair(left: str, right: str) -> tuple[str, str]:
    first = str(left).strip()
    second = str(right).strip()
    return tuple(sorted((first, second)))


@dataclass(frozen=True)
class SignalFamily:
    """Stable synchronization/conflict family for one or more approaches."""

    name: str
    approaches: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "approaches": list(self.approaches),
        }


@dataclass(frozen=True)
class IntersectionTopology:
    """Conflict model shared by signal-state and realtime inference.

    Family conflicts are the conservative fallback when exact movement
    geometry is unknown. Explicit movement compatibility or conflict pairs
    override that fallback when configured for a particular intersection.
    """

    families: tuple[SignalFamily, ...]
    family_conflicts: tuple[tuple[str, str], ...] = ()
    movement_conflicts: tuple[tuple[str, str], ...] = ()
    movement_compatibilities: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        names = [family.name for family in self.families]
        if not names or any(not name for name in names):
            raise ValueError("topology requires named signal families")
        if len(set(names)) != len(names):
            raise ValueError("topology family names must be unique")

        approaches: list[str] = []
        for family in self.families:
            if not family.approaches:
                raise ValueError("signal family requires at least one approach")
            for approach in family.approaches:
                if not approach:
                    raise ValueError("approach names must not be empty")
                approaches.append(approach)
        if len(set(approaches)) != len(approaches):
            raise ValueError("an approach may belong to only one signal family")

        family_names = set(names)
        normalized_family_conflicts = {
            _pair(left, right)
            for left, right in self.family_conflicts
        }
        for left, right in normalized_family_conflicts:
            if left == right:
                raise ValueError("signal family cannot conflict with itself")
            if left not in family_names or right not in family_names:
                raise ValueError("family conflict references unknown family")

        normalized_conflicts = {
            _pair(left, right)
            for left, right in self.movement_conflicts
        }
        normalized_compatibilities = {
            _pair(left, right)
            for left, right in self.movement_compatibilities
        }
        if normalized_conflicts & normalized_compatibilities:
            raise ValueError(
                "movement pair cannot be both conflicting and compatible"
            )

        object.__setattr__(
            self,
            "family_conflicts",
            tuple(sorted(normalized_family_conflicts)),
        )
        object.__setattr__(
            self,
            "movement_conflicts",
            tuple(sorted(normalized_conflicts)),
        )
        object.__setattr__(
            self,
            "movement_compatibilities",
            tuple(sorted(normalized_compatibilities)),
        )

    @property
    def approaches(self) -> tuple[str, ...]:
        return tuple(
            approach
            for family in self.families
            for approach in family.approaches
        )

    def family_for_approach(self, approach: str) -> str | None:
        for family in self.families:
            if approach in family.approaches:
                return family.name
        return None

    def approaches_for_family(self, family_name: str) -> tuple[str, ...]:
        for family in self.families:
            if family.name == family_name:
                return family.approaches
        return ()

    def family_for_active_approaches(
        self,
        active_approaches: Sequence[str],
    ) -> str | None:
        active = tuple(active_approaches)
        if not active:
            return None
        families = {
            self.family_for_approach(approach)
            for approach in active
        }
        if None in families or len(families) != 1:
            return None
        return next(iter(families))

    def conflicting_families_for(
        self,
        family_name: str | None,
    ) -> tuple[str, ...]:
        if family_name is None:
            return ()
        result: list[str] = []
        for left, right in self.family_conflicts:
            if left == family_name:
                result.append(right)
            elif right == family_name:
                result.append(left)
        return tuple(result)

    def families_conflict(
        self,
        left: str | None,
        right: str | None,
    ) -> bool:
        if left is None or right is None or left == right:
            return False
        return _pair(left, right) in set(self.family_conflicts)

    def approaches_conflict(self, left: str, right: str) -> bool:
        return self.families_conflict(
            self.family_for_approach(left),
            self.family_for_approach(right),
        )

    @staticmethod
    def movement_approach(movement: str | None) -> str | None:
        if not movement or "->" not in movement:
            return None
        approach = movement.split("->", 1)[0].strip()
        return approach or None

    def movements_conflict(
        self,
        left_movement: str,
        right_movement: str,
        *,
        left_approach: str | None = None,
        right_approach: str | None = None,
    ) -> bool:
        pair = _pair(left_movement, right_movement)
        if pair in set(self.movement_compatibilities):
            return False
        if pair in set(self.movement_conflicts):
            return True

        left = left_approach or self.movement_approach(left_movement)
        right = right_approach or self.movement_approach(right_movement)
        if left is None or right is None:
            return False
        return self.approaches_conflict(left, right)

    def to_dict(self) -> dict[str, object]:
        return {
            "families": [family.to_dict() for family in self.families],
            "family_conflicts": [
                list(pair) for pair in self.family_conflicts
            ],
            "movement_conflicts": [
                list(pair) for pair in self.movement_conflicts
            ],
            "movement_compatibilities": [
                list(pair) for pair in self.movement_compatibilities
            ],
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "IntersectionTopology":
        raw_families = payload.get("families")
        if not isinstance(raw_families, list):
            raise ValueError("topology families must be a list")

        families: list[SignalFamily] = []
        for item in raw_families:
            if not isinstance(item, Mapping):
                raise ValueError("topology family must be an object")
            name = str(item.get("name", "")).strip()
            raw_approaches = item.get("approaches")
            if not isinstance(raw_approaches, list):
                raise ValueError("topology family approaches must be a list")
            families.append(
                SignalFamily(
                    name=name,
                    approaches=tuple(str(value) for value in raw_approaches),
                )
            )

        def pairs(key: str) -> tuple[tuple[str, str], ...]:
            raw = payload.get(key, [])
            if not isinstance(raw, list):
                raise ValueError(f"topology {key} must be a list")
            result: list[tuple[str, str]] = []
            for item in raw:
                if (
                    not isinstance(item, (list, tuple))
                    or len(item) != 2
                ):
                    raise ValueError(
                        f"topology {key} entries must contain two names"
                    )
                result.append((str(item[0]), str(item[1])))
            return tuple(result)

        return cls(
            families=tuple(families),
            family_conflicts=pairs("family_conflicts"),
            movement_conflicts=pairs("movement_conflicts"),
            movement_compatibilities=pairs(
                "movement_compatibilities"
            ),
        )


DEFAULT_INTERSECTION_TOPOLOGY = IntersectionTopology(
    families=(
        SignalFamily("NS", ("N", "S")),
        SignalFamily("EW", ("E", "W")),
    ),
    family_conflicts=(("NS", "EW"),),
)

DEFAULT_FAMILY_APPROACHES = {
    family.name: frozenset(family.approaches)
    for family in DEFAULT_INTERSECTION_TOPOLOGY.families
}


__all__ = [
    "DEFAULT_FAMILY_APPROACHES",
    "DEFAULT_INTERSECTION_TOPOLOGY",
    "IntersectionTopology",
    "SignalFamily",
]
