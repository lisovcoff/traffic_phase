from scripts.video_audit_pack import parse_window, trajectory_start_ms

def test_trajectory_start_uses_first_valid_detection():
    assert trajectory_start_ms({"millis":3000,"detections":[{"millis":1000},{"millis":2000}]})==1000

def test_trajectory_start_falls_back_to_top_level_millis():
    assert trajectory_start_ms({"millis":3000,"detections":[]})==3000

def test_trajectory_start_ignores_malformed_detections():
    assert trajectory_start_ms({"millis":3000,"detections":[{"millis":"bad"},{"millis":1500}]})==1500

def test_parse_event_window():
    assert parse_window("615:30:90")== (615.0,30.0,90.0)
