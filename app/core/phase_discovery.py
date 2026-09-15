from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

APPROACHES = ("N", "S", "E", "W")
MIN_SIGNAL_STD = 1e-9
DEFAULT_MIN_PHASE_SECONDS = 8.0
DEFAULT_ACTIVITY_THRESHOLD = 0.45


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
    """Infer recurring signal phases from delay, stops and throughput evidence.

    A trajectory's wait duration is treated as delay/queue evidence, not as a direct
    green-release signal. Phase inference is based on a robust consensus across repeated
    cycles so single-cycle demand fluctuations do not define the phase schedule.
    """

    def __init__(
        self,
        *,
        bin_seconds: float = 2.0,
        min_phase_seconds: float = DEFAULT_MIN_PHASE_SECONDS,
        queue_weight: float = 0.65,
        stop_weight: float = 0.35,
        activity_threshold: float = DEFAULT_ACTIVITY_THRESHOLD,
        min_cycles: int = 3,
    ) -> None:
        if bin_seconds <= 0 or min_phase_seconds < bin_seconds:
            raise ValueError("invalid phase-discovery timing parameters")
        if queue_weight < 0 or stop_weight < 0 or queue_weight + stop_weight <= 0:
            raise ValueError("invalid queue/stop weights")
        if not 0 < activity_threshold < 1:
            raise ValueError("activity_threshold must be in (0, 1)")
        if min_cycles < 1:
            raise ValueError("min_cycles must be positive")
        self.bin_seconds = bin_seconds
        self.min_phase_bins = max(1, int(round(min_phase_seconds / bin_seconds)))
        total = queue_weight + stop_weight
        self.queue_weight = queue_weight / total
        self.stop_weight = stop_weight / total
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
            cycles = self._approach_cycle_matrix(frame, cycle_seconds, n_bins, approach)
            flow = self._robust_consensus(cycles[:, :, 0])
            wait = self._robust_consensus(cycles[:, :, 1])
            stopped = self._robust_consensus(cycles[:, :, 2])
            profiles.extend(
                (
                    Profile(approach, "flow", tuple(self._smooth(flow))),
                    Profile(f"{approach}:wait", "wait", tuple(self._smooth(wait))),
                    Profile(f"{approach}:stopped", "stopped", tuple(self._smooth(stopped))),
                )
            )

        return profiles, centers

    def discover(self, frame: pd.DataFrame, *, cycle_seconds: float) -> PhaseDiscoveryResult:
        profiles, centers = self.build_profiles(frame, cycle_seconds=cycle_seconds)
        flow = np.vstack([self._values(profiles, approach, "flow") for approach in APPROACHES])
        wait = np.vstack([self._values(profiles, f"{approach}:wait", "wait") for approach in APPROACHES])
        stopped = np.vstack([self._values(profiles, f"{approach}:stopped", "stopped") for approach in APPROACHES])

        evidence = self._signal_evidence(flow, wait, stopped)
        active = self._stabilize_activity(evidence["green"] >= self.activity_threshold)
        phases = self._phases(active, evidence, frame, cycle_seconds, centers)

        similarities = self._similarities(evidence["green"])
        return PhaseDiscoveryResult(
            float(cycle_seconds),
            self.bin_seconds,
            tuple(phases),
            tuple(profiles),
            similarities,
        )

    def _validate_frame(self, frame: pd.DataFrame) -> None:
        required = {"t_s", "zone_in", "movement", "wait_s", "stopped"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"missing required columns: {sorted(missing)}")

    def _approach_cycle_matrix(
        self,
        frame: pd.DataFrame,
        cycle_seconds: float,
        n_bins: int,
        approach: str,
    ) -> np.ndarray:
        t = pd.to_numeric(frame["t_s"], errors="coerce").fillna(0.0).to_numpy(float)
        cycles = np.floor(np.maximum(t, 0.0) / cycle_seconds).astype(int)
        cycle_count = int(cycles.max()) + 1 if len(cycles) else 1
        matrix = np.zeros((cycle_count, n_bins, 3), dtype=float)
        mask = frame["zone_in"].astype(str).to_numpy() == approach
        if not mask.any():
            return matrix[: max(1, min(cycle_count, self.min_cycles))]

        wait = pd.to_numeric(frame["wait_s"], errors="coerce").fillna(0.0).to_numpy(float)
        stopped = frame["stopped"].astype(float).to_numpy()
        bins = self._bin_indices(t, cycle_seconds, n_bins)
        for cycle_id, bin_id, wait_value, stopped_value, selected in zip(
            cycles, bins, wait, stopped, mask
        ):
            if selected:
                matrix[cycle_id, bin_id, 0] += 1.0
                matrix[cycle_id, bin_id, 1] += max(0.0, float(wait_value))
                matrix[cycle_id, bin_id, 2] += max(0.0, float(stopped_value))
        return matrix

    @staticmethod
    def _bin_indices(t: np.ndarray, cycle_seconds: float, n_bins: int) -> np.ndarray:
        folded = np.mod(t, cycle_seconds)
        return np.minimum((folded / cycle_seconds * n_bins).astype(int), n_bins - 1)

    @staticmethod
    def _robust_consensus(matrix: np.ndarray) -> np.ndarray:
        if matrix.size == 0:
            return np.zeros(matrix.shape[-1] if matrix.ndim else 1, dtype=float)
        return np.median(matrix, axis=0)

    @staticmethod
    def _values(profiles: list[Profile], key: str, kind: str) -> np.ndarray:
        for profile in profiles:
            if profile.key == key and profile.kind == kind:
                return np.asarray(profile.values, dtype=float)
        raise RuntimeError(f"missing profile {key}/{kind}")

    def _signal_evidence(
        self,
        flow: np.ndarray,
        wait: np.ndarray,
        stopped: np.ndarray,
    ) -> dict[str, np.ndarray]:
        flow_strength = self._rowwise_activity(flow)
        mean_wait = wait / np.maximum(flow, 1.0)
        wait_pressure = self._rowwise_activity(mean_wait)
        stop_pressure = self._rowwise_activity(stopped / np.maximum(flow, 1.0))
        red = self.queue_weight * wait_pressure + self.stop_weight * stop_pressure

        # Throughput is only useful as green evidence when the approach actually has
        # traffic. Empty bins are therefore kept weak rather than interpreted as green.
        green = flow_strength * (1.0 - red)
        green = self._smooth_matrix(green)
        red = self._smooth_matrix(red)
        return {"green": np.clip(green, 0.0, 1.0), "red": np.clip(red, 0.0, 1.0)}

    @staticmethod
    def _rowwise_activity(values: np.ndarray) -> np.ndarray:
        baseline = np.median(values, axis=1, keepdims=True)
        scale = np.percentile(values, 90, axis=1, keepdims=True) - baseline
        scale = np.maximum(scale, MIN_SIGNAL_STD)
        activity = np.clip((values - baseline) / scale, 0.0, 1.0)
        return activity

    def _stabilize_activity(self, active: np.ndarray) -> np.ndarray:
        result = active.copy()
        result = self._remove_short_runs(result)
        result = self._fill_small_gaps(result)
        return result

    def _remove_short_runs(self, active: np.ndarray) -> np.ndarray:
        result = active.copy()
        for approach_idx in range(result.shape[0]):
            row = result[approach_idx]
            i = 0
            while i < len(row):
                j = i + 1
                while j < len(row) and row[j] == row[i]:
                    j += 1
                if row[i] and j - i < self.min_phase_bins:
                    left = row[i - 1] if i else False
                    right = row[j] if j < len(row) else False
                    row[i:j] = left or right
                i = j
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
        evidence: dict[str, np.ndarray],
        frame: pd.DataFrame,
        cycle_seconds: float,
        centers: np.ndarray,
    ) -> list[Phase]:
        green = evidence["green"]
        red = evidence["red"]
        states = [tuple(np.flatnonzero(active[:, idx]).tolist()) for idx in range(active.shape[1])]
        states = self._fill_empty_states(states, green)

        runs: list[tuple[int, int, tuple[int, ...]]] = []
        i = 0
        while i < len(states):
            j = i + 1
            while j < len(states) and states[j] == states[i]:
                j += 1
            runs.append((i, j, states[i]))
            i = j

        phases: list[Phase] = []
        for phase_id, (start_idx, end_idx, members) in enumerate(runs, 1):
            start_s = float(centers[start_idx])
            end_s = float(min(cycle_seconds, centers[end_idx - 1] + self.bin_seconds))
            approaches = tuple(APPROACHES[idx] for idx in members)
            member_slice = slice(start_idx, end_idx)
            active_score = float(np.mean(green[list(members), member_slice])) if members else 0.0
            inactive = [idx for idx in range(len(APPROACHES)) if idx not in members]
            inactive_red = float(np.mean(red[inactive, member_slice])) if inactive else 0.0
            confidence = float(np.clip(0.65 * active_score + 0.35 * inactive_red, 0.0, 1.0))
            movements = self._movements(frame, cycle_seconds, start_s, end_s, approaches)
            phases.append(
                Phase(
                    phase_id=phase_id,
                    phase_start=round(start_s, 2),
                    phase_end=round(end_s, 2),
                    active_approaches=approaches,
                    active_movements=movements,
                    confidence=round(confidence, 4),
                    members=tuple(approaches + movements),
                )
            )
        return phases

    @staticmethod
    def _fill_empty_states(states: list[tuple[int, ...]], green: np.ndarray) -> list[tuple[int, ...]]:
        result = states[:]
        for idx, members in enumerate(result):
            if members:
                continue
            strongest = np.argsort(green[:, idx])[-2:]
            result[idx] = tuple(sorted(int(item) for item in strongest if green[item, idx] > 0)) or (int(np.argmax(green[:, idx])),)
        return result

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
    def _similarities(green: np.ndarray) -> dict[str, dict[str, float]]:
        centered = green - green.mean(axis=1, keepdims=True)
        norms = np.linalg.norm(centered, axis=1)
        result: dict[str, dict[str, float]] = {}
        for i, left in enumerate(APPROACHES):
            result[left] = {}
            for j, right in enumerate(APPROACHES):
                if i == j or norms[i] <= MIN_SIGNAL_STD or norms[j] <= MIN_SIGNAL_STD:
                    continue
                result[left][right] = round(float(np.dot(centered[i], centered[j]) / (norms[i] * norms[j])), 4)
        return result

    def _smooth_matrix(self, matrix: np.ndarray) -> np.ndarray:
        return np.vstack([self._smooth(row) for row in matrix])

    @staticmethod
    def _smooth(values: np.ndarray) -> np.ndarray:
        if len(values) < 3:
            return values
        padded = np.r_[values[-1], values, values[0]]
        return np.convolve(padded, np.array([0.25, 0.5, 0.25]), mode="valid")


def discover_phases(frame: pd.DataFrame, cycle_seconds: float) -> PhaseDiscoveryResult:
    return PhaseDiscovery().discover(frame, cycle_seconds=cycle_seconds)
