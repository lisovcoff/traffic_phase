from __future__ import annotations

from tests.v10.test_synthetic_v9_three_phase_end_to_end import _make_tracks, _phase_by_signature
from app.core.v9.model import discover_records


def test_debug_synthetic_v9_physical() -> None:
    result = discover_records(
        _make_tracks(minutes=60),
        input_name="debug_synthetic",
        dt=1.0,
    )
    print("DEBUG_PHASES", result["schedule"]["phase_names"])
    print("DEBUG_ACTIVITY", result["schedule"]["stream_activity_by_phase"])
    print("DEBUG_SEGMENTS", result["schedule"]["baseline_segments"])
    print("DEBUG_MAPPING", _phase_by_signature(result))
    print("DEBUG_PHYSICAL", result["physical_signal_plan"])
