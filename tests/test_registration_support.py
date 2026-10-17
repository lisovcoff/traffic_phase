import numpy as np
import pytest

from app.experimental.vehicle_clock_alignment import inspect_registration_support, project


def records(points):
    return [{'id': i, 'detections': [{'centroid_x': x, 'centroid_y': y}]}
            for i, (x, y) in enumerate(points)]


@pytest.mark.parametrize('scale', [1.0, -1.0, 1e-8, -1e8])
def test_plane_support_result_is_projective_gauge_invariant(scale):
    h = np.array([[1, 0, .1], [0, .8, .2], [0, 0, 1.]]) * scale
    result = inspect_registration_support({'homography': h}, records([(0, 0), (1, 0), (1, 1), (0, 1)]))
    assert result['geometry_usable_on_supplied_support']
    assert result['status'] == 'GEOMETRY_FINITE_ON_SUPPLIED_SUPPORT_ONLY'
    assert result['accepted_json_video_clock_transform'] is None
    assert not result['production_usable']


def test_finite_point_projections_do_not_hide_horizon_between_approaches():
    # Every observation is finite. Their connecting road support crosses x=.5,
    # where this purported common plane registration would be undefined.
    h = [[1, 0, 0], [0, 1, 0], [1, 0, -.5]]
    points = [(.2, .2), (.8, .2), (.2, .8), (.8, .8)]
    assert np.isfinite(project(points, h)).all()
    result = inspect_registration_support({'homography': h}, records(points))
    assert result['status'] == 'REJECTED_ROAD_HORIZON_CROSSING'
    assert not result['geometry_usable_on_supplied_support']
    assert result['witnesses'][0]['normalized_denominator'] < 0
    assert result['witnesses'][1]['normalized_denominator'] > 0


def test_perfect_local_training_projection_does_not_certify_broader_scope():
    h = [[1, 0, 0], [0, 1, 0], [1, 0, -.5]]
    local = records([(.1, .1), (.2, .2), (.3, .3)])
    assert inspect_registration_support({'homography': h}, local)['geometry_usable_on_supplied_support']
    # A new approach must be checked even if the local model fit was exact.
    broad = inspect_registration_support({'homography': h}, local + records([(.9, .1)]))
    assert broad['status'] == 'REJECTED_ROAD_HORIZON_CROSSING'


def test_actual_observation_on_horizon_is_rejected():
    result = inspect_registration_support({'homography': [[1,0,0],[0,1,0],[1,0,-.5]]}, records([(.5,.2)]))
    assert result['status'] == 'REJECTED_ROAD_HORIZON_CROSSING'


def test_no_observations_cannot_certify_a_registration():
    result = inspect_registration_support({'homography': np.eye(3)}, [])
    assert result['status'] == 'UNAVAILABLE_NO_OBSERVED_ROAD_SUPPORT'
    assert not result['geometry_usable_on_supplied_support']


@pytest.mark.parametrize('h', [np.zeros((3,3)), np.eye(2), [[1,0,0],[0,1,0],[0,0,float('nan')]]])
def test_invalid_registration_is_rejected(h):
    with pytest.raises(ValueError, match='INVALID_REGISTRATION_HOMOGRAPHY'):
        inspect_registration_support({'homography': h}, records([(.1,.2)]))


@pytest.mark.parametrize('x', [True, float('nan'), float('inf'), '0.1', None])
def test_invalid_feature_is_not_silently_dropped(x):
    with pytest.raises(ValueError, match='INVALID_REGISTRATION_SUPPORT_POINT'):
        inspect_registration_support({'homography': np.eye(3)}, records([(x,.2)]))


def test_score_cli_rejects_broad_road_horizon_before_scoring(tmp_path, monkeypatch):
    import json
    import sys
    from scripts import vehicle_clock_calibration as cli

    sample=tmp_path/'sample.json';points=tmp_path/'points.json';plan=tmp_path/'plan.json'
    model=tmp_path/'model.json';out=tmp_path/'result.json'
    sample.write_text(json.dumps(records([(.2,.2),(.8,.2)])),encoding='utf-8')
    points.write_text(json.dumps({'rows':[]}),encoding='utf-8')
    plan.write_text('{}',encoding='utf-8')
    model.write_text(json.dumps({'homography':[[1,0,0],[0,1,0],[1,0,-.5]],'heldout_id':1}),encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['calibration','--mode','score','--sample',str(sample),
        '--points',str(points),'--plan',str(plan),'--model',str(model),'--out',str(out)])

    def forbidden(*args,**kwargs):
        raise AssertionError('Rejected geometry must not reach pixel scoring or clock-set evaluation')
    monkeypatch.setattr(cli,'score_heldout',forbidden)
    monkeypatch.setattr(cli,'conditional_clock_set',forbidden)
    cli.main()
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['status']=='REJECTED_ROAD_HORIZON_CROSSING'
    assert not result['scoring_performed']
    assert result['accepted_json_video_clock_transform'] is None
    assert 'conditional_clock_set' not in result
