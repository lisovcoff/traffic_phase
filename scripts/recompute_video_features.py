"""Reclassify existing shaded-camera crops without decoding or prediction use."""
import hashlib
import json
from pathlib import Path
from scripts.sample_video_truth import features
from scripts.video_truth_inventory import LOCAL,save


def main():
    for window in ('calibration','validation'):
        old=LOCAL/'enthusiasts'/window;new=old.with_name(window+'_v2')
        new.mkdir(exist_ok=False)
        data=json.loads((old/'frames.json').read_text(encoding='utf8'))
        for row in data['frames']:
            source=old/row['file'];assert hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256']
            row.update(features(source,'enthusiasts'))
            row['file']='../'+window+'/'+source.name
        data.update(feature_revision='cyan green from native shaded-camera review; G>45,G>1.30R,G>.75B',
                    original_features_preserved=True,prediction_data_read=False)
        save(new/'frames.json',data)
        print(window,'recomputed existing crops',len(data['frames']))


if __name__=='__main__':main()
