from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

import numpy as np
import pandas as pd

APPROACHES = ("N", "S", "E", "W")
MIN_SIGNAL_STD = 1e-9
DEFAULT_MIN_PHASE_SECONDS = 8.0


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
        return {"cycle_seconds": self.cycle_seconds, "bin_seconds": self.bin_seconds,
                "phases": [p.to_dict() for p in self.phases],
                "profiles": [asdict(p) for p in self.profiles], "similarities": self.similarities}


class PhaseDiscovery:
    """Infer temporal signal regimes across a folded cycle without a fixed phase order."""

    def __init__(self, *, bin_seconds: float = 2.0, min_phase_seconds: float = DEFAULT_MIN_PHASE_SECONDS,
                 release_weight: float = 1.0, queue_weight: float = 0.25, transition_cost: float = 0.35) -> None:
        if bin_seconds <= 0 or min_phase_seconds < bin_seconds:
            raise ValueError("invalid phase-discovery timing parameters")
        self.bin_seconds = bin_seconds
        self.min_phase_bins = max(1, int(round(min_phase_seconds / bin_seconds)))
        self.release_weight = release_weight
        self.queue_weight = queue_weight
        self.transition_cost = transition_cost

    def build_profiles(self, frame: pd.DataFrame, *, cycle_seconds: float) -> tuple[list[Profile], np.ndarray]:
        self._validate_frame(frame)
        n_bins = max(1, int(round(cycle_seconds / self.bin_seconds)))
        centers = np.arange(n_bins, dtype=float) * self.bin_seconds
        t = np.mod(pd.to_numeric(frame["t_s"], errors="coerce").fillna(0.0).to_numpy(float), cycle_seconds)
        ids = np.minimum((t / cycle_seconds * n_bins).astype(int), n_bins - 1)
        approaches = frame["zone_in"].astype(str).to_numpy()
        release = pd.to_numeric(frame["release_weight"], errors="coerce").fillna(0.0).to_numpy(float)
        stopped = frame["stopped"].astype(float).to_numpy()
        movements = frame["movement"].astype(str).to_numpy()
        profiles: list[Profile] = []
        for approach in APPROACHES:
            mask = approaches == approach
            rel = np.bincount(ids[mask], weights=release[mask], minlength=n_bins).astype(float)
            q = np.bincount(ids[mask], weights=stopped[mask], minlength=n_bins).astype(float)
            profiles.extend((Profile(approach, "release", tuple(self._smooth(rel))),
                             Profile(f"{approach}:queue", "queue", tuple(self._smooth(q)))))
        for movement in sorted(set(movements)):
            mask = movements == movement
            vals = np.bincount(ids[mask], weights=release[mask], minlength=n_bins).astype(float)
            if vals.sum() > 0:
                profiles.append(Profile(movement, "movement", tuple(self._smooth(vals))))
        return profiles, centers

    def discover(self, frame: pd.DataFrame, *, cycle_seconds: float) -> PhaseDiscoveryResult:
        profiles, centers = self.build_profiles(frame, cycle_seconds=cycle_seconds)
        rel = np.vstack([self._values(profiles, a, "release") for a in APPROACHES])
        queue = np.vstack([self._values(profiles, f"{a}:queue", "queue") for a in APPROACHES])
        score = self._green_score(rel, queue)
        labels = self._viterbi(score)
        labels = self._merge_short(labels)
        phases = self._phases(labels, score, frame, cycle_seconds, centers)
        similarities = self._similarities(rel)
        return PhaseDiscoveryResult(float(cycle_seconds), self.bin_seconds, tuple(phases), tuple(profiles), similarities)

    def _validate_frame(self, frame: pd.DataFrame) -> None:
        required = {"t_s", "zone_in", "movement", "release_weight", "stopped"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"missing required columns: {sorted(missing)}")

    @staticmethod
    def _values(profiles: list[Profile], key: str, kind: str) -> np.ndarray:
        for p in profiles:
            if p.key == key and p.kind == kind:
                return np.asarray(p.values, dtype=float)
        raise RuntimeError(f"missing profile {key}/{kind}")

    def _smooth(self, values: np.ndarray) -> np.ndarray:
        if len(values) < 3:
            return values
        padded = np.r_[values[-1], values, values[0]]
        return np.convolve(padded, np.array([0.25, 0.5, 0.25]), mode="valid")

    @staticmethod
    def _normalize(values: np.ndarray) -> np.ndarray:
        med = np.median(values, axis=1, keepdims=True)
        scale = np.percentile(values, 90, axis=1, keepdims=True) - med
        scale = np.maximum(scale, MIN_SIGNAL_STD)
        return np.clip((values - med) / scale, -1.0, 1.5)

    def _green_score(self, release: np.ndarray, queue: np.ndarray) -> np.ndarray:
        return self.release_weight * self._normalize(release) - self.queue_weight * self._normalize(queue)

    @staticmethod
    def _states() -> list[tuple[int, ...]]:
        return [c for size in range(1, len(APPROACHES) + 1) for c in combinations(range(len(APPROACHES)), size)]

    @staticmethod
    def _emission(column: np.ndarray, state: tuple[int, ...]) -> float:
        active = set(state)
        return float(sum(column[i] for i in state) - 0.25 * sum(max(0.0, column[i]) for i in range(len(column)) if i not in active)
                     - 0.08 * max(0, len(state) - 2))

    def _viterbi(self, score: np.ndarray) -> list[tuple[int, ...]]:
        states = self._states()
        n = score.shape[1]
        dp = np.full((n, len(states)), -np.inf)
        back = np.zeros((n, len(states)), dtype=int)
        for j, state in enumerate(states):
            dp[0, j] = self._emission(score[:, 0], state)
        for t in range(1, n):
            for j, state in enumerate(states):
                best = -np.inf
                best_i = 0
                for i, prev in enumerate(states):
                    overlap = len(set(state) & set(prev)) / max(1, len(set(state) | set(prev)))
                    value = dp[t - 1, i] - self.transition_cost * (1.0 - overlap) + self._emission(score[:, t], state)
                    if value > best:
                        best, best_i = value, i
                dp[t, j], back[t, j] = best, best_i
        idx = int(np.argmax(dp[-1]))
        labels = [states[idx]]
        for t in range(n - 1, 0, -1):
            idx = int(back[t, idx])
            labels.append(states[idx])
        return list(reversed(labels))

    def _merge_short(self, labels: list[tuple[int, ...]]) -> list[tuple[int, ...]]:
        result = labels[:]
        changed = True
        while changed:
            changed = False
            i = 0
            while i < len(result):
                j = i + 1
                while j < len(result) and result[j] == result[i]:
                    j += 1
                if j - i < self.min_phase_bins and len(result) > 1:
                    left = result[i - 1] if i else None
                    right = result[j] if j < len(result) else None
                    replacement = left if left == right and left is not None else (left or right)
                    if replacement is not None:
                        result[i:j] = [replacement] * (j - i)
                        changed = True
                        break
                i = j
        return result

    def _phases(self, labels: list[tuple[int, ...]], score: np.ndarray, frame: pd.DataFrame,
                cycle_seconds: float, centers: np.ndarray) -> list[Phase]:
        runs: list[tuple[int, int, tuple[int, ...]]] = []
        i = 0
        while i < len(labels):
            j = i + 1
            while j < len(labels) and labels[j] == labels[i]:
                j += 1
            runs.append((i, j, labels[i]))
            i = j
        phases: list[Phase] = []
        for pid, (a, b, state) in enumerate(runs, 1):
            start_s = float(centers[a])
            end_s = float(min(cycle_seconds, centers[b - 1] + self.bin_seconds))
            active = tuple(APPROACHES[i] for i in state)
            vals = score[list(state), a:b]
            confidence = float(np.clip(np.mean((vals + 1.0) / 2.5), 0.0, 1.0))
            movements = self._movements(frame, cycle_seconds, start_s, end_s, active)
            phases.append(Phase(pid, round(start_s, 2), round(end_s, 2), active, movements,
                                round(confidence, 4), tuple(active + movements)))
        return phases

    @staticmethod
    def _movements(frame: pd.DataFrame, cycle: float, start: float, end: float, active: tuple[str, ...]) -> tuple[str, ...]:
        pos = np.mod(pd.to_numeric(frame["t_s"], errors="coerce"), cycle)
        mask = ((pos >= start) & (pos < end)) if start <= end else ((pos >= start) | (pos < end))
        mask &= frame["zone_in"].astype(str).isin(active)
        return tuple(frame.loc[mask, "movement"].astype(str).value_counts().head(8).index.tolist())

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
