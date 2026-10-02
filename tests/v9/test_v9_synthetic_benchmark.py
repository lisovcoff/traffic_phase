from __future__ import annotations

import pytest

from app.core.v9.v9_discovery import discover_records
from scripts.v9_synthetic_benchmark import CASES, generate


@pytest.mark.parametrize("index,name", list(enumerate(CASES)))
def test_v9_phase_count_on_benchmark_case(index, name):
    durations, streams = CASES[name]
    drop = 0.25 if "noisy" in name else 0.10 if "missing" in name else 0.0
    jitter = 0.30 if "noisy" in name else 0.0
    duplicates = 0.05 if "noisy" in name else 0.0

    tracks, _starts, _period = generate(
        durations,
        streams,
        cycles=10,
        seed=index + 100,
        drop=drop,
        timestamp_jitter_s=jitter,
        duplicate_fraction=duplicates,
    )
    result = discover_records(tracks, input_name=name, dt=1.0)

    predicted = int(
        result["phase_model_selection"]["selected_phase_count"]
    )
    expected = len(durations)

    assert predicted == expected, (
        f"{name}: expected {expected} phases, got {predicted}; "
        f"candidates={result['phase_model_selection']['candidates']}"
    )
