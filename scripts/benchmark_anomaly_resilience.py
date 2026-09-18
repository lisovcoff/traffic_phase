from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import zipfile

from app.core.anomaly_inference import AnomalyAwareSignalInference
from app.core.anomaly_profile import TrafficBaselineProfile
from app.core.event_cycle_estimator import estimate_event_cycle
from app.core.event_phase_discovery import EventPhaseDiscovery
from app.core.preprocessing import load_trajectory_file
from app.core.signal_state_estimator import SignalStateEstimator
from app.core.trajectory_events import extract_trajectory_events
from app.core.trajectory_geometry import build_trajectory_geometry


def load_events(path: Path):
    if path.suffix.lower() == ".json":
        trajectories = load_trajectory_file(path)
        events = []
        for trajectory in trajectories:
            events.extend(
                extract_trajectory_events(
                    trajectory,
                    build_trajectory_geometry(trajectory.to_record()),
                )
            )
        return events
    if path.suffix.lower() != ".zip":
        raise ValueError(f"unsupported input: {path}")

    events = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".json"):
                continue
            with archive.open(name) as handle:
                payload = json.load(handle)
            with tempfile.NamedTemporaryFile(
                suffix=".json", mode="w", encoding="utf-8", delete=False
            ) as tmp:
                json.dump(payload, tmp)
                temp_path = Path(tmp.name)
            try:
                trajectories = load_trajectory_file(temp_path)
                for trajectory in trajectories:
                    events.extend(
                        extract_trajectory_events(
                            trajectory,
                            build_trajectory_geometry(trajectory.to_record()),
                        )
                    )
            finally:
                temp_path.unlink(missing_ok=True)
    return events


def summarize(events, baseline):
    cycle = estimate_event_cycle(events).estimate
    phase_model = EventPhaseDiscovery().discover(
        events,
        cycle_seconds=cycle.cycle_seconds,
    )
    origin = min(event.timestamp_ms for event in events)
    end = max(event.timestamp_ms for event in events)
    duration_s = max(0.0, (end - origin) / 1000.0)
    estimator = SignalStateEstimator(phase_model, event_origin_ms=origin)
    aware = AnomalyAwareSignalInference(phase_model, baseline)
    rows = []
    for timestamp_s in range(0, int(duration_s) + 1, 30):
        result = estimator.estimate(float(timestamp_s), events)
        rows.append(
            aware.estimate(
                result,
                events,
                current_time_s=float(timestamp_s),
                recent_window_s=baseline.window_seconds,
                origin_ms=origin,
            )
        )
    scores = [row.indicators.anomaly_score for row in rows]
    confidences = [row.signal.phase_confidence for row in rows]
    return {
        "cycle_seconds": cycle.cycle_seconds,
        "phase_count": len(phase_model.phases),
        "mean_anomaly_score": sum(scores) / len(scores),
        "max_anomaly_score": max(scores),
        "mean_phase_confidence": sum(confidences) / len(confidences),
        "conditions": sorted({row.indicators.condition.value for row in rows}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", nargs="+", type=Path, required=True)
    parser.add_argument("--scenario", nargs="+", type=Path, required=True)
    args = parser.parse_args()

    reference_events = []
    for path in args.baseline:
        reference_events.extend(load_events(path))
    profile = TrafficBaselineProfile.from_events(
        reference_events,
        window_seconds=12.0,
        source=";".join(str(path) for path in args.baseline),
    )
    report = {
        "baseline": profile.to_dict(),
        "scenarios": {
            str(path): summarize(load_events(path), profile)
            for path in args.scenario
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
