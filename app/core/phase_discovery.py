from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

APPROACHES = ("N", "S", "E", "W")
MIN_ACTIVE_RATIO = 0.35
CORRELATION_THRESHOLD = 0.55
MIN_SIGNAL_STD = 1e-9


@dataclass(frozen=True)
class Profile:
    key: str
    kind: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class Phase:
    phase_id: int
    phase_start: float
    phase_end: float
    active_approaches: tuple[str, ...]
    active_movements: tuple[str, ...]
    confidence: float
    members: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PhaseDiscoveryResult:
    cycle_seconds: float
    bin_seconds: float
    phases: tuple[Phase, ...]
    profiles: tuple[Profile, ...]
    similarities: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, object]:
        return {
            "cycle_seconds": self.cycle_seconds,
            "bin_seconds": self.bin_seconds,
            "phases": [phase.to_dict() for phase in self.phases],
            "profiles": [asdict(profile) for profile in self.profiles],
            "similarities": self.similarities,
        }


class PhaseDiscovery:
    """Discover co-activated traffic phases from a previously estimated cycle."""

    def __init__(
        self,
        *,
        bin_seconds: float = 2.0,
        smoothing_sigma_bins: float = 1.5,
        correlation_threshold: float = CORRELATION_THRESHOLD,
        min_active_ratio: float = MIN_ACTIVE_RATIO,
    ) -> None:
        if bin_seconds <= 0:
            raise ValueError("bin_seconds must be positive")
        if not 0 < correlation_threshold < 1:
            raise ValueError("correlation_threshold must be in (0, 1)")
        if not 0 < min_active_ratio < 1:
            raise ValueError("min_active_ratio must be in (0, 1)")
        self.bin_seconds = bin_seconds
        self.smoothing_sigma_bins = smoothing_sigma_bins
        self.correlation_threshold = correlation_threshold
        self.min_active_ratio = min_active_ratio

    def build_profiles(
        self,
        frame: pd.DataFrame,
        *,
        cycle_seconds: float,
    ) -> tuple[list[Profile], np.ndarray]:
        self._validate_frame(frame)
        if cycle_seconds <= self.bin_seconds:
            raise ValueError("cycle_seconds must exceed bin_seconds")

        n_bins = max(1, int(round(cycle_seconds / self.bin_seconds)))
        centers = np.arange(n_bins, dtype=float) * self.bin_seconds
        profiles: list[Profile] = []

        approaches = frame["zone_in"].astype(str)
        movements = frame["movement"].astype(str)
        weights = pd.to_numeric(frame["release_weight"], errors="coerce").fillna(0.0)
        phases = np.mod(pd.to_numeric(frame["t_s"], errors="coerce"), cycle_seconds)
        bin_ids = np.minimum((phases / cycle_seconds * n_bins).astype(int), n_bins - 1)

        for approach in APPROACHES:
            mask = approaches == approach
            if mask.any():
                profile = np.bincount(
                    bin_ids[mask], weights=weights[mask], minlength=n_bins
                ).astype(float)
                profiles.append(
                    Profile(
                        key=approach,
                        kind="approach",
                        values=tuple(self._smooth(profile)),
                    )
                )

        for movement in sorted(movements.unique()):
            mask = movements == movement
            profile = np.bincount(
                bin_ids[mask], weights=weights[mask], minlength=n_bins
            ).astype(float)
            if float(profile.sum()) <= 0:
                continue
            profiles.append(
                Profile(
                    key=movement,
                    kind="movement",
                    values=tuple(self._smooth(profile)),
                )
            )

        return profiles, centers

    def discover(
        self,
        frame: pd.DataFrame,
        *,
        cycle_seconds: float,
    ) -> PhaseDiscoveryResult:
        profiles, centers = self.build_profiles(frame, cycle_seconds=cycle_seconds)
        if not profiles:
            raise RuntimeError("no traffic profiles available for phase discovery")

        values = np.asarray([profile.values for profile in profiles], dtype=float)
        similarity_matrix = self._correlation_matrix(values)
        groups = self._connected_components(similarity_matrix)

        phases: list[Phase] = []
        for phase_id, member_indices in enumerate(groups, start=1):
            member_profiles = [profiles[index] for index in member_indices]
            aggregate = np.mean(
                np.asarray([profile.values for profile in member_profiles], dtype=float),
                axis=0,
            )
            start, end, active_strength = self._active_interval(aggregate, centers, cycle_seconds)
            active_approaches = tuple(
                profile.key
                for profile in member_profiles
                if profile.kind == "approach" and profile.key in APPROACHES
            )
            active_movements = tuple(
                profile.key for profile in member_profiles if profile.kind == "movement"
            )
            phases.append(
                Phase(
                    phase_id=phase_id,
                    phase_start=round(start, 2),
                    phase_end=round(end, 2),
                    active_approaches=tuple(sorted(active_approaches)),
                    active_movements=tuple(sorted(active_movements)),
                    confidence=round(active_strength, 4),
                    members=tuple(profile.key for profile in member_profiles),
                )
            )

        phases.sort(key=lambda phase: phase.phase_start)
        phases = [
            Phase(
                phase_id=index,
                phase_start=phase.phase_start,
                phase_end=phase.phase_end,
                active_approaches=phase.active_approaches,
                active_movements=phase.active_movements,
                confidence=phase.confidence,
                members=phase.members,
            )
            for index, phase in enumerate(phases, start=1)
        ]

        similarities = {
            profiles[row].key: {
                profiles[col].key: round(float(similarity_matrix[row, col]), 4)
                for col in range(len(profiles))
                if col != row and similarity_matrix[row, col] >= self.correlation_threshold
            }
            for row in range(len(profiles))
        }
        return PhaseDiscoveryResult(
            cycle_seconds=float(cycle_seconds),
            bin_seconds=self.bin_seconds,
            phases=tuple(phases),
            profiles=tuple(profiles),
            similarities=similarities,
        )

    def _validate_frame(self, frame: pd.DataFrame) -> None:
        required = {"t_s", "zone_in", "movement", "release_weight"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"missing required columns: {sorted(missing)}")

    def _smooth(self, values: np.ndarray) -> np.ndarray:
        if len(values) < 3:
            return values
        padded = np.concatenate([values[-2:], values, values[:2]])
        return gaussian_filter1d(padded, sigma=self.smoothing_sigma_bins, mode="wrap")[2:-2]

    def _correlation_matrix(self, values: np.ndarray) -> np.ndarray:
        count = values.shape[0]
        matrix = np.eye(count, dtype=float)
        normalized = values - values.mean(axis=1, keepdims=True)
        norms = np.linalg.norm(normalized, axis=1)
        for left in range(count):
            if norms[left] <= MIN_SIGNAL_STD:
                continue
            for right in range(left + 1, count):
                if norms[right] <= MIN_SIGNAL_STD:
                    continue
                corr = float(np.dot(normalized[left], normalized[right]) / (norms[left] * norms[right]))
                matrix[left, right] = corr
                matrix[right, left] = corr
        return matrix

    def _connected_components(self, similarity: np.ndarray) -> list[list[int]]:
        visited = set()
        components: list[list[int]] = []
        for start in range(len(similarity)):
            if start in visited:
                continue
            stack = [start]
            visited.add(start)
            component: list[int] = []
            while stack:
                current = stack.pop()
                component.append(current)
                neighbours = np.flatnonzero(similarity[current] >= self.correlation_threshold)
                for neighbour in neighbours:
                    if int(neighbour) not in visited:
                        visited.add(int(neighbour))
                        stack.append(int(neighbour))
            components.append(sorted(component))
        return components

    def _active_interval(
        self,
        values: np.ndarray,
        centers: np.ndarray,
        cycle_seconds: float,
    ) -> tuple[float, float, float]:
        maximum = float(values.max())
        if maximum <= 0:
            return 0.0, 0.0, 0.0
        threshold = maximum * self.min_active_ratio
        active = values >= threshold
        if not active.any():
            peak = int(np.argmax(values))
            return float(centers[peak]), float(centers[peak]), 0.0

        doubled = np.concatenate([active, active])
        runs: list[tuple[int, int]] = []
        start = None
        for index, flag in enumerate(doubled):
            if flag and start is None:
                start = index
            elif not flag and start is not None:
                runs.append((start, index))
                start = None
        if start is not None:
            runs.append((start, len(doubled)))
        n = len(values)
        runs = [(a, b) for a, b in runs if b - a <= n]
        best = max(runs, key=lambda run: (run[1] - run[0], values[run[0] % n]))
        start_idx = best[0] % n
        end_idx = (best[1] - 1) % n
        start_s = float(centers[start_idx])
        end_s = float(centers[end_idx] + self.bin_seconds)
        duration = (end_s - start_s) % cycle_seconds
        if duration == 0:
            duration = cycle_seconds
        confidence = min(1.0, float(values[active].mean() / maximum))
        return start_s, end_s, confidence



def discover_phases(frame: pd.DataFrame, cycle_seconds: float) -> PhaseDiscoveryResult:
    return PhaseDiscovery().discover(frame, cycle_seconds=cycle_seconds)
