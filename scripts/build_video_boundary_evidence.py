"""Assemble visual-review evidence; no video decoding or signal inference."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image


def build(root):
    observations = json.loads((root/'visual_review.json').read_text(encoding='utf-8'))
    lookup = {}
    totals = {'frames':0, 'runtime_s':0, 'media_bytes_served':0}
    identity = None
    for name in ('coarse','refined','followup'):
        manifest = json.loads((root/name/'frames.json').read_text(encoding='utf-8'))
        current = manifest['source']['sampled_identity_sha256']
        if identity is not None and current != identity:
            raise ValueError('VIDEO_SAMPLED_IDENTITY_CHANGED')
        identity = current
        totals['runtime_s'] += manifest['runtime_s']
        totals['media_bytes_served'] += manifest['media_bytes_served']
        if manifest['media_bytes_served'] > 128*1024*1024:
            raise ValueError('MEDIA_BUDGET_EXCEEDED')
        for frame in manifest['frames']:
            path = root/name/frame['file']
            if hashlib.sha256(path.read_bytes()).hexdigest() != frame['sha256']:
                raise ValueError('FRAME_HASH_MISMATCH')
            with Image.open(path) as image:
                if image.size != (180,120):
                    raise ValueError('ROI_DIMENSION_MISMATCH')
            lookup[(name,frame['requested_elapsed_s'])] = {**frame,'path':str(path).replace('\\','/')}
            totals['frames'] += 1
    if totals['frames'] > 96:
        raise ValueError('TOTAL_FRAME_BUDGET_EXCEEDED')
    rows = []
    for claim in observations['transitions']:
        before = lookup[tuple(claim['before'])]
        after = lookup[tuple(claim['after'])]
        lo, hi = before['actual_media_time_s'], after['actual_media_time_s']
        if not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (lo,hi)) or lo < 0 or hi <= lo:
            raise ValueError('NONPOSITIVE_PRESENTATION_BRACKET')
        supporting = [lookup[tuple(ref)] for ref in claim.get('supporting_later_dark_samples',[])]
        marker = claim.get('operator_marker_media_s')
        rows.append({**claim, 'before_frame':before, 'after_frame':after, 'supporting_frames':supporting,
            'video_presentation_bracket_s':[lo,hi], 'width_s':round(hi-lo,6),
            'operator_marker_minus_bracket_s':None if marker is None else [round(marker-hi,6),round(marker-lo,6)],
            'json_boundary_timestamp_ms':None,
            'physical_switch_timing_error_ms':None,
            'bracket_semantics':'sampled decoded appearance only; not calibrated physical-switch uncertainty',
            'continuous_monitoring':False})
    return {'schema':'direct-video-review-v1','source_sampled_identity_sha256':identity,
            'source_full_sha256':None, 'sampling':totals,'transitions':rows,
            'observations':observations['notes'], 'json_video_sync':'UNVERIFIED',
            'section_to_movement_mapping':'UNKNOWN', 'lamp_accuracy_evaluated':False,
            'phase_inference_runs':0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args = parser.parse_args()
    report = build(args.root)
    (args.root/'verified_video_boundaries.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['sampling']))
