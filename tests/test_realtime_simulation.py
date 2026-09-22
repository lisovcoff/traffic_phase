from __future__ import annotations

import asyncio
from io import BytesIO
import json
import zipfile

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.api.realtime_simulation import (
    delete_realtime_simulation,
    realtime_simulation_status,
    reset_realtime_simulation,
    simulation_registry,
    start_realtime_simulation,
    step_realtime_simulation,
)
from app.core.event_phase_discovery import (
    EventPhase,
    EventPhaseDiscoveryResult,
)
from app.core.realtime_simulation import (
    RealtimeArchiveSimulation,
    RealtimeSimulationRegistry,
    load_realtime_simulation_source,
)


def _phase_model():
    return EventPhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            EventPhase(
                1,
                0.0,
                40.0,
                ("N", "S"),
                0.9,
                20,
                2,
                ("N", "S"),
            ),
            EventPhase(
                2,
                40.0,
                100.0,
                ("E", "W"),
                0.9,
                20,
                2,
                ("E", "W"),
            ),
        ),
        profiles=(),
        cycle_coverage=1.0,
        overlap=0.0,
        supporting_event_count=40,
        contradictory_event_count=4,
        origin_timestamp_ms=987654321000,
    )


def _phase_payload_json():
    model = _phase_model()
    return json.dumps(
        {
            "cycle_seconds": model.cycle_seconds,
            "bin_seconds": model.bin_seconds,
            "origin_timestamp_ms": (
                model.origin_timestamp_ms
            ),
            "phases": [
                phase.to_dict()
                for phase in model.phases
            ],
            "cycle_coverage": model.cycle_coverage,
            "overlap": model.overlap,
            "supporting_event_count": (
                model.supporting_event_count
            ),
            "contradictory_event_count": (
                model.contradictory_event_count
            ),
        }
    )


def _record(
    vehicle_id,
    *,
    start_ms,
    crossing_ms,
    end_ms,
    approach,
    zone_out,
):
    return {
        "id": vehicle_id,
        "millis": end_ms,
        "zone_in": approach,
        "zone_out": zone_out,
        "category_name": "car",
        "detections": [
            {
                "millis": start_ms,
                "lat": 55.0,
                "lng": 61.0,
                "zone": approach,
            },
            {
                "millis": crossing_ms,
                "lat": 55.00003,
                "lng": 61.0,
                "zone": None,
            },
            {
                "millis": end_ms,
                "lat": 55.00006,
                "lng": 61.0,
                "zone": zone_out,
            },
        ],
    }


def _upload(name, payload):
    return UploadFile(
        file=BytesIO(payload),
        filename=name,
    )


def _json_bytes(records):
    return json.dumps(records).encode("utf-8")


def _zip_bytes(members):
    stream = BytesIO()
    with zipfile.ZipFile(
        stream,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for name, records in members:
            archive.writestr(
                name,
                _json_bytes(records),
            )
    return stream.getvalue()


def test_start_step_status_reset_json_simulation():
    simulation_registry.clear()
    records = [
        _record(
            1,
            start_ms=0,
            crossing_ms=2_000,
            end_ms=10_000,
            approach="N",
            zone_out="_S",
        ),
        _record(
            2,
            start_ms=20_000,
            crossing_ms=22_000,
            end_ms=30_000,
            approach="E",
            zone_out="_W",
        ),
    ]
    upload = _upload(
        "sample.json",
        _json_bytes(records),
    )

    started = asyncio.run(
        start_realtime_simulation(
            file=upload,
            phase_model=_phase_payload_json(),
            speed=2.0,
            simulation_id="json-sim",
        )
    )

    assert started["simulated_timestamp_ms"] == 0
    assert started["synchronization_status"] == "WARMUP"
    assert set(started["signal_states"].values()) == {
        "UNKNOWN"
    }
    assert started["active_movements"] == []
    assert started["adaptive_mode"] == "NORMAL"
    assert started["template_disagreement"] is False
    assert started["template_signal_states"] == started["signal_states"]
    assert (
        started["evidence_summary"][
            "emitted_trajectory_count"
        ]
        == 0
    )

    early = asyncio.run(
        step_realtime_simulation(
            "json-sim",
            elapsed_seconds=2.0,
        )
    )
    assert early["simulated_timestamp_ms"] == 4_000
    assert (
        early["evidence_summary"][
            "emitted_trajectory_count"
        ]
        == 1
    )
    assert (
        early["evidence_summary"][
            "completed_trajectory_count"
        ]
        == 0
    )
    assert early["evidence_summary"]["emitted_event_count"] >= 2

    released = asyncio.run(
        step_realtime_simulation(
            "json-sim",
            elapsed_seconds=3.0,
        )
    )
    assert released["simulated_timestamp_ms"] == 10_000
    assert (
        released["evidence_summary"][
            "emitted_trajectory_count"
        ]
        == 1
    )
    assert (
        released["evidence_summary"][
            "synchronization_evidence_count"
        ]
        >= 1
    )

    status = asyncio.run(
        realtime_simulation_status("json-sim")
    )
    assert status["simulated_timestamp_ms"] == 10_000

    reset = asyncio.run(
        reset_realtime_simulation("json-sim")
    )
    assert reset["simulated_timestamp_ms"] == 0
    assert (
        reset["evidence_summary"][
            "emitted_trajectory_count"
        ]
        == 0
    )

    deleted = asyncio.run(
        delete_realtime_simulation("json-sim")
    )
    assert deleted["deleted"] is True
    assert len(simulation_registry) == 0


def test_zip_source_is_compacted_and_sorted_by_completion_time():
    late = _record(
        2,
        start_ms=20_000,
        crossing_ms=22_000,
        end_ms=30_000,
        approach="E",
        zone_out="_W",
    )
    early = _record(
        1,
        start_ms=0,
        crossing_ms=2_000,
        end_ms=10_000,
        approach="N",
        zone_out="_S",
    )
    content = _zip_bytes(
        [
            ("late.json", [late]),
            ("early.json", [early]),
        ]
    )

    source = load_realtime_simulation_source(
        BytesIO(content),
        filename="sample.zip",
    )

    assert source.source_format == "zip"
    assert source.trajectory_count == 2
    assert [
        item.available_timestamp_ms
        for item in source.items
    ] == [10_000, 30_000]
    assert all(item.events for item in source.items)


def test_future_trajectory_cannot_affect_early_snapshot():
    records = [
        _record(
            1,
            start_ms=0,
            crossing_ms=2_000,
            end_ms=10_000,
            approach="N",
            zone_out="_S",
        ),
        _record(
            2,
            start_ms=20_000,
            crossing_ms=21_000,
            end_ms=90_000,
            approach="E",
            zone_out="_W",
        ),
    ]
    source = load_realtime_simulation_source(
        BytesIO(_json_bytes(records)),
        filename="future.json",
    )
    simulation = RealtimeArchiveSimulation(
        source,
        _phase_model(),
    )

    before_completion = simulation.step(5.0)

    assert before_completion[
        "simulated_timestamp_ms"
    ] == 5_000
    assert (
        before_completion["evidence_summary"][
            "emitted_trajectory_count"
        ]
        == 1
    )
    assert (
        before_completion["evidence_summary"][
            "completed_trajectory_count"
        ]
        == 0
    )
    assert (
        before_completion["evidence_summary"][
            "synchronization_evidence_count"
        ]
        >= 1
    )
    assert before_completion["phase_id"] is None
    assert set(
        before_completion["signal_states"].values()
    ) == {"UNKNOWN"}

    first_complete = simulation.step(5.0)
    assert (
        first_complete["evidence_summary"][
            "emitted_trajectory_count"
        ]
        == 1
    )
    assert (
        first_complete["evidence_summary"][
            "remaining_trajectory_count"
        ]
        == 1
    )
    assert (
        first_complete["evidence_summary"][
            "synchronization_evidence_count"
        ]
        >= 1
    )


def test_registry_evicts_oldest_simulation():
    source = load_realtime_simulation_source(
        BytesIO(
            _json_bytes(
                [
                    _record(
                        1,
                        start_ms=0,
                        crossing_ms=1_000,
                        end_ms=2_000,
                        approach="N",
                        zone_out="_S",
                    )
                ]
            )
        ),
        filename="one.json",
    )
    registry = RealtimeSimulationRegistry(
        max_simulations=1
    )
    first = RealtimeArchiveSimulation(
        source,
        _phase_model(),
    )
    second = RealtimeArchiveSimulation(
        source,
        _phase_model(),
    )

    registry.create("first", first)
    registry.create("second", second)

    assert len(registry) == 1
    with pytest.raises(KeyError):
        registry.get("first")
    assert registry.get("second") is second


def test_corrupted_zip_start_returns_422():
    simulation_registry.clear()
    upload = _upload(
        "broken.zip",
        b"not-a-valid-zip",
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            start_realtime_simulation(
                file=upload,
                phase_model=_phase_payload_json(),
                speed=1.0,
                simulation_id="broken",
            )
        )

    assert exc.value.status_code == 422
    assert "corrupted ZIP" in exc.value.detail



def test_simulated_time_advances_phase_without_new_evidence():
    from app.core.models import EventType, TrajectoryEvent
    from app.core.realtime_simulation import (
        RealtimeSimulationSource,
        ScheduledTrajectoryEvidence,
    )

    events = tuple(
        TrajectoryEvent(
            event_type=EventType.RELEASE,
            timestamp_ms=int(timestamp_s * 1000),
            approach=approach,
            movement=f"{approach}->x",
            confidence=1.0,
            quality="HIGH",
        )
        for timestamp_s, approach in (
            (4.0, "N"),
            (18.0, "S"),
            (36.0, "N"),
            (44.0, "E"),
            (62.0, "W"),
            (82.0, "E"),
        )
    )
    source = RealtimeSimulationSource(
        filename="clock.json",
        source_format="json",
        start_timestamp_ms=0,
        end_timestamp_ms=190_000,
        trajectory_count=2,
        event_count=len(events),
        items=(
            ScheduledTrajectoryEvidence(
                available_timestamp_ms=90_000,
                start_timestamp_ms=0,
                trajectory_key="evidence",
                events=events,
            ),
            ScheduledTrajectoryEvidence(
                available_timestamp_ms=190_000,
                start_timestamp_ms=180_000,
                trajectory_key="future-empty",
                events=(),
            ),
        ),
    )
    simulation = RealtimeArchiveSimulation(
        source,
        _phase_model(),
    )

    at_ninety = simulation.step(90.0)
    assert at_ninety["synchronization_status"] == "SYNCHRONIZED"
    assert at_ninety["phase_id"] == 2
    evidence_count = at_ninety["evidence_summary"][
        "synchronization_evidence_count"
    ]

    at_one_ten = simulation.step(20.0)
    assert at_one_ten["simulated_timestamp_ms"] == 110_000
    assert at_one_ten["phase_id"] == 1
    assert (
        (
            at_one_ten["cycle_position_s"]
            - at_ninety["cycle_position_s"]
        )
        % 100.0
        == 20.0
    )
    assert (
        at_one_ten["evidence_summary"][
            "synchronization_evidence_count"
        ]
        == evidence_count
    )



def test_realtime_simulation_accepts_custom_topology_in_phase_payload():
    simulation_registry.clear()
    payload = json.loads(_phase_payload_json())
    payload["topology"] = {
        "families": [
            {"name": "MAIN", "approaches": ["N", "S"]},
            {"name": "CROSS", "approaches": ["E", "W"]},
        ],
        "family_conflicts": [["MAIN", "CROSS"]],
    }
    upload = _upload(
        "topology.json",
        _json_bytes(
            [
                _record(
                    1,
                    start_ms=0,
                    crossing_ms=1_000,
                    end_ms=2_000,
                    approach="N",
                    zone_out="_S",
                )
            ]
        ),
    )

    started = asyncio.run(
        start_realtime_simulation(
            file=upload,
            phase_model=json.dumps(payload),
            speed=1.0,
            simulation_id="topology-sim",
        )
    )

    assert started["simulation_id"] == "topology-sim"
    simulation_registry.clear()


def test_causal_simulation_emits_release_before_trajectory_completion():
    from app.core.models import Detection, Trajectory
    from app.core.realtime_simulation import (
        RealtimeSimulationSource,
        ScheduledTrajectoryEvidence,
    )

    detections = tuple(
        Detection(
            millis=millis,
            lat=lat,
            lng=61.0,
            zone=zone,
        )
        for millis, lat, zone in (
            (0, 55.0, "N"),
            (1000, 55.0, "N"),
            (2000, 55.0, "N"),
            (3000, 55.0, "N"),
            (4000, 55.0, "N"),
            (5000, 55.00003, "N"),
            (6000, 55.00006, None),
            (20_000, 55.00030, "_S"),
        )
    )
    trajectory = Trajectory(
        vehicle_id=42,
        timestamp_ms=20_000,
        zone_in="N",
        zone_out="_S",
        movement="N->_S",
        speed=None,
        wait_s=0.0,
        move_s=0.0,
        distance=None,
        detections=detections,
    )
    source = RealtimeSimulationSource(
        filename="causal.json",
        source_format="json",
        start_timestamp_ms=0,
        end_timestamp_ms=20_000,
        trajectory_count=1,
        event_count=0,
        items=(
            ScheduledTrajectoryEvidence(
                available_timestamp_ms=20_000,
                start_timestamp_ms=0,
                trajectory_key="causal:42",
                trajectory=trajectory,
            ),
        ),
    )
    simulation = RealtimeArchiveSimulation(source, _phase_model())

    partial = simulation.step(6.0)

    assert partial["finished"] is False
    assert partial["evidence_summary"]["emitted_trajectory_count"] == 1
    assert partial["evidence_summary"]["completed_trajectory_count"] == 0
    assert partial["evidence_summary"]["emitted_event_count"] >= 4
    assert (
        partial["evidence_summary"]["synchronization_evidence_count"]
        >= 2
    )


def test_causal_simulation_does_not_release_precomputed_future_event():
    record = _record(
        1,
        start_ms=0,
        crossing_ms=10_000,
        end_ms=20_000,
        approach="N",
        zone_out="_S",
    )
    source = load_realtime_simulation_source(
        BytesIO(_json_bytes([record])),
        filename="no-lookahead.json",
    )
    assert source.items[0].events

    simulation = RealtimeArchiveSimulation(source, _phase_model())
    early = simulation.step(5.0)

    assert early["evidence_summary"]["emitted_trajectory_count"] == 1
    assert early["evidence_summary"]["completed_trajectory_count"] == 0
    assert (
        early["evidence_summary"]["synchronization_evidence_count"]
        == 0
    )

    crossing_seen = simulation.step(5.0)
    assert (
        crossing_seen["evidence_summary"][
            "synchronization_evidence_count"
        ]
        >= 1
    )


def test_warmup_reason_reports_missing_or_single_family_evidence():
    records = [
        _record(
            1,
            start_ms=0,
            crossing_ms=2_000,
            end_ms=10_000,
            approach="N",
            zone_out="_S",
        )
    ]
    source = load_realtime_simulation_source(
        BytesIO(_json_bytes(records)),
        filename="warmup.json",
    )
    simulation = RealtimeArchiveSimulation(source, _phase_model())

    initial = simulation.snapshot()
    assert initial["warmup_reason"] == "no_release_or_crossing_evidence"

    partial = simulation.step(3.0)
    assert partial["warmup_reason"] == "only_one_family"



def test_realtime_unknown_metrics_track_post_sync_and_rolling_rates():
    from app.core.models import EventType, TrajectoryEvent
    from app.core.realtime_simulation import (
        RealtimeSimulationSource,
        ScheduledTrajectoryEvidence,
    )

    events = tuple(
        TrajectoryEvent(
            event_type=EventType.RELEASE,
            timestamp_ms=int(timestamp_s * 1000),
            approach=approach,
            movement=f"{approach}->x",
            confidence=1.0,
            quality="HIGH",
        )
        for timestamp_s, approach in (
            (4.0, "N"),
            (18.0, "S"),
            (36.0, "N"),
            (44.0, "E"),
            (62.0, "W"),
            (82.0, "E"),
        )
    )
    source = RealtimeSimulationSource(
        filename="unknown-metrics.json",
        source_format="json",
        start_timestamp_ms=0,
        end_timestamp_ms=100_000,
        trajectory_count=1,
        event_count=len(events),
        items=(
            ScheduledTrajectoryEvidence(
                available_timestamp_ms=90_000,
                start_timestamp_ms=0,
                trajectory_key="metrics",
                events=events,
            ),
        ),
    )
    simulation = RealtimeArchiveSimulation(source, _phase_model())

    synchronized = simulation.step(90.0)

    assert synchronized["synchronization_status"] == "SYNCHRONIZED"
    assert synchronized["template_compatibility"] == "COMPATIBLE"
    metrics = synchronized["unknown_metrics"]
    assert metrics["sample_count"] == 1
    assert metrics["post_sync_sample_count"] == 1
    assert metrics["post_sync_rate"] == 0.0
    assert metrics["rolling_60s_rate"] == 0.0
    assert metrics["meets_post_sync_target"] is True


def test_realtime_source_rejects_unknown_approach_topology():
    from app.core.models import EventType, TrajectoryEvent
    from app.core.realtime_simulation import (
        RealtimeSimulationSource,
        ScheduledTrajectoryEvidence,
    )

    source = RealtimeSimulationSource(
        filename="wrong-intersection.json",
        source_format="json",
        start_timestamp_ms=0,
        end_timestamp_ms=1_000,
        trajectory_count=1,
        event_count=1,
        items=(
            ScheduledTrajectoryEvidence(
                available_timestamp_ms=1_000,
                start_timestamp_ms=0,
                trajectory_key="wrong",
                events=(
                    TrajectoryEvent(
                        event_type=EventType.RELEASE,
                        timestamp_ms=1_000,
                        approach="X",
                        movement="X->Y",
                        confidence=1.0,
                        quality="HIGH",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(ValueError, match="incompatible realtime source"):
        RealtimeArchiveSimulation(source, _phase_model())
