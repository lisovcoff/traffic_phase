"""Record the completed visual endpoint review before conditional model scoring."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from scripts.video_truth_inventory import OUT,save


def main():
    site=OUT/'sverdlovsky';source=site/'video_only_truth_proposal_v2.json'
    data=json.loads(source.read_text(encoding='utf8'))
    for window in data['windows']:
        for row in window['transitions']:
            row['visual_review_status']='CODEX_NATIVE_ENDPOINT_REVIEWED_NO_SECOND_HUMAN_REVIEW'
            for key in ('before','after'):
                frame=row[key];assert hashlib.sha256((OUT/frame['file']).read_bytes()).hexdigest()==frame['sha256']
    data.update(proposal_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        reviewed_truth=True,review='Both v2 endpoint sheets inspected; old red/amber and new main green appearance verified. Validation4 deliberately keeps2.467s bracket; do not replace by LED-dark-to-green0.1s.',
        physical_lamp_timing_calibrated=False,prediction_data_used_to_choose_labels=False,
        clock_mapping_accepted=False)
    save(site/'video_only_truth_sealed.json',data)
    reads={
      'sverdlovsky':['27-02-2025 09:59:55','27-02-2025 10:14:55','27-02-2025 10:44:55','27-02-2025 10:59:55'],
      'enthusiasts':['05-10-2024 11:59:58','05-10-2024 12:14:58','05-10-2024 12:44:58','05-10-2024 12:59:58']}
    result=[]
    for name,values in reads.items():
        inventory=json.loads((OUT/name/'inventory.json').read_text(encoding='utf8'))
        rows=[]
        for frame,text in zip(inventory['frames'],values):
            date=datetime.strptime(text,'%d-%m-%Y %H:%M:%S').replace(tzinfo=timezone(timedelta(hours=5)))
            epoch=date.timestamp()*1000
            rows.append(dict(pts_s=frame['pts_s'],display=text,display_epoch_ms=epoch,
                clock_crop=frame['clock'],sha256=frame['clock_sha256'],
                floor_model_base_bounds_ms=[epoch-frame['pts_s']*1000,epoch+1000-frame['pts_s']*1000]))
        bounds=[max(r['floor_model_base_bounds_ms'][0] for r in rows),min(r['floor_model_base_bounds_ms'][1] for r in rows)]
        result.append(dict(site=name,readouts=rows,visual_reviewed=True,overlay_resolution_s=1,
            conditional_floor_camera_base_ms=bounds,timezone='UTC+5 interpreted from project location',
            rounding_and_overlay_exposure_latency='UNKNOWN',json_sync_verified=False,
            nominal_base_ms=rows[0]['display_epoch_ms'],clock_fit_from_signals=False))
    save(OUT/'clock_readouts.json',result)
    print('Sealed12 Sverd main-green appearances and8 clock readouts; JSON synchronization still unverified')


if __name__=='__main__':main()
