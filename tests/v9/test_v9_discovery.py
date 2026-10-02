from __future__ import annotations

from array import array
import json
import random
from pathlib import Path
import zipfile

from app.core.v9.events import load_event_streams
from app.core.v9.fit import candidate_metrics
from app.core.v9.v9_discovery import OnlinePhaseTracker, discover_path, discover_records


def _tracks(
    phases,
    cycles=12,
    step=2.0,
    drop=0.0,
    jitter=0.0,
    blocked_stream=None,
):
    rng = random.Random(42)
    base = 1_700_000_000_000
    period = sum(duration for duration, _ in phases)
    tracks = []
    ident = 0

    for cycle in range(cycles):
        cursor = 0.0
        for duration, streams in phases:
            for stream in streams:
                if blocked_stream == stream:
                    continue
                t = cursor + 1.0
                while t < cursor + duration - 1.0:
                    if rng.random() >= drop:
                        ident += 1
                        timestamp = (
                            cycle * period
                            + t
                            + rng.gauss(0.0, jitter)
                        )
                        millis = base + int(
                            round(timestamp * 1000.0)
                        )
                        source, target = stream.split("->", 1)
                        tracks.append(
                            {
                                "category_name": "car",
                                "id": ident,
                                "millis": millis,
                                "zone_in": source,
                                "zone_out": target,
                                "stay_duration_millis": 0,
                                "detections": [
                                    {
                                        "millis": millis,
                                        "zone": source,
                                        "speed": 10.0,
                                    },
                                    {
                                        "millis": millis + 1000,
                                        "zone": target,
                                        "speed": 10.0,
                                    },
                                ],
                            }
                        )
                    t += step
            cursor += duration
    return tracks


def _assert_model(phases, **kwargs):
    result = discover_records(
        _tracks(phases, **kwargs)
    )
    assert (
        result["phase_model_selection"]["selected_phase_count"]
        == len(phases)
    )
    assert (
        abs(
            result["period_inference"]["period_s"]
            - sum(duration for duration, _ in phases)
        )
        <= 2.0
    )
    assert result["schedule"]["baseline_duration_targets_s"]
    return result


def test_v9_two_phase_clean():
    _assert_model(
        [
            (45.0, ["A->B", "B->A"]),
            (55.0, ["C->D", "D->C"]),
        ]
    )


def test_v9_three_phase_uneven():
    _assert_model(
        [
            (20.0, ["A->B", "B->A"]),
            (30.0, ["C->D", "D->C"]),
            (50.0, ["E->F", "F->E"]),
        ]
    )


def test_v9_four_phase():
    _assert_model(
        [
            (15.0, ["A->B", "B->A"]),
            (25.0, ["C->D", "D->C"]),
            (35.0, ["E->F", "F->E"]),
            (45.0, ["G->H", "H->G"]),
        ]
    )


def test_v9_missing_events_and_blocked_stream():
    _assert_model(
        [
            (20.0, ["A->B", "B->A"]),
            (30.0, ["C->D", "D->C"]),
            (50.0, ["E->F", "F->E"]),
        ],
        drop=0.22,
        blocked_stream="E->F",
    )


def test_v9_timestamp_jitter():
    _assert_model(
        [
            (20.0, ["A->B", "B->A"]),
            (30.0, ["C->D", "D->C"]),
            (50.0, ["E->F", "F->E"]),
        ],
        jitter=0.25,
    )


def test_v9_direction_agnostic_stream_names():
    phases = [
        (20.0, ["foo->bar", "bar->foo"]),
        (30.0, ["x->y", "y->x"]),
        (50.0, ["left->right", "right->left"]),
    ]
    result = _assert_model(phases)
    assert all(
        name.startswith("PHASE_")
        for name in result["schedule"]["phase_names"]
    )
    payload = json.dumps(result)
    assert "NS" not in payload
    assert "EW" not in payload


def test_v9_accepts_repository_normalized_records():
    tracks = _tracks(
        [
            (40.0, ["A->B", "B->A"]),
            (60.0, ["C->D", "D->C"]),
        ]
    )
    for track in tracks:
        track.pop("stay_duration_millis", None)
        track["wait_s"] = 0.0
    result = discover_records(tracks)
    assert (
        result["phase_model_selection"]["selected_phase_count"]
        == 2
    )


def test_v9_online_tracker_is_causal():
    result = _assert_model(
        [
            (20.0, ["A->B", "B->A"]),
            (30.0, ["C->D", "D->C"]),
            (50.0, ["E->F", "F->E"]),
        ],
        cycles=10,
    )
    tracker = OnlinePhaseTracker(
        result,
        lookback_s=45.0,
    )
    stream = sorted(
        result["movement_streams"],
        key=lambda name: name,
    )[0]
    base = int(result["analysis_base_timestamp_ms"])

    tracker.observe(
        base + 1000 * 5,
        stream,
    )
    snapshot = tracker.infer(
        base + 1000 * 5,
    )
    assert snapshot["status"] in {
        "SYNCHRONIZED",
        "WARMUP",
    }


def test_v9_discover_path_supports_json_file(tmp_path: Path):
    tracks = _tracks(
        [
            (20.0, ["A->B", "B->A"]),
            (30.0, ["C->D", "D->C"]),
            (50.0, ["E->F", "F->E"]),
        ],
        cycles=8,
    )
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(tracks), encoding="utf-8")

    result = discover_path(path)

    assert result["trajectory_count"] == len(tracks)
    assert result["archive"]["source_file_count"] == 1


def test_v9_discover_path_supports_zip_without_decoding_archive_as_json(tmp_path: Path):
    tracks = _tracks(
        [
            (20.0, ["A->B", "B->A"]),
            (30.0, ["C->D", "D->C"]),
            (50.0, ["E->F", "F->E"]),
        ],
        cycles=8,
    )
    json_bytes = json.dumps(tracks).encode("utf-8")
    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("nested/trajectories.json", json_bytes)

    result = discover_path(zip_path)

    assert result["trajectory_count"] == len(tracks)
    assert result["archive"]["source_file_count"] == 1
    assert "sample.zip" in result["archive"]["source_files"][0]


def test_v9_stream_loader_returns_compact_packed_streams(tmp_path: Path):
    tracks = _tracks(
        [
            (20.0, ["A->B", "B->A"]),
            (30.0, ["C->D", "D->C"]),
            (50.0, ["E->F", "F->E"]),
        ],
        cycles=4,
    )
    path = tmp_path / "compact.json"
    path.write_text(json.dumps(tracks), encoding="utf-8")

    payload = load_event_streams(path)
    by_stream, entry_streams, release_streams, method_counts, release_methods, files, recording_start, base_ms, trajectory_count, event_count = payload

    assert by_stream
    assert all(type(values).__name__ == "array" for values in by_stream.values())
    assert set(by_stream) == set(entry_streams)
    assert isinstance(release_streams, dict)
    assert trajectory_count == len(tracks)
    assert event_count == len(tracks)
    assert recording_start is not None
    assert float(recording_start) <= float(base_ms)


def test_v9_slice_streams_preserves_packed_array():
    from app.core.v9.model import _slice_streams

    values = array("d", [10.0, 11.5, 13.0, 16.0])
    result = _slice_streams({"A->B": values}, 10.0, 16.0)

    assert isinstance(result["A->B"], array)
    assert result["A->B"].typecode == "d"
    assert list(result["A->B"]) == [0.0, 1.5, 3.0]


def test_v9_ignores_non_car_records():
    tracks = _tracks(
        [
            (40.0, ["A->B", "B->A"]),
            (60.0, ["C->D", "D->C"]),
        ],
        cycles=8,
    )
    non_car = dict(tracks[0])
    non_car["category_name"] = "bus"
    tracks_with_noise = tracks + [non_car]
    baseline = discover_records(tracks)
    noisy = discover_records(tracks_with_noise)
    assert noisy["trajectory_count"] == len(tracks_with_noise)
    assert noisy["event_count"] == baseline["event_count"]


def test_v9_canonical_four_leg_phase_cap():
    result = discover_records(
        _tracks(
            [
                (20.0, ["N->S", "S->N"]),
                (30.0, ["E->W", "W->E"]),
                (50.0, ["N->E", "E->N"]),
                (60.0, ["W->S", "S->W"]),
            ],
            cycles=8,
        )
    )
    assert result["phase_model_selection"]["selected_phase_count"] <= 3
    assert result["phase_model_selection"]["topology_prior"]["canonical_four_leg_cap_applied"] is True


def test_v9_detects_local_regime_on_long_input():
    phases = [
        (40.0, ["A->B", "B->A"]),
        (60.0, ["C->D", "D->C"]),
    ]
    tracks_120 = _tracks(phases, cycles=40)
    # Build a second regime with a different period and append it after a gap.
    tracks_100 = _tracks(
        [
            (45.0, ["A->B", "B->A"]),
            (75.0, ["C->D", "D->C"]),
        ],
        cycles=40,
    )
    shift_ms = max(t["millis"] for t in tracks_120) + 7200 * 1000
    rebased = []
    for track in tracks_100:
        item = json.loads(json.dumps(track))
        item["millis"] += shift_ms - min(t["millis"] for t in tracks_100)
        for detection in item["detections"]:
            detection["millis"] += shift_ms - min(t["millis"] for t in tracks_100)
        rebased.append(item)
    result = discover_records(tracks_120 + rebased)
    assert result["regime_detection"]["method"] == "hourly_local_period_consensus"
    assert result["regime_detection"]["selected_window_event_count"] > 0


def test_v9_candidate_metrics_detect_unsupported_phase() -> None:
    import numpy as np

    fit = {
        "k": 3,
        "score": -100.0,
        "segments": [
            (0.0, 50.0, 0),
            (50.0, 100.0, 1),
            (100.0, 150.0, 2),
        ],
        "probs": np.asarray(
            [
                [0.60, 0.03, 0.02],
                [0.03, 0.60, 0.02],
                [0.02, 0.02, 0.02],
            ],
            dtype=float,
        ),
    }
    metrics = candidate_metrics(fit, (150, 3))
    assert metrics["supported_phase_count"] == 2
    assert metrics["unsupported_phase_count"] == 1


def test_v9_phase_selector_rejects_multiple_degenerate_extra_phases(monkeypatch) -> None:
    import numpy as np
    from app.core.v9 import fit as fit_module

    def fake_em_fit(
        x,
        period,
        k,
        by_stream_global=None,
        entry_streams=None,
        dt=1.0,
        iterations=3,
    ):
        if k == 2:
            probs = np.asarray(
                [
                    [0.60, 0.03, 0.02],
                    [0.03, 0.02, 0.60],
                ],
                dtype=float,
            )
        else:
            probs = np.asarray(
                [
                    [0.60, 0.03, 0.02],
                    [0.03, 0.02, 0.02],
                    [0.02, 0.02, 0.02],
                ],
                dtype=float,
            )
        return {
            "k": k,
            "score": -100.0,
            "probs": probs,
            "segments": [
                (0.0, 50.0, 0),
                (50.0, 100.0, 1),
            ] + ([(100.0, 150.0, 2)] if k == 3 else []),
            "decoder_info": {},
        }

    monkeypatch.setattr(fit_module, "em_fit", fake_em_fit)
    x = np.zeros((150, 3), dtype=float)
    selected, candidates, _ = fit_module.discover_phase_count(
        x,
        {"a": [1.0], "b": [2.0], "c": [3.0]},
        150.0,
        kmin=2,
        kmax=3,
        recording_end_s=150.0,
    )
    assert selected == 2
    candidate = next(
        item for item in candidates if item["k"] == 3
    )
    assert candidate["unsupported_phase_count"] == 2
    assert candidate["selection_score"] == float("inf")


def test_v9_phase_selector_keeps_one_weak_phase_when_two_phases_have_support(
    monkeypatch,
) -> None:
    import numpy as np
    from app.core.v9 import fit as fit_module

    def fake_em_fit(
        x,
        period,
        k,
        by_stream_global=None,
        entry_streams=None,
        dt=1.0,
        iterations=3,
    ):
        if k == 2:
            probs = np.asarray(
                [
                    [0.50, 0.03, 0.02],
                    [0.03, 0.50, 0.02],
                ],
                dtype=float,
            )
            score = -100.0
            segments = [
                (0.0, 50.0, 0),
                (50.0, 100.0, 1),
            ]
        else:
            probs = np.asarray(
                [
                    [0.50, 0.03, 0.02],
                    [0.03, 0.50, 0.02],
                    [0.02, 0.02, 0.07],
                ],
                dtype=float,
            )
            score = -80.0
            segments = [
                (0.0, 33.0, 0),
                (33.0, 66.0, 1),
                (66.0, 100.0, 2),
            ]
        return {
            "k": k,
            "score": score,
            "probs": probs,
            "segments": segments,
            "decoder_info": {},
        }

    monkeypatch.setattr(fit_module, "em_fit", fake_em_fit)
    x = np.zeros((100, 3), dtype=float)
    topology_streams = {
        "N->S": [1.0],
        "S->N": [2.0],
        "E->W": [3.0],
        "W->E": [4.0],
    }
    selected, candidates, _ = fit_module.discover_phase_count(
        x,
        topology_streams,
        100.0,
        kmin=2,
        kmax=3,
        recording_end_s=100.0,
        topology_streams=topology_streams,
    )
    weak_candidate = next(
        item for item in candidates if item["k"] == 3
    )
    assert weak_candidate["supported_phase_count"] == 2
    assert weak_candidate["unsupported_phase_count"] == 1
    assert selected == 3


