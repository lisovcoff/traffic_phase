"""Fresh visible-lamp endpoints; deliberately imports no traffic predictor."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from scripts.corpus_validation import prepare_worker_environment,save
prepare_worker_environment()
from scripts.sample_video_truth import sample


def main():
    root=Path(__file__).resolve().parents[1]
    out=root/'evidence/accuracy_recovery_20261019/video_holdout'
    runtime=root/'.web_runtime/accuracy_recovery_20261019/video_native'
    targets=[dict(color=color,target_s=t+100*i,index=i) for i in range(3)
        for color,t in [('GREEN',2119.),('YELLOW',2167.),('RED',2170.)]]
    save(out/'native_plan.json',dict(rows=targets,selection='video-only coarse frames2100..2400, visually inspected',
        predicted_times_read=False,frozen_clock_reused=True,source_head='N main'))
    def collect(row):
        folder=runtime/f"{row['color']}_{row['index']}"
        return sample('sverdlovsky',row['target_s']-.4,row['target_s']+.4,folder,spacing_s=None,max_frames=30)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for report in pool.map(collect,targets):print(report['range_s'],len(report['frames']),flush=True)


if __name__=='__main__':main()
