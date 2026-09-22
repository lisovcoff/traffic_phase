from __future__ import annotations

from app.api.visualization import visualization_page


def test_visualization_page_has_batch_and_realtime_modes():
    html = visualization_page()

    assert ">Batch<" in html
    assert ">Realtime simulation<" in html
    assert 'accept=".json,.zip' in html
    assert "/api/v1/phase/analyze" in html
    assert "/api/v1/realtime/simulations/start" in html
    assert "/step?elapsed_seconds=" in html
    assert "/reset" in html


def test_realtime_controls_and_speed_choices_are_present():
    html = visualization_page()

    assert 'id="realtimeStart"' in html
    assert 'id="realtimePlay"' in html
    assert 'id="realtimePause"' in html
    assert 'id="realtimeStep"' in html
    assert 'id="realtimeReset"' in html
    assert '<option value="1">x1</option>' in html
    assert '<option value="5">x5</option>' in html
    assert '<option value="20" selected>x20</option>' in html
    assert '<option value="1000">MAX</option>' in html


def test_visualization_reuses_shared_intersection_and_explicit_unknown():
    html = visualization_page()

    assert html.count('class="intersection"') == 1
    assert 'id="sigN"' in html
    assert 'id="nsState"' in html
    assert "UNKNOWN" in html
    assert "WARMUP" in html
    assert "SYNCHRONIZED" in html
    assert "Ground truth is unavailable" in html


def test_visualization_uses_backend_phase_model_not_client_inference():
    html = visualization_page()

    assert "JSON.stringify(template.model)" in html
    assert "function effectiveTemplate" in html
    assert "The browser does not compute phases." in html
    assert "phase_at(" not in html
    assert "cycle_position =" not in html
    assert "/visualization/playback" not in html



def test_visualization_cleans_simulation_with_delete_keepalive():
    html = visualization_page()

    assert "method:'DELETE',keepalive:true" in html
    assert "navigator.sendBeacon" not in html



def test_visualization_shows_movement_specific_groups_as_backend_data():
    html = visualization_page()

    assert 'id="batchActiveMovements"' in html
    assert 'id="batchMovementList"' in html
    assert 'id="realtimeMovements"' in html
    assert "movement_stages" in html
    assert "active_movements" in html
    assert "Movement-specific groups are inferred separately" in html



def test_visualization_surfaces_adaptive_realtime_override_state():
    html = visualization_page()

    assert 'id="realtimeAdaptive"' in html
    assert "adaptive_mode" in html
    assert "template_expected_axis" in html
    assert "effective_axis" in html
    assert "Live override:" in html



def test_visualization_surfaces_batch_unknown_diagnostics():
    html = visualization_page()

    assert 'id="batchUnknown"' in html
    assert 'id="batchUnknownByApproach"' in html
    assert 'id="batchCoverage"' in html
    assert 'id="batchUnknownCause"' in html
    assert "uncovered_cycle_intervals" in html



def test_visualization_surfaces_batch_quality_and_boundary_recovery():
    html = visualization_page()

    assert 'id="batchQuality"' in html
    assert 'id="batchRecovery"' in html
    assert "model_quality" in html
    assert "boundary_recovered_fraction" in html
    assert "batchSession.model_quality==='GOOD'" in html
    assert "family.model_quality==='GOOD'" in html



def test_visualization_surfaces_gap_semantics_and_regime_families():
    html = visualization_page()

    assert 'id="batchGapSemantics"' in html
    assert 'id="batchUnresolved"' in html
    assert 'id="batchRegimeFamily"' in html
    assert "function currentRegimeFamily" in html
    assert "function effectiveTemplate" in html
    assert "regime family '+family.family_id+' consensus" in html
    assert "Analysis segment:" in html
