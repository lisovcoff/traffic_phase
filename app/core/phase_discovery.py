"""Legacy trajectory/profile phase discovery for comparison tests only.

The production API uses app.core.event_phase_discovery.EventPhaseDiscovery.
Keep this module for historical benchmark/regression comparisons; do not add
new production imports from it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

APPROACHES = ("N", "S", "E", "W")
NS_PHASE = ("N", "S")
EW_PHASE = ("E", "W")
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
        return {
            "cycle_seconds": self.cycle_seconds,
            "bin_seconds": self.bin_seconds,
            "phases": [phase.to_dict() for phase in self.phases],
            "profiles": [asdict(profile) for profile in self.profiles],
            "similarities": self.similarities,
        }


class PhaseDiscovery:
    """Infer two opposing signal phases from actual movement events.

    The MVP assumes exactly two signal groups: N/S green versus E/W red,
    or E/W green versus N/S red.

    Movement is positive evidence that an approach received green around the
    trajectory timestamp. A long stay/wait duration is not treated as direct
    red evidence because it describes the whole trajectory, not the signal
    state at one instant. Bins without moving trajectories carry no evidence.
    """

    def __init__(
        self,
        *,
        bin_seconds: float = 2.0,
        min_phase_seconds: float = DEFAULT_MIN_PHASE_SECONDS,
        transition_penalty: float = 0.08,
    ) -> None:
        if bin_seconds <= 0 or min_phase_seconds < bin_seconds:
            raise ValueError("invalid phase-discovery timing parameters")
        if transition_penalty < 0:
            raise ValueError("transition_penalty must be non-negative")
        self.bin_seconds = float(bin_seconds)
        self.min_phase_bins = max(1, int(round(min_phase_seconds / bin_seconds)))
        self.transition_penalty = float(transition_penalty)

    def build_profiles(
        self,
        frame: pd.DataFrame,
        *,
        cycle_seconds: float,
    ) -> tuple[list[Profile], np.ndarray, np.ndarray]:
        self._validate_frame(frame)
        n_bins = max(1, int(round(cycle_seconds / self.bin_seconds)))
        centers = np.arange(n_bins, dtype=float) * self.bin_seconds
        pair_support = np.full((2, n_bins), np.nan, dtype=float)

        per_cycle = self._cycle_evidence(frame, cycle_seconds, n_bins)
        if per_cycle.shape[0]:
            support_ns = self._robust_cycle_consensus(per_cycle[:, :, 0])
            pair_support = np.vstack((support_ns, 1.0 - support_ns))

        profiles = [
            Profile("NS", "moving_support", tuple(np.nan_to_num(pair_support[0], nan=0.0))),
            Profile("EW", "moving_support", tuple(np.nan_to_num(pair_support[1], nan=0.0))),
        ]
        return profiles, centers, pair_support

    def discover(self, frame: pd.DataFrame, *, cycle_seconds: float) -> PhaseDiscoveryResult:
        profiles, centers, pair_support = self.build_profiles(frame, cycle_seconds=cycle_seconds)
        states = self._best_two_phase_schedule(pair_support)
        phases = self._build_phases(states, pair_support, frame, cycle_seconds, centers)
        similarities = self._similarities(pair_support)
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

    @staticmethod
    def _moving_mask(frame: pd.DataFrame) -> np.ndarray:
        if "move_s" in frame.columns:
            move_s = pd.to_numeric(frame["move_s"], errors="coerce")
            if bool(move_s.notna().any()):
                return move_s.fillna(0.0).to_numpy(float) > 0.0
        return ~frame["stopped"].astype(bool).to_numpy()

    def _cycle_evidence(
        self,
        frame: pd.DataFrame,
        cycle_seconds: float,
        n_bins: int,
    ) -> np.ndarray:
        if frame.empty:
            return np.empty((0, n_bins, 1), dtype=float)

        t = pd.to_numeric(frame["t_s"], errors="coerce").fillna(0.0).to_numpy(float)
        cycles = np.floor(np.maximum(t, 0.0) / cycle_seconds).astype(int)
        cycle_count = int(cycles.max()) + 1
        bins = np.minimum(
            (np.mod(np.maximum(t, 0.0), cycle_seconds) / self.bin_seconds).astype(int),
            n_bins - 1,
        )
        approaches = frame["zone_in"].astype(str).to_numpy()
        moving = self._moving_mask(frame)

        counts = np.zeros((cycle_count, n_bins, len(APPROACHES)), dtype=float)
        approach_index = {approach: idx for idx, approach in enumerate(APPROACHES)}
        for cycle_id, bin_id, approach, is_moving in zip(cycles, bins, approaches, moving):
            if not is_moving:
                continue
            idx = approach_index.get(approach)
            if idx is not None:
                counts[cycle_id, bin_id, idx] += 1.0

        pair_support: list[np.ndarray] = []
        for cycle_id in range(cycle_count):
            cycle = counts[cycle_id]
            ns = cycle[:, 0] + cycle[:, 1]
            ew = cycle[:, 2] + cycle[:, 3]
            total = ns + ew
            support = np.divide(
                ns,
                total,
                out=np.full(n_bins, np.nan),
                where=total > 0,
            )
            pair_support.append(support)

        return np.stack(pair_support, axis=0)[..., None]

    @staticmethod
    def _robust_cycle_consensus(values: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore"):
            return np.nanmedian(values, axis=0)

    def _best_two_phase_schedule(self, pair_support: np.ndarray) -> np.ndarray:
        ns = np.asarray(pair_support[0], dtype=float)
        ew = np.asarray(pair_support[1], dtype=float)
        n_bins = len(ns)
        if n_bins == 0:
            return np.zeros(0, dtype=np.int8)
        if n_bins < 2 * self.min_phase_bins:
            raise ValueError("cycle is too short for two signal phases")

        best_score = -np.inf
        best_start = 0
        best_length = max(self.min_phase_bins, n_bins // 2)
        doubled_ns = np.r_[ns, ns]
        doubled_ew = np.r_[ew, ew]
        ns_prefix = np.concatenate(([0.0], np.cumsum(np.nan_to_num(doubled_ns, nan=0.0))))
        ew_prefix = np.concatenate(([0.0], np.cumsum(np.nan_to_num(doubled_ew, nan=0.0))))
        max_length = n_bins - self.min_phase_bins

        for start in range(n_bins):
            for length in range(self.min_phase_bins, max_length + 1):
                end = start + length
                ns_inside = ns_prefix[end] - ns_prefix[start]
                ew_inside = ew_prefix[end] - ew_prefix[start]
                ew_total = ew_prefix[start + n_bins] - ew_prefix[start]
                score = ns_inside + (ew_total - ew_inside) - 2.0 * self.transition_penalty
                if score > best_score:
                    best_score = score
                    best_start = start
                    best_length = length

        states = np.ones(n_bins, dtype=np.int8)
        for offset in range(best_length):
            states[(best_start + offset) % n_bins] = 0
        return states

    def _build_phases(
        self,
        states: np.ndarray,
        pair_support: np.ndarray,
        frame: pd.DataFrame,
        cycle_seconds: float,
        centers: np.ndarray,
    ) -> list[Phase]:
        if len(states) == 0:
            return []

        transitions = [
            i for i in range(len(states))
            if states[i] != states[(i - 1) % len(states)]
        ]
        if not transitions:
            active = NS_PHASE if int(states[0]) == 0 else EW_PHASE
            values = pair_support[int(states[0])]
            confidence = float(np.nanmean(values)) if np.isfinite(values).any() else 0.0
            return [self._make_phase(1, 0.0, cycle_seconds, active, confidence, frame, cycle_seconds)]

        if len(transitions) > 2:
            contrasts = [
                abs(float(np.nan_to_num(pair_support[0, index] - pair_support[1, index], nan=0.0)))
                for index in transitions
            ]
            transitions = sorted(item for _, item in sorted(zip(contrasts, transitions), reverse=True)[:2])

        if len(transitions) == 1:
            transitions.append((transitions[0] + len(states) // 2) % len(states))
            transitions.sort()

        boundary_a, boundary_b = transitions[:2]
        state_a = int(states[(boundary_a + 1) % len(states)])
        state_b = 1 - state_a
        intervals = (
            (boundary_a, boundary_b, state_a),
            (boundary_b, boundary_a, state_b),
        )

        phases: list[Phase] = []
        for phase_id, (start_idx, end_idx, state) in enumerate(intervals, 1):
            start_s = float(centers[start_idx])
            end_s = float(centers[end_idx])
            indices = self._interval_indices(start_idx, end_idx, len(states))
            values = pair_support[state, indices] if indices else np.array([], dtype=float)
            confidence = float(np.nanmean(values)) if values.size and np.isfinite(values).any() else 0.0
            active = NS_PHASE if state == 0 else EW_PHASE
            phases.append(
                self._make_phase(
                    phase_id,
                    start_s,
                    end_s,
                    active,
                    confidence,
                    frame,
                    cycle_seconds,
                )
            )
        return phases

    @staticmethod
    def _interval_indices(start: int, end: int, size: int) -> list[int]:
        if start == end:
            return list(range(size))
        if start < end:
            return list(range(start, end))
        return list(range(start, size)) + list(range(0, end))

    def _make_phase(
        self,
        phase_id: int,
        start: float,
        end: float,
        active: tuple[str, ...],
        confidence: float,
        frame: pd.DataFrame,
        cycle_seconds: float,
    ) -> Phase:
        movements = self._movements(frame, cycle_seconds, start % cycle_seconds, end % cycle_seconds, active)
        return Phase(
            phase_id=phase_id,
            phase_start=round(start % cycle_seconds, 2),
            phase_end=round(end % cycle_seconds, 2),
            active_approaches=active,
            active_movements=movements,
            confidence=round(float(np.clip(confidence, 0.0, 1.0)), 4),
            members=tuple(active + movements),
        )

    @staticmethod
    def _movements(
        frame: pd.DataFrame,
        cycle: float,
        start: float,
        end: float,
        active: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not active or frame.empty:
            return ()
        pos = np.mod(pd.to_numeric(frame["t_s"], errors="coerce"), cycle)
        mask = ((pos >= start) & (pos < end)) if start <= end else ((pos >= start) | (pos < end))
        mask &= frame["zone_in"].astype(str).isin(active)
        return tuple(frame.loc[mask, "movement"].astype(str).value_counts().head(8).index.tolist())

    @staticmethod
    def _similarities(pair_support: np.ndarray) -> dict[str, dict[str, float]]:
        ns = np.asarray(pair_support[0], dtype=float)
        ew = np.asarray(pair_support[1], dtype=float)
        valid = np.isfinite(ns) & np.isfinite(ew)
        if valid.sum() < 2 or np.std(ns[valid]) <= MIN_SIGNAL_STD:
            correlation = -1.0
        else:
            correlation = float(np.corrcoef(ns[valid], ew[valid])[0, 1])
        correlation = round(correlation, 4)
        return {"NS": {"EW": correlation}, "EW": {"NS": correlation}}


def discover_phases(frame: pd.DataFrame, cycle_seconds: float) -> PhaseDiscoveryResult:
    return PhaseDiscovery().discover(frame, cycle_seconds=cycle_seconds)
