from __future__ import annotations

from app.api.visualization import visualization_page


def test_visualization_page_uses_production_archive_api():
    html = visualization_page()

    assert 'accept=".json,.zip' in html
    assert "/api/v1/phase/analyze" in html
    assert "/visualization/playback" not in html
    assert "sessionSelect" in html
    assert "phaseTimeline" in html
    assert "slider" in html


def test_visualization_page_exposes_unknown_and_no_client_inference():
    html = visualization_page()

    assert "UNKNOWN" in html
    assert "Ground truth is unavailable" in html
    assert "The browser displays backend inference only" in html
    assert "NS / EW state" in html
