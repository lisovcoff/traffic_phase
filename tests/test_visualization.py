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
    assert "Only evidence-backed intervals are authoritative" in html



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
    assert "boundary_suggested_fraction" in html
    assert "suggested · not applied" in html
    assert "effective_phase_model" in html
    assert "realtime_template_usability" in html



def test_visualization_surfaces_gap_semantics_and_regime_families():
    html = visualization_page()

    assert 'id="batchGapSemantics"' in html
    assert 'id="batchUnresolved"' in html
    assert 'id="batchRegimeFamily"' in html
    assert 'id="batchPooled"' in html
    assert "function currentRegimeFamily" in html
    assert "function effectiveTemplate" in html
    assert "effective_phase_model" in html
    assert "pooled_phase_model" in html
    assert "transition ambiguous" in html
    assert "Analysis segment:" in html



def test_visualization_surfaces_residual_movement_decisions():
    html = visualization_page()

    assert "movement_stage_decisions" in html
    assert "Pooled decision " in html
    assert "residual_repeatability" in html
    assert "conflicting_event_ratio" in html



def test_visualization_does_not_treat_unknown_as_a_failure_target():
    html = visualization_page()

    assert "Unable to determine" in html
    assert "Determination" in html
    assert "Realtime template" in html
    assert "Only evidence-backed intervals are authoritative" in html
    assert "✓ <1%" not in html
    assert "meets_target" not in html
    assert "meets_unresolved_target" not in html



def test_visualization_separates_determination_from_realtime_template():
    html = visualization_page()

    assert 'id="batchTemplateUsability"' in html
    assert "realtime_template_usability" in html
    assert "realtime_phase_model" in html
    assert "batchSession.effective_phase_model" in html
    assert "batchSession.effective_timeline" in html
    assert ">Diagnostics<" in html
    assert "Effective phase model" in html
    assert "Local model quality" in html
