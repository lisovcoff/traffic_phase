"""Explicit offline calibration CLI; no phase inference or default changes.

Training and scoring use separate input files. Output must be new, so an existing
sealed result cannot be silently overwritten. The source sample remains immutable.
"""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime

from app.experimental.vehicle_clock_alignment import (
    fit_training, score_heldout, conditional_clock_set, inspect_registration_support,
)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['fit','score'],required=True)
    p.add_argument('--sample',type=Path,required=True)
    p.add_argument('--points',type=Path,required=True)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--model',type=Path)
    a=p.parse_args()
    if a.out.exists():raise ValueError('FRESH_OUTPUT_REQUIRED')
    if a.sample.stat().st_size>32*1024*1024:raise ValueError('SOURCE_BYTE_BUDGET_EXCEEDED')
    raw=a.sample.read_bytes();records=json.loads(raw)
    if len(records)>400:raise ValueError('SOURCE_TRACK_BUDGET_EXCEEDED')
    points=json.loads(a.points.read_text(encoding='utf-8'))['rows']
    plan=json.loads(a.plan.read_text(encoding='utf-8'))
    if a.mode=='fit':
        selected=[r for r in records if r['id'] in plan['training_tracks']]
        result=fit_training(selected,points,training_ids=plan['training_tracks'],
            heldout_id=plan['validation_track'],
            origin_ms=int(datetime.fromisoformat('2025-02-27T09:59:55+05:00').timestamp()*1000))
        # Inspect every supplied source approach, not just the selected training
        # tracks. This uses unlabeled coordinate support, never validation pixel
        # annotations, and does not refit the model.
        support=inspect_registration_support(result,records)
        result['registration_support']=support
        if not support['geometry_usable_on_supplied_support']:
            result['status']=support['status']
    else:
        if a.model is None:raise ValueError('SEALED_TRAINING_MODEL_REQUIRED')
        model=json.loads(a.model.read_text(encoding='utf-8'))
        selected=[r for r in records if r['id']==model['heldout_id']]
        if len(selected)!=1:raise ValueError('UNIQUE_HELDOUT_TRACK_REQUIRED')
        support=inspect_registration_support(model,records)
        if not support['geometry_usable_on_supplied_support']:
            # Do not compute a clock set from a geometry already contradicted by
            # its intended road scope, even when all training residuals were tiny.
            result=dict(status=support['status'],sync_certified=False,
                        accepted_json_video_clock_transform=None,
                        calibrated_sync_uncertainty_ms=None,production_usable=False,
                        scoring_performed=False,refit=False)
        else:
            result=score_heldout(model,selected[0],points)
            result['conditional_clock_set']=conditional_clock_set(model,selected[0],points,50)
            result['scoring_performed']=True
        result['registration_support']=support
        result['training_model_sha256']=hashlib.sha256(a.model.read_bytes()).hexdigest()
    result.update(source_sample_sha256=hashlib.sha256(raw).hexdigest(),
        points_sha256=hashlib.sha256(a.points.read_bytes()).hexdigest(),
        plan_sha256=hashlib.sha256(a.plan.read_bytes()).hexdigest())
    a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'saved':str(a.out),'sync_certified':False,
                      'registration_status':result['registration_support']['status']}))


if __name__=='__main__':main()
