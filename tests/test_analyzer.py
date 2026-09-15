from pathlib import Path

from app.analyzer import analyze


REFERENCE_JSON = Path("6_2025_2_23_13.json")


def test_reference_signal_is_periodic():
    result = analyze(REFERENCE_JSON)

    assert result["statistics"]["cars_used"] == 226
    assert 80 <= result["cycle"]["estimated_seconds"] <= 120
    assert result["cycle"]["autocorrelation_strength"] > 0.25
    assert result["candidate_phase_transitions"]
