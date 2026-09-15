from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks


MIN_WAIT_S = 5.0
SIGNAL_BIN_S = 2.0


def load_trajectories(path: Path) -> pd.DataFrame:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for trajectory in data:
        if trajectory.get("category_name") != "car":
            continue
        if not trajectory.get("zone_in") or not trajectory.get("zone_out"):
            continue
        if trajectory.get("millis") is None:
            continue

        rows.append(
            {
                "vehicle_id": trajectory["id"],
                "millis": trajectory["millis"],
                "movement": f'{trajectory["zone_in"]}->{trajectory["zone_out"]}',
                "wait_s": (trajectory.get("stay_duration_millis") or 0) / 1000.0,
                "speed": trajectory.get("speed"),
                "max_speed": trajectory.get("max_speed"),
                "distance": trajectory.get("distance"),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("No usable car trajectories found")

    frame["t_s"] = (frame["millis"] - frame["millis"].min()) / 1000.0
    frame["delayed"] = frame["wait_s"] >= MIN_WAIT_S
    frame["release_weight"] = np.maximum(frame["wait_s"] - MIN_WAIT_S, 0.0)
    return frame


def estimate_cycle(frame: pd.DataFrame) -> tuple[float, float, list[dict[str, float]]]:
    n_bins = int(np.ceil(frame["t_s"].max() / SIGNAL_BIN_S)) + 1
    signal = np.zeros(n_bins)

    for _, row in frame[frame["delayed"]].iterrows():
        signal[int(row["t_s"] // SIGNAL_BIN_S)] += row["release_weight"]

    signal = gaussian_filter1d(signal, sigma=1.2)
    centered = signal - signal.mean()
    autocorr = np.correlate(centered, centered, mode="full")[len(centered) - 1 :]
    lags = np.arange(len(autocorr)) * SIGNAL_BIN_S

    mask = (lags >= 60) & (lags <= 140)
    if not mask.any() or autocorr[0] <= 0:
        raise RuntimeError("Could not estimate a traffic cycle")

    local = autocorr[mask]
    cycle = float(lags[mask][np.argmax(local)])
    strength = float(autocorr[int(cycle / SIGNAL_BIN_S)] / autocorr[0])

    peaks, _ = find_peaks(
        local,
        distance=max(1, int(15 / SIGNAL_BIN_S)),
        prominence=max(1e-9, local.max() * 0.03),
    )
    candidates = sorted(
        (
            {
                "period_s": round(float(lags[mask][idx]), 1),
                "strength": round(float(local[idx] / autocorr[0]), 3),
            }
            for idx in peaks
        ),
        key=lambda item: item["strength"],
        reverse=True,
    )[:10]

    return cycle, strength, candidates


def build_movement_profiles(
    frame: pd.DataFrame,
    cycle_s: float,
    phase_bin_s: float = 2.0,
    top_movements: int = 12,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    dominant = frame["movement"].value_counts().head(top_movements).index.tolist()
    phase_centers = np.arange(phase_bin_s / 2, cycle_s, phase_bin_s)

    profiles: dict[str, np.ndarray] = {}
    delayed = frame[frame["delayed"]].copy()
    delayed["cycle_phase_s"] = delayed["t_s"] % cycle_s

    for movement in dominant:
        profile = np.zeros(len(phase_centers))
        group = delayed[delayed["movement"] == movement]
        for _, row in group.iterrows():
            idx = int(row["cycle_phase_s"] // phase_bin_s)
            if idx < len(profile):
                profile[idx] += row["release_weight"]

        pad = min(8, max(1, len(profile) // 4))
        profile = gaussian_filter1d(
            np.r_[profile[-pad:], profile, profile[:pad]], sigma=1.5
        )[pad:-pad]
        profiles[movement] = profile

    raw = pd.DataFrame(profiles, index=phase_centers).T
    normalized = raw.div(raw.max(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    return raw, normalized, phase_centers


def detect_phase_transitions(
    profiles: pd.DataFrame, phase_centers: np.ndarray
) -> list[dict[str, float]]:
    if profiles.empty:
        return []

    signal = gaussian_filter1d(profiles.sum(axis=0).to_numpy(), sigma=1.5)
    peak_indices, _ = find_peaks(
        signal,
        distance=max(1, int(12 / 2.0)),
        prominence=max(0.01, signal.max() * 0.08),
    )

    if signal.max() <= 0:
        return []

    return [
        {
            "phase_s": round(float(phase_centers[idx]), 1),
            "relative_strength": round(float(signal[idx] / signal.max()), 3),
        }
        for idx in peak_indices
    ]


def analyze(path: Path) -> dict:
    frame = load_trajectories(path)
    cycle_s, cycle_strength, cycle_candidates = estimate_cycle(frame)
    raw_profiles, profiles, phase_centers = build_movement_profiles(frame, cycle_s)
    transitions = detect_phase_transitions(raw_profiles, phase_centers)

    return {
        "mode": "unsupervised_baseline",
        "statistics": {
            "cars_used": int(len(frame)),
            "duration_s": round(float(frame["t_s"].max()), 2),
            "unique_movements": int(frame["movement"].nunique()),
        },
        "cycle": {
            "estimated_seconds": round(cycle_s, 2),
            "autocorrelation_strength": round(cycle_strength, 3),
            "candidates": cycle_candidates,
        },
        "candidate_phase_transitions": transitions,
        "movement_profiles": [
            {
                "movement": movement,
                "peak_phase_s": round(float(profiles.loc[movement].idxmax()), 1),
                "peak_strength": round(float(profiles.loc[movement].max()), 3),
            }
            for movement in profiles.index
        ],
        "warning": (
            "This baseline infers recurring traffic-flow structure. "
            "Ground-truth signal phases are required to validate classification accuracy."
        ),
    }
