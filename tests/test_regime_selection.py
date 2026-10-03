from app.core.v9.model import _cluster_local_regime_windows


def _window(start_s, phase_count, event_count, period_bucket=100.0, confidence=1.0):
    return {
        "start_s": float(start_s),
        "end_s": float(start_s + 3600.0),
        "period_s": 100.0,
        "period_bucket_s": float(period_bucket),
        "event_count": int(event_count),
        "score": float(confidence),
        "confidence": float(confidence),
        "selected_phase_count": phase_count,
        "boundary_coherence": 0.8,
        "supported_phase_count": int(phase_count or 0),
        "unsupported_phase_count": 0,
    }


def test_local_regime_clustering_prefers_recurring_phase_topology():
    windows = [
        _window(0, 2, 1700),
        _window(3600, 3, 2260),
        _window(7200, 2, 2250),
        _window(10800, 2, 2200),
    ]

    clusters = _cluster_local_regime_windows(windows)

    by_phase_count = {
        cluster["phase_count"]: cluster
        for cluster in clusters
    }

    assert by_phase_count[2]["support_windows"] == 3
    assert by_phase_count[2]["support_events"] == 6150
    assert by_phase_count[3]["support_windows"] == 1
    assert by_phase_count[3]["support_events"] == 2260

    selected = max(
        clusters,
        key=lambda cluster: (
            cluster["support_score"],
            cluster["support_windows"],
            cluster["support_events"],
        ),
    )
    assert selected["phase_count"] == 2


def test_local_regime_clustering_keeps_consistent_three_phase_recording():
    windows = [
        _window(0, 3, 3850),
        _window(3600, 3, 3980),
        _window(7200, 3, 3660),
    ]

    clusters = _cluster_local_regime_windows(windows)

    assert len(clusters) == 1
    assert clusters[0]["phase_count"] == 3
    assert clusters[0]["support_windows"] == 3
    assert clusters[0]["support_events"] == 11490
