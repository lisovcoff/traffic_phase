"""Conditional video/detection clock conversion, separate from lamp inference."""
import math


def map_bracket(bracket_s, *, origin_ms, delta_s, delta_bounds_s):
    """JSON time = origin + 1000*(PTS + delta); preserve both error sources."""
    lo, hi = bracket_s
    lower, upper = delta_bounds_s
    if not all(math.isfinite(v) for v in (lo, hi, origin_ms, delta_s, lower, upper)):
        raise ValueError('finite clock and bracket required')
    if hi < lo or lower > delta_s or delta_s > upper:
        raise ValueError('ordered bracket and bounds containing frozen delta required')
    return dict(
        video_bracket_s=[lo, hi],
        json_bracket_fixed_clock_ms=[origin_ms+1000*(lo+delta_s), origin_ms+1000*(hi+delta_s)],
        json_bracket_conditional_envelope_ms=[origin_ms+1000*(lo+lower), origin_ms+1000*(hi+upper)],
        interval_semantics='image appearance plus conditional fixed-geometry clock bounds; not calibrated physical exposure accuracy',
    )


def source_bias(apparent_video_bias_s, delta_s):
    if not all(math.isfinite(v) for v in (apparent_video_bias_s, delta_s)):
        raise ValueError('finite offsets required')
    return apparent_video_bias_s-delta_s
