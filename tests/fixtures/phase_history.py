"""Minimal two-phase history for player and source-scope tests."""


def model():
    return dict(schedule_base_timestamp_ms=6000, analysis_base_timestamp_ms=6000,
        recording_start_timestamp_ms=1000, recording_duration_s=30,
        schedule=dict(phase_names=['A','B'],phase_count=2,period_s=20,
            raw_hsmm_segments=[[0,10,0],[12,20,1]],baseline_segments=[[0,10,0],[10,20,1]],
            stream_activity_by_phase=[{'stream':'N->E','event_probability_by_phase':{'A':.9,'B':.1}}]))
