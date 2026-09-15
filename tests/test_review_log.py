from __future__ import annotations

import pandas as pd

from app.core.phase_discovery import Phase, PhaseDiscoveryResult
from app.core.review_log import review_summary


def test_review_summary_flags_non_overlapping_phase_model_as_valid():
    frame = pd.DataFrame({
        "t_s": [5.0, 6.0, 55.0, 56.0],
        "zone_in": ["N", "S", "E", "W"],
        "release_weight": [5.0, 4.0, 5.0, 4.0],
        "stopped": [False, False, False, False],
    })
    model = PhaseDiscoveryResult(
        cycle_seconds=100.0,
        bin_seconds=2.0,
        phases=(
            Phase(1, 0.0, 40.0, ("N", "S"), ("N->_S", "S->_N"), 0.8, ("N", "S")),
            Phase(2, 50.0, 90.0, ("E", "W"), ("E->_W", "W->_E"), 0.8, ("E", "W")),
        ),
        profiles=(),
        similarities={},
    )
    timeline = [
        {
            "timestamp_s": 10.0,
            "cycle_phase_s": 10.0,
            "approaches": {
                "N": {"state": "GREEN"}, "S": {"state": "GREEN"},
                "E": {"state": "RED"}, "W": {"state": "RED"},
            },
        },
        {
            "timestamp_s": 60.0,
            "cycle_phase_s": 60.0,
            "approaches": {
                "N": {"state": "RED"}, "S": {"state": "RED"},
                "E": {"state": "GREEN"}, "W": {"state": "GREEN"},
            },
        },
    ]
    summary = review_summary(frame, model, timeline, cycle_confidence=0.8)
    assert summary["status"] in {"PASS", "WARN"}
    assert summary["metrics"]["phase_overlap_ratio"] == 0.0
