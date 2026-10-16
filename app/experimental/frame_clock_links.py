"""Validate supplied frame identity/time pairs; never guess a clock from motion.

Numeric bounds condition on a constant unit-scale clock relation and supplied
timestamp-error bounds. Declarations do not certify clocks or producer identity.
"""
from fractions import Fraction
import math


def _integer(value, positive=False, signed=False):
    if (isinstance(value, bool) or not isinstance(value, int)
            or (not signed and value < int(positive))):
        raise ValueError('INVALID_INTEGER_TIME_OR_TIME_BASE')
    return value


def inspect_frame_clock_links(document):
    if document.get('schema') != 'frame-clock-links-v1':
        raise ValueError('INVALID_FRAME_CLOCK_SCHEMA')
    if document.get('timestamp_field') != 'detections[].millis':
        raise ValueError('DETECTION_TIMESTAMP_FIELD_REQUIRED')
    if document.get('association_basis') != 'producer_frame_identity':
        raise ValueError('FRAME_IDENTITY_REQUIRED_NOT_MOTION_OR_PHASE_ALIGNMENT')
    rows = document.get('rows')
    if not isinstance(rows, list):
        raise ValueError('FRAME_ROWS_REQUIRED')
    if len(rows) > 1000:
        raise ValueError('FRAME_LINK_RESOURCE_LIMIT')
    missing = [k for k in ['capture_id', 'video_source_id', 'trajectory_source_id', 'source_reference']
               if not isinstance(document.get(k), str) or not document[k].strip()]
    seen = set()
    output = []
    previous = None
    for row in rows:
        frame_id = row.get('frame_id')
        if not isinstance(frame_id, str) or not frame_id.strip() or frame_id in seen:
            raise ValueError('MISSING_OR_DUPLICATE_FRAME_ID')
        seen.add(frame_id)
        tb = row.get('video_time_base')
        if not isinstance(tb, list) or len(tb) != 2:
            raise ValueError('EXPLICIT_RATIONAL_TIME_BASE_REQUIRED')
        numerator, denominator = [_integer(x, positive=True) for x in tb]
        pts = Fraction(_integer(row.get('video_pts_ticks'), signed=True) * numerator * 1000, denominator)
        detection = _integer(row.get('detection_timestamp_ms'))
        if previous is not None and (pts <= previous[0] or detection < previous[1]):
            raise ValueError('UNSORTED_OR_CONFLICTING_FRAME_SEQUENCE')
        previous = pts, detection
        uncertainty = row.get('timestamp_uncertainty_ms')
        if uncertainty is not None and (isinstance(uncertainty, bool)
                or not isinstance(uncertainty, (int, float))
                or not math.isfinite(uncertainty) or uncertainty < 0):
            raise ValueError('INVALID_TIMESTAMP_UNCERTAINTY')
        if not isinstance(row.get('frame_identity_reference'), str) or not row['frame_identity_reference'].strip():
            raise ValueError('FRAME_IDENTITY_PROVENANCE_REQUIRED')
        has_error_source = isinstance(row.get('uncertainty_source'), str) and bool(row['uncertainty_source'].strip())
        offset = Fraction(detection)-pts
        bounds = None
        if uncertainty is not None and has_error_source:
            radius = Fraction(str(uncertainty))
            bounds = [offset-radius, offset+radius]
        output.append(dict(frame_id=frame_id, video_pts_ms_rational=str(pts),
                           detection_timestamp_ms=detection,
                           nominal_epoch_offset_ms_rational=str(offset),
                           conditional_offset_bounds_ms_rational=[str(x) for x in bounds] if bounds else None))
    bounds = None
    complete = bool(output) and all(r['conditional_offset_bounds_ms_rational'] is not None for r in output)
    if complete:
        intervals = [list(map(Fraction, r['conditional_offset_bounds_ms_rational'])) for r in output]
        bounds = [max(s[0] for s in intervals), min(s[1] for s in intervals)]
    inconsistent = bounds is not None and bounds[0] > bounds[1]
    status = ('UNAVAILABLE_NO_FRAME_LINKS' if not rows else
              'UNAVAILABLE_SOURCE_PROVENANCE' if missing else
              'UNAVAILABLE_TIMESTAMP_UNCERTAINTY' if not complete else
              'INCONSISTENT_DECLARED_CONSTANT_CLOCK' if inconsistent else
              'DECLARATIONS_READY_FOR_INDEPENDENT_REVIEW')
    return dict(schema='frame-clock-link-check-v1', status=status, row_count=len(rows),
                missing_metadata=missing, rows=output,
                conditional_constant_epoch_offset_ms_rational=(
                    [str(x) for x in bounds] if bounds is not None and not inconsistent and not missing else None),
                assumptions=['same captured exposure matched by producer frame identity',
                             'PTS time base explicitly supplied; no average-FPS conversion',
                             'constant unit-scale clock relation',
                             'supplied timestamp bounds include relevant timestamping/exposure error'],
                scientific_validation='NOT_PERFORMED', production_usable=False,
                accepted_json_video_clock_transform=None, calibrated_sync_uncertainty_ms=None,
                physical_section_state='UNKNOWN', calibrated_lamp_probability=None,
                inference_calls=0)
