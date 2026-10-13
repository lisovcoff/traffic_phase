"""Verify contract on frozen predictions; never fit or open trajectory/label files."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

from app.core.state_contract import attach_state_contract, logical_phase_at

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/stage2b2_state_contract"
BASE = "afcfaa2b38e106201d7e819570425acfc4c5487f"


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False).encode()).hexdigest()


def union_length(intervals):
    total, end = 0., float('-inf')
    for a,b in sorted(intervals):
        total += max(0,b-max(a,end)); end=max(end,b)
    return total


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    report=[]
    for path in sorted((ROOT/"benchmarks/stage2b1_20261013/predictions").glob("*_v9.json")):
        data=path.read_bytes(); before=json.loads(data); after=copy.deepcopy(before)
        attach_state_contract(after)
        # Full schedule equality covers K, period, raw and baseline segments and scores.
        assert before["schedule"] == after["schedule"]
        assert before["phase_model_selection"] == after["phase_model_selection"]
        assert before["period_inference"] == after["period_inference"]
        schedule=after["schedule"]; segments=schedule["raw_hsmm_segments"]
        intervals=[[a,b] for a,b,_ in segments]
        lo,hi=min(a for a,b in intervals),max(b for a,b in intervals)
        query_times=sorted(set([lo-1,hi,hi+1]+[(a+b)/2 for a,b in intervals]))
        queries=[logical_phase_at(after,t).to_dict() for t in query_times]
        assert sum(q["estimated_state"]=="UNKNOWN" for q in queries)>=3
        assert after["state_contract"]["physical_section"]["estimated_state"]=="UNKNOWN"
        assert data==path.read_bytes()
        report.append({"recording":path.stem,"input_sha256":hashlib.sha256(data).hexdigest(),
            "schedule_sha256_before":digest(before["schedule"]),"schedule_sha256_after":digest(schedule),
            "K":schedule["phase_count"],"period_s":schedule["period_s"],
            "raw_segments_count":len(segments),"baseline_segments_count":len(schedule["baseline_segments"]),
            "raw_segments_sha256":digest(segments),"baseline_segments_sha256":digest(schedule["baseline_segments"]),
            "raw_model_history_extent_s":[lo,hi],"raw_model_history_coverage_s":union_length(intervals),
            "coverage_semantics":"model_history_NOT_lamp_accuracy_or_observation_support",
            "physical_section_unknown_percent_on_temporally_covered_history":100,
            "physical_section_count":None,"section_count_reason":"hardware_layout_unverified",
            "physical_abstention_reason":after["state_contract"]["physical_section"]["abstention_reason"],
            "logical_query_count":len(queries),"logical_unknown_query_count":sum(q["estimated_state"]=="UNKNOWN" for q in queries),
            "logical_queries":queries,"contract":after["state_contract"]})
    assert len(report)==3
    protected=["app/core/v9/fit.py","app/core/v9/decoder.py","app/core/v9/primitives.py",
               "app/core/v9/vehicle_evidence.py","app/core/v10/automatic_physical.py"]
    subprocess.run(["git","diff","--exit-code",BASE,"--",*protected],cwd=ROOT,check=True)
    subprocess.run(["git","diff","--exit-code",BASE,"--","benchmarks"],cwd=ROOT,check=True)
    manifest={"base_sha":BASE,"uncertainty_source_sha":"1207344bdcbc46edbf19bace65382ee0252d1f4d",
              "runner_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
              "protected_git_blobs":{p:subprocess.check_output(["git","rev-parse",BASE+":"+p],cwd=ROOT,text=True).strip() for p in protected},
              "new_fitting_runs":0,"benchmark_runs":0,"trajectory_reads":0,"annotation_reads":0,
              "verification":"exact saved schedule/selection/period equality; not independent lamp validation"}
    for name,value in [("manifest.json",manifest),("prediction_contract_checks.json",report)]:
        with (OUT/name).open("x",encoding="utf-8",newline="\n") as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write("\n")
    print("3 frozen predictions: schedule, K, period, raw/baseline segments and selection unchanged.")
    for row in report:
        print(row["recording"],"K=",row["K"],"period=",row["period_s"],
              "model coverage s=",round(row["raw_model_history_coverage_s"],3),"physical UNKNOWN=100%")


if __name__=="__main__":
    run()
