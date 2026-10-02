from __future__ import annotations

from scripts.v9_dataset_benchmark import DATASETS, compare_pairs


def test_dataset_matrix_contains_three_reference_anomaly_pairs() -> None:
    assert len(DATASETS) == 6
    assert sum(spec.role == "reference" for spec in DATASETS) == 3
    assert sum(spec.role != "reference" for spec in DATASETS) == 3


def test_compare_pairs_uses_reference_and_anomaly_rows() -> None:
    rows = []
    for index, spec in enumerate(DATASETS):
        rows.append(
            {
                "dataset": {"key": spec.key, "filename": spec.filename},
                "status": "ok",
                "period_s": 100.0 + index,
                "phase_count": 3,
                "streams": ["N->S", "S->N"],
            }
        )
    pairs = compare_pairs(rows)
    assert len(pairs) == 3
    assert all(item["phase_count_changed"] is False for item in pairs)
    assert all(item["stream_jaccard"] == 1.0 for item in pairs)


def test_stream_flow_rates_prefer_full_archive_counts() -> None:
    from scripts.v9_dataset_benchmark import _stream_flow_rates

    row = {
        "recording_duration_s": 7200.0,
        "stream_event_counts": {"E->W": 10},
        "archive_stream_event_counts": {"E->W": 1000},
    }
    rates = _stream_flow_rates(row)
    assert rates["E->W"] == 500.0
