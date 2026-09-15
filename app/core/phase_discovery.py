from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

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
    """Discover non-overlapping traffic-light phases from a folded cycle."""

    def __init__(
        self,
        *,
        bin_seconds: float = 2.0,
        smoothing_sigma_bins: float = 1.5,
        correlation_threshold: float = CORRELATION_THRESHOLD,
        min_active_ratio: float = MIN_ACTIVE_RATIO,
        dominance_ratio: float = 1.10,
        min_phase_bins: int = 2,
    ) -> None:
        if bin_seconds <= 0:
            raise ValueError("bin_seconds must be positive")
        if not 0 < correlation_threshold < 1:
            raise ValueError("correlation_threshold must be in (0, 1)")
        if not 0 < min_active_ratio < 1:
            raise ValueError("min_active_ratio must be in (0, 1)")
        if dominance_ratio <= 1:
            raise ValueError("dominance_ratio must exceed 1")
        if min_phase_bins < 1:
            raise ValueError("min_phase_bins must be positive")
        self.bin_seconds = bin_seconds
        self.smoothing_sigma_bins = smoothing_sigma_bins
        self.correlation_threshold = correlation_threshold
        self.min_active_ratio = min_active_ratio
        self.dominance_ratio = dominance_ratio
        self.min_phase_bins = min_phase_bins

    def build_profiles(self, frame: pd.DataFrame, *, cycle_seconds: float) -> tuple[list[Profile], np.ndarray]:
        self._validate_frame(frame)
        if cycle_seconds <= self.bin_seconds:
            raise ValueError("cycle_seconds must exceed bin_seconds")

        n_bins = max(1, int(round(cycle_seconds / self.bin_seconds)))
        centers = np.arange(n_bins, dtype=float) * self.bin_seconds
        approaches = frame["zone_in"].astype(str).to_numpy()
        movements = frame["movement"].astype(str).to_numpy()
        weights = pd.to_numeric(frame["release_weight"], errors="coerce").fillna(0.0).to_numpy(float)
        times = pd.to_numeric(frame["t_s"], errors="coerce").fillna(0.0).to_numpy(float)
        phase_positions = np.mod(times, cycle_seconds)
        bin_ids = np.minimum((phase_positions / cycle_seconds * n_bins).astype(int), n_bins - 1)

        profiles: list[Profile] = []
        for approach in APPROACHES:
            mask = approaches == approach
            profile = np.bincount(bin_ids[mask], weights=weights[mask], minlength=n_bins).astype(float)
            profiles.append(Profile(approach, "approach", tuple(self._smooth(profile))))

        for movement in sorted(set(movements)):
            mask = movements == movement
            profile = np.bincount(bin_ids[mask], weights=weights[mask], minlength=n_bins).astype(float)
            if float(profile.sum()) <= 0:
                continue
            profiles.append(Profile(movement, "movement", tuple(self._smooth(profile))))
        return profiles, centers

    def discover(self, frame: pd.DataFrame, *, cycle_seconds: float) -> PhaseDiscoveryResult:
        profiles, _ = self.build_profiles(frame, cycle_seconds=cycle_seconds)
        approach_profiles = {p.key: np.asarray(p.values, dtype=float) for p in profiles if p.kind == "approach"}
        if not any(float(values.sum()) > 0 for values in approach_profiles.values()):
            raise RuntimeError("no approach traffic profiles available for phase discovery")

        partition = self._infer_partition(approach_profiles)
        labels, group_scores = self._segment_groups(partition, approach_profiles)
        runs = self._build_runs(labels)
        runs = self._merge_short_gaps(runs, labels)
        runs = [run for run in runs if self._run_length(run, len(labels)) >= self.min_phase_bins]
        if not runs:
            raise RuntimeError("unable to find stable phase intervals")

        movement_profiles = {p.key: np.asarray(p.values, dtype=float) for p in profiles if p.kind == "movement"}
        phases: list[Phase] = []
        for phase_id, (group_index, start_idx, end_idx) in enumerate(runs, start=1):
            active = tuple(sorted(partition[group_index]))
            start_s = round(start_idx * self.bin_seconds, 2)
            end_s = round((end_idx % len(labels)) * self.bin_seconds, 2)
            interval_mask = self._interval_mask(start_idx, end_idx, len(labels))
            if start_idx == end_idx:
                end_s = round(cycle_seconds, 2)
            confidence = self._phase_confidence(active, approach_profiles, group_scores[group_index], interval_mask)
            active_movements = tuple(sorted(
                movement for movement, values in movement_profiles.items()
                if self._movement_belongs(values, interval_mask)
            ))
            phases.append(Phase(
                phase_id=phase_id,
                phase_start=start_s,
                phase_end=end_s,
                active_approaches=active,
                active_movements=active_movements,
                confidence=round(confidence, 4),
                members=tuple(active + active_movements),
            ))

        phases.sort(key=lambda phase: phase.phase_start)
        phases = [
            Phase(index, phase.phase_start, phase.phase_end, phase.active_approaches,
                  phase.active_movements, phase.confidence, phase.members)
            for index, phase in enumerate(phases, start=1)
        ]

        values = np.asarray([profile.values for profile in profiles], dtype=float)
        similarity_matrix = self._correlation_matrix(values)
        similarities = {
            profiles[row].key: {
                profiles[col].key: round(float(similarity_matrix[row, col]), 4)
                for col in range(len(profiles))
                if col != row and similarity_matrix[row, col] >= self.correlation_threshold
            }
            for row in range(len(profiles))
        }
        return PhaseDiscoveryResult(float(cycle_seconds), self.bin_seconds, tuple(phases), tuple(profiles), similarities)

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

    def _safe_corr(self, left: np.ndarray, right: np.ndarray) -> float:
        a = left - left.mean()
        b = right - right.mean()
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom <= MIN_SIGNAL_STD:
            return 0.0
        return float(np.dot(a, b) / denom)

    def _correlation_matrix(self, values: np.ndarray) -> np.ndarray:
        count = values.shape[0]
        matrix = np.eye(count, dtype=float)
        for left in range(count):
            for right in range(left + 1, count):
                corr = self._safe_corr(values[left], values[right])
                matrix[left, right] = corr
                matrix[right, left] = corr
        return matrix

    def _infer_partition(self, profiles: dict[str, np.ndarray]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        candidates: list[tuple[float, tuple[str, ...], tuple[str, ...]]] = []
        seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
        for size in range(1, len(APPROACHES) // 2 + 1):
            for left_items in combinations(APPROACHES, size):
                left = tuple(sorted(left_items))
                right = tuple(sorted(key for key in APPROACHES if key not in left))
                canonical = tuple(sorted((left, right)))
                if canonical in seen:
                    continue
                seen.add(canonical)
                candidates.append((self._partition_score(left, right, profiles), left, right))
        return max(candidates, key=lambda item: item[0])[1:]

    def _partition_score(self, left: tuple[str, ...], right: tuple[str, ...], profiles: dict[str, np.ndarray]) -> float:
        left_signal = np.sum([profiles[key] for key in left], axis=0)
        right_signal = np.sum([profiles[key] for key in right], axis=0)
        total = left_signal + right_signal
        separation = float(np.mean(np.abs(left_signal - right_signal)) / (np.mean(total) + 1e-9))
        within = [self._safe_corr(profiles[a], profiles[b]) for group in (left, right) for a, b in combinations(group, 2)]
        within_score = (float(np.mean(within)) + 1.0) / 2.0 if within else 0.5
        return separation + within_score

    def _segment_groups(self, partition: tuple[tuple[str, ...], tuple[str, ...]], profiles: dict[str, np.ndarray]) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
        groups = tuple(np.sum([profiles[key] for key in group], axis=0) for group in partition)
        peak = float(max(groups[0].max(), groups[1].max()))
        if peak <= MIN_SIGNAL_STD:
            return np.full(len(groups[0]), -1, dtype=int), groups
        threshold = peak * self.min_active_ratio
        labels = np.full(len(groups[0]), -1, dtype=int)
        for index, (left, right) in enumerate(zip(groups[0], groups[1])):
            if left >= threshold and left >= right * self.dominance_ratio:
                labels[index] = 0
            elif right >= threshold and right >= left * self.dominance_ratio:
                labels[index] = 1
        return labels, groups

    def _build_runs(self, labels: np.ndarray) -> list[tuple[int, int, int]]:
        runs: list[tuple[int, int, int]] = []
        current = -1
        start = 0
        for index, label in enumerate(np.append(labels, [-1])):
            if label == current:
                continue
            if current >= 0:
                runs.append((current, start, index))
            current = int(label)
            start = index
        if runs and runs[0][0] == runs[-1][0] and runs[0][1] == 0 and runs[-1][2] == len(labels):
            first, last = runs[0], runs[-1]
            runs = [(first[0], last[1], first[2])] + runs[1:-1]
        return runs

    def _merge_short_gaps(self, runs: list[tuple[int, int, int]], labels: np.ndarray) -> list[tuple[int, int, int]]:
        if len(runs) < 2:
            return runs
        result = runs[:]
        changed = True
        while changed:
            changed = False
            new_runs: list[tuple[int, int, int]] = []
            index = 0
            while index < len(result):
                current = result[index]
                if index + 2 < len(result):
                    gap_start = current[2]
                    middle = result[index + 1]
                    next_run = result[index + 2]
                    if middle[0] < 0 and middle[2] - middle[1] <= 2 and current[0] == next_run[0]:
                        new_runs.append((current[0], current[1], next_run[2]))
                        index += 3
                        changed = True
                        continue
                new_runs.append(current)
                index += 1
            result = new_runs
        return result

    @staticmethod
    def _run_length(run: tuple[int, int, int], n_bins: int) -> int:
        _, start, end = run
        return end - start if start <= end else n_bins - start + end

    @staticmethod
    def _interval_mask(start_idx: int, end_idx: int, n_bins: int) -> np.ndarray:
        mask = np.zeros(n_bins, dtype=bool)
        if start_idx == end_idx:
            mask[:] = True
        elif start_idx < end_idx:
            mask[start_idx:end_idx] = True
        else:
            mask[start_idx:] = True
            mask[:end_idx] = True
        return mask

    @staticmethod
    def _movement_belongs(values: np.ndarray, interval_mask: np.ndarray) -> bool:
        total = float(values.sum())
        if total <= MIN_SIGNAL_STD:
            return False
        return float(values[interval_mask].sum()) / total >= 0.45

    def _phase_confidence(self, active: tuple[str, ...], profiles: dict[str, np.ndarray], group_profile: np.ndarray, interval_mask: np.ndarray) -> float:
        active_mean = float(np.mean(group_profile[interval_mask])) if interval_mask.any() else 0.0
        inactive_keys = [key for key in APPROACHES if key not in active]
        inactive_profile = np.sum([profiles[key] for key in inactive_keys], axis=0)
        inactive_mean = float(np.mean(inactive_profile[interval_mask])) if interval_mask.any() else 0.0
        dominance = active_mean / (active_mean + inactive_mean + 1e-9)
        internal = [self._safe_corr(profiles[a], profiles[b]) for a, b in combinations(active, 2)]
        internal_score = (float(np.mean(internal)) + 1.0) / 2.0 if internal else 0.75
        return min(1.0, 0.6 * dominance + 0.4 * internal_score)


def discover_phases(frame: pd.DataFrame, cycle_seconds: float) -> PhaseDiscoveryResult:
    return PhaseDiscovery().discover(frame, cycle_seconds=cycle_seconds)
