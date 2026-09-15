from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

APPROACHES = ("N", "S", "E", "W")
MIN_SIGNAL_STD = 1e-9
DEFAULT_MIN_PHASE_SECONDS = 8.0
DEFAULT_ACTIVITY_THRESHOLD = 0.35


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
            "phases": [p.to_dict() for p in self.phases],
            "profiles": [asdict(p) for p in self.profiles],
            "similarities": self.similarities,
        }


class PhaseDiscovery:
    """Infer recurring traffic regimes from a consensus folded over many cycles.

    The model deliberately does not choose a phase at every raw timestamp. It first
    builds one robust per-approach profile from the median activity of individual
    cycles, then detects sustained directional activity and converts those stable
    intervals into candidate signal phases. This separates recurring signal structure
    from one-off traffic fluctuations.
    """

    def __init__(
        self,
        *,
        bin_seconds: float = 2.0,
        min_phase_seconds: float = DEFAULT_MIN_PHASE_SECONDS,
        release_weight: float = 1.0,
        queue_weight: float = 0.25,
        activity_threshold: float = DEFAULT_ACTIVITY_THRESHOLD,
        min_cycles: int = 3,
    ) -> None:
        if bin_seconds <= 0 or min_phase_seconds < bin_seconds:
            raise ValueError("invalid phase-discovery timing parameters")
        if not 0 < activity_threshold < 1:
            raise ValueError("activity_threshold must be in (0, 1)")
        if min_cycles < 1:
            raise ValueError("min_cycles must be positive")
        self.bin_seconds = bin_seconds
        self.min_phase_bins = max(1, int(round(min_phase_seconds / bin_seconds)))
        self.release_weight = release_weight
        self.queue_weight = queue_weight
        self.activity_threshold = activity_threshold
        self.min_cycles = min_cycles

    def build_profiles(
        self,
        frame: pd.DataFrame,
        *,
        cycle_seconds: float,
    ) -> tuple[list[Profile], np.ndarray]:
        self._validate_frame(frame)
        n_bins = max(1, int(round(cycle_seconds / self.bin_seconds)))
        centers = np.arange(n_bins, dtype=float) * self.bin_seconds
        profiles: list[Profile] = []

        for approach in APPROACHES:
            cycles = self._cycle_matrix(frame, cycle_seconds, n_bins, approach)
            release_consensus = self._robust_consensus(cycles[:, :, 0])
            queue_consensus = self._robust_consensus(cycles[:, :, 1])
            profiles.append(Profile(approach, "release", tuple(self._smooth(release_consensus))))
            profiles.append(Profile(f"{approach}:queue", "queue", tuple(self._smooth(queue_consensus))))

        movements = sorted(frame["movement"].astype(str).unique())
        for movement in movements:
            cycles = self._movement_cycle_matrix(frame, cycle_seconds, n_bins, movement)
            consensus = self._robust_consensus(cycles)
            if float(consensus.sum()) > 0:
                profiles.append(Profile(movement, "movement", tuple(self._smooth(consensus))))
        return profiles, centers

    def discover(self, frame: pd.DataFrame, *, cycle_seconds: float) -> PhaseDiscoveryResult:
        profiles, centers = self.build_profiles(frame, cycle_seconds=cycle_seconds)
        release = np.vstack([self._values(profiles, a, "release") for a in APPROACHES])
        queue = np.vstack([self._values(profiles, f"{a}:queue", "queue") for a in APPROACHES])

        activity = self._activity_score(release, queue)
        stable = self._stabilize_activity(activity)
        phases = self._phases(stable, activity, frame, cycle_seconds, centers)
        similarities = self._similarities(release)

        return PhaseDiscoveryResult(
            float(cycle_seconds),
            self.bin_seconds,
            tuple(phases),
            tuple(profiles),
            similarities,
        )

    def _validate_frame(self, frame: pd.DataFrame) -> None:
        required = {"t_s", "zone_in", "movement", "release_weight", "stopped"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"missing required columns: {sorted(missing)}")

    def _cycle_matrix(
        self,
        frame: pd.DataFrame,
        cycle_seconds: float,
        n_bins: int,
        approach: str,
    ) -> np.ndarray:
        t = pd.to_numeric(frame["t_s"], errors="coerce").fillna(0.0).to_numpy(float)
        cycles = np.floor(np.maximum(t, 0.0) / cycle_seconds).astype(int)
        cycle_count = int(cycles.max()) + 1 if len(cycles) else 1
        matrix = np.zeros((cycle_count, n_bins, 2), dtype=float)
        mask = frame["zone_in"].astype(str).to_numpy() == approach
        if not mask.any():
            return matrix[: max(1, min(cycle_count, self.min_cycles))]

        rel = pd.to_numeric(frame["release_weight"], errors="coerce").fillna(0.0).to_numpy(float)
        stopped = frame["stopped"].astype(float).to_numpy()
        rel_bins = self._bin_indices(t, cycle_seconds, n_bins)
        for cycle_id, bin_id, rel_value, stop_value, selected in zip(
            cycles,
            rel_bins,
            rel,
            stopped,
            mask,
        ):
            if selected:
                matrix[cycle_id, bin_id, 0] += max(0.0, float(rel_value))
                matrix[cycle_id, bin_id, 1] += max(0.0, float(stop_value))
        return matrix

    def _movement_cycle_matrix(
        self,
        frame: pd.DataFrame,
        cycle_seconds: float,
        n_bins: int,
        movement: str,
    ) -> np.ndarray:
        t = pd.to_numeric(frame["t_s"], errors="coerce").fillna(0.0).to_numpy(float)
        cycles = np.floor(np.maximum(t, 0.0) / cycle_seconds).astype(int)
        cycle_count = int(cycles.max()) + 1 if len(cycles) else 1
        matrix = np.zeros((cycle_count, n_bins), dtype=float)
        mask = frame["movement"].astype(str).to_numpy() == movement
        release = pd.to_numeric(frame["release_weight"], errors="coerce").fillna(0.0).to_numpy(float)
        rel_bins = self._bin_indices(t, cycle_seconds, n_bins)
        for cycle_id, bin_id, rel_value, selected in zip(cycles, rel_bins, release, mask):
            if selected:
                matrix[cycle_id, bin_id] += max(0.0, float(rel_value))
        return matrix

    @staticmethod
    def _bin_indices(t: np.ndarray, cycle_seconds: float, n_bins: int) -> np.ndarray:
        folded = np.mod(t, cycle_seconds)
        return np.minimum((folded / cycle_seconds * n_bins).astype(int), n_bins - 1)

    def _robust_consensus(self, matrix: np.ndarray) -> np.ndarray:
        if matrix.size == 0:
            return np.zeros(matrix.shape[-1] if matrix.ndim else 1, dtype=float)
        if matrix.shape[0] < self.min_cycles:
            return np.median(matrix, axis=0)
        return np.median(matrix, axis=0)

    @staticmethod
    def _values(profiles: list[Profile], key: str, kind: str) -> np.ndarray:
        for profile in profiles:
            if profile.key == key and profile.kind == kind:
                return np.asarray(profile.values, dtype=float)
        raise RuntimeError(f"missing profile {key}/{kind}")

    def _activity_score(self, release: np.ndarray, queue: np.ndarray) -> np.ndarray:
        release_strength = self._robust_scale_rows(release)
        queue_pressure = self._robust_scale_rows(queue)
        score = self.release_weight * release_strength - self.queue_weight * queue_pressure
        return np.clip(score, 0.0, 1.0)

    @staticmethod
    def _robust_scale_rows(values: np.ndarray) -> np.ndarray:
        median = np.median(values, axis=1, keepdims=True)
        q75 = np.percentile(values, 75, axis=1, keepdims=True)
        q90 = np.percentile(values, 90, axis=1, keepdims=True)
        scale = np.maximum(q90 - median, MIN_SIGNAL_STD)
        raw = (values - median) / scale
        raw = np.clip(raw, 0.0, 1.5)
        max_value = np.max(raw, axis=1, keepdims=True)
        max_value = np.maximum(max_value, MIN_SIGNAL_STD)
        return np.clip(raw / max_value, 0.0, 1.0)

    def _stabilize_activity(self, activity: np.ndarray) -> np.ndarray:
        active = activity >= self.activity_threshold
        active = self._remove_short_runs(active)
        active = self._fill_small_gaps(active)
        return active

    def _remove_short_runs(self, active: np.ndarray) -> np.ndarray:
        result = active.copy()
        for approach_idx in range(result.shape[0]):
            row = result[approach_idx]
            start = 0
            while start < len(row):
                end = start + 1
                while end < len(row) and row[end] == row[start]:
                    end += 1
                if row[start] and end - start < self.min_phase_bins:
                    left = row[start - 1] if start > 0 else False
                    right = row[end] if end < len(row) else False
                    replacement = left or right
                    row[start:end] = replacement
                start = end
            result[approach_idx] = row
        return result

    def _fill_small_gaps(self, active: np.ndarray) -> np.ndarray:
        result = active.copy()
        max_gap = max(1, self.min_phase_bins // 2)
        for approach_idx in range(result.shape[0]):
            row = result[approach_idx]
            i = 0
            while i < len(row):
                if row[i]:
                    i += 1
                    continue
                j = i + 1
                while j < len(row) and not row[j]:
                    j += 1
                if i > 0 and j < len(row) and j - i <= max_gap:
                    row[i:j] = True
                i = j
            result[approach_idx] = row
        return result

    def _phases(
        self,
        active: np.ndarray,
        score: np.ndarray,
        frame: pd.DataFrame,
        cycle_seconds: float,
        centers: np.ndarray,
    ) -> list[Phase]:
        state = [tuple(np.flatnonzero(active[:, idx]).tolist()) for idx in range(active.shape[1])]
        state = self._fill_empty_states(state, score)
        runs: list[tuple[int, int, tuple[int, ...]]] = []
        i = 0
        while i < len(state):
            j = i + 1
            while j < len(state) and state[j] == state[i]:
                j += 1
            runs.append((i, j, state[i]))
            i = j

        phases: list[Phase] = []
        for phase_id, (start_idx, end_idx, members) in enumerate(runs, 1):
            start_s = float(centers[start_idx])
            end_s = float(min(cycle_seconds, centers[end_idx - 1] + self.bin_seconds))
            approaches = tuple(APPROACHES[idx] for idx in members)
            if approaches:
                values = score[list(members), start_idx:end_idx]
                mean_score = float(np.mean(values)) if values.size else 0.0
                separation = self._phase_separation(score, members, start_idx, end_idx)
                confidence = float(np.clip(0.65 * mean_score + 0.35 * separation, 0.0, 1.0))
            else:
                confidence = 0.0
            movements = self._movements(frame, cycle_seconds, start_s, end_s, approaches)
            phases.append(
                Phase(
                    phase_id,
                    round(start_s, 2),
                    round(end_s, 2),
                    approaches,
                    movements,
                    round(confidence, 4),
                    tuple(approaches + movements),
                )
            )
        return phases

    def _fill_empty_states(
        self,
        state: list[tuple[int, ...]],
        score: np.ndarray,
    ) -> list[tuple[int, ...]]:
        result = state[:]
        for idx, members in enumerate(result):
            if members:
                continue
            best = int(np.argmax(score[:, idx]))
            result[idx] = (best,)
        return result

    @staticmethod
    def _phase_separation(score: np.ndarray, members: tuple[int, ...], start: int, end: int) -> float:
        active_mean = float(np.mean(score[list(members), start:end])) if members else 0.0
        inactive = [idx for idx in range(score.shape[0]) if idx not in members]
        if not inactive:
            return active_mean
        inactive_mean = float(np.mean(score[inactive, start:end]))
        return float(np.clip(active_mean - inactive_mean + 0.5, 0.0, 1.0))

    @staticmethod
    def _movements(
        frame: pd.DataFrame,
        cycle: float,
        start: float,
        end: float,
        active: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not active:
            return ()
        pos = np.mod(pd.to_numeric(frame["t_s"], errors="coerce"), cycle)
        mask = ((pos >= start) & (pos < end)) if start <= end else ((pos >= start) | (pos < end))
        mask &= frame["zone_in"].astype(str).isin(active)
        return tuple(frame.loc[mask, "movement"].astype(str).value_counts().head(8).index.tolist())

    @staticmethod
    def _smooth(values: np.ndarray) -> np.ndarray:
        if len(values) < 3:
            return values
        padded = np.r_[values[-1], values, values[0]]
        return np.convolve(padded, np.array([0.25, 0.5, 0.25]), mode="valid")

    @staticmethod
    def _similarities(release: np.ndarray) -> dict[str, dict[str, float]]:
        centered = release - release.mean(axis=1, keepdims=True)
        norms = np.linalg.norm(centered, axis=1)
        result: dict[str, dict[str, float]] = {}
        for i, left in enumerate(APPROACHES):
            result[left] = {}
            for j, right in enumerate(APPROACHES):
                if i == j or norms[i] <= MIN_SIGNAL_STD or norms[j] <= MIN_SIGNAL_STD:
                    continue
                result[left][right] = round(float(np.dot(centered[i], centered[j]) / (norms[i] * norms[j])), 4)
        return result


def discover_phases(frame: pd.DataFrame, cycle_seconds: float) -> PhaseDiscoveryResult:
    return PhaseDiscovery().discover(frame, cycle_seconds=cycle_seconds)
