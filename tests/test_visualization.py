from __future__ import annotations

from app.api.visualization import visualization_page


def test_visualization_page_declares_inferred_not_measured_state():
    html = visualization_page()
    assert "not measured directly" in html
    assert "Ground truth: unavailable" in html
    assert "/visualization/playback" in html
