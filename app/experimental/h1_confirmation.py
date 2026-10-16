"""Confirm bounded facts from saved anchors, without fitting or clock promotion."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math


def assess_confirmation(readouts, frame_metadata, model, validation, mapping, raw_zones, timestamp_definitions=None):
    """Camera overlay observations are not independent JSON-clock certificates.

    UTC+5 is a supplied interpretation of the displayed local time. No display
    rounding, shutter latency or common-clock guarantee is silently assumed.
    """
    frames={row['file']:row for row in frame_metadata['frames']}
    rows=[];seen=set()
    for row in readouts:
        if row['file'] in seen:raise ValueError('DUPLICATE_CLOCK_FRAME')
        seen.add(row['file'])
        frame=frames[row['file']]
        if frame['sha256']!=row['frame_sha256']:raise ValueError('CLOCK_FRAME_IDENTITY_MISMATCH')
        pts=frame['actual_media_time_s']
        if isinstance(pts,bool) or not isinstance(pts,(int,float)) or not math.isfinite(pts):
            raise ValueError('INVALID_MEDIA_PTS')
        local=datetime.strptime(row['displayed_local_time'],'%d-%m-%Y %H:%M:%S')
        displayed_ms=local.replace(tzinfo=timezone(timedelta(hours=5))).timestamp()*1000
        nominal_json_ms=model['origin_ms']+1000*(pts+model['delta_s'])
        rows.append(dict(file=row['file'],frame_sha256=row['frame_sha256'],media_pts_s=pts,
            displayed_local_time=row['displayed_local_time'],interpreted_display_epoch_ms=displayed_ms,
            displayed_epoch_minus_pts_ms=displayed_ms-1000*pts,
            nominal_model_json_minus_displayed_second_ms=nominal_json_ms-displayed_ms,
            reviewer=row['reviewer']))
    if len(rows)<2:raise ValueError('TWO_CLOCK_READOUTS_REQUIRED')
    rows.sort(key=lambda r:r['media_pts_s'])
    increments=[]
    for before,after in zip(rows,rows[1:]):
        media_delta=after['media_pts_s']-before['media_pts_s']
        if media_delta<=0:raise ValueError('DUPLICATE_OR_NONMONOTONE_MEDIA_PTS')
        increments.append(dict(media_elapsed_s=media_delta,
            displayed_elapsed_s=(after['interpreted_display_epoch_ms']-before['interpreted_display_epoch_ms'])/1000))
    anchors=[]
    for row in validation['tracks']:
        identity=raw_zones.get(str(row['track_id']))
        if identity is None:raise ValueError('RAW_ZONE_ANCHOR_MISSING')
        anchors.append(dict(track_id=row['track_id'],raw_zone_in=identity['zone_in'],raw_zone_out=identity['zone_out'],
            observations=row.get('observations',0),max_image_residual_px=row.get('new_max_error_px'),
            local_pixel_check_status=row['status'],
            support_semantics='saved withheld local image check; not identity/clock/hardware certificate'))
    # A local residual gate or a successful optimization cannot certify clocks.
    observed={f"{r['raw_zone_in']}->{r['raw_zone_out']}" for r in anchors}
    proposals=[dict(section=section,raw_movement=movement,verified=False)
               for section,movement in [('main','N->_S'),('lateral','N->_E')] if movement in observed]
    return dict(schema='h1-anchor-confirmation-v1',overlay_readouts=rows,overlay_increments=increments,
        media_clock_status='SAVED_FRAME_OVERLAY_READOUTS_CONFIRMED',
        displayed_timezone='Asia/Yekaterinburg UTC+5 supplied interpretation; device setting not certified',
        observed_display_resolution_s=1,display_rounding_convention='UNKNOWN',
        camera_exposure_and_overlay_latency_ms=None,
        accepted_json_video_clock_transform=None,calibrated_sync_uncertainty_ms=None,
        json_millis_clock_source='AWAITING_SUPPLIER_OR_USER_PROVENANCE',
        supplier_timestamp_definition_excerpt=deepcopy(timestamp_definitions),
        clock_candidate=dict(origin_ms=model['origin_ms'],delta_s=model['delta_s'],
                             status='EXISTING_DIAGNOSTIC_NOT_REESTIMATED'),
        video_relative_H1_mapping=deepcopy(mapping),local_raw_zone_anchors=anchors,
        raw_mapping_status='LOCAL_CORRESPONDENCE_SUPPORTED_NOT_INDEPENDENTLY_CERTIFIED',
        movement_mapping_proposals=proposals,
        protected_permissive_semantics='UNKNOWN',
        physical_section_state='UNKNOWN',calibrated_lamp_probability=None,
        phase_labels_used=False,release_timestamps_used=False,fit_calls=0,production_default_changed=False,
        limitations=['Only three saved frames over four seconds; no global drift validation.',
                     'Overlay observations do not establish JSON clock source or same-event accuracy.',
                     '30/50px allowances were declared, not calibrated measurement uncertainty.',
                     'Supplier centroid feature, identity and joint geometry-clock error remain unverified.',
                     'Neither movement labels nor observed turns establish hardware permission semantics.'])
