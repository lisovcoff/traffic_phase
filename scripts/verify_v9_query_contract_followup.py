"""Frozen-prediction core queries only: no trajectory/label access or fitting."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

from app.core.state_contract import prepare_logical_query
from app.core.v9.signal_renderer import build_signal_model, signal_state_at
from app.core.v10.semantic_mapping import signal_state_at as v10_state_at

ROOT=Path(__file__).resolve().parents[1]
BASE="8bb7ca1a9d8137001028f2c6b6e8e6af98d42201"
OUT=ROOT/"evidence/stage2b2_v9_query_followup"


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False).encode()).hexdigest()


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    report=[]
    for path in sorted((ROOT/"benchmarks/stage2b1_20261013/predictions").glob("*_v9.json")):
        data=path.read_bytes(); result=json.loads(data); original=copy.deepcopy(result)
        model=build_signal_model(result)
        assert model.logical_query.validation_error is None
        configured=build_signal_model(result,mode="configured")
        assert configured.logical_query.validation_error is None
        query=prepare_logical_query(result)
        segments=query.segments
        lo,hi=segments[0][0],segments[-1][1]
        times=sorted(set([lo-1,hi,hi+1]+[(a+b)/2 for a,b,_ in segments]+[a for a,b,_ in segments]))
        summaries=[]
        for t in times:
            expected=query.at(t).to_dict()
            v9=signal_state_at(model,t)
            v10=v10_state_at(result,t,[],{},query_model=query)
            assert v9["logical_phase"]==v10["logical_phase"]==expected
            assert v9["physical_section"]["estimated_state"]=="UNKNOWN"
            assert v10["physical_section"]["estimated_state"]=="UNKNOWN"
            for stream in v9["streams"]:
                assert stream["state"]==stream["estimated_state"]=="UNKNOWN"
                assert stream["transition"] is None
                assert stream["calibrated_lamp_probability"] is None
            json.dumps(v9,allow_nan=False)
            summaries.append({"timestamp_s":t,"logical_phase":expected["estimated_state"],
                "logical_reason":expected["abstention_reason"],
                "physical_reason":v9["physical_section"]["abstention_reason"],
                "stream_count":len(v9["streams"]),"physical_unknown_count":len(v9["streams"])})
        assert result==original
        assert data==path.read_bytes()
        report.append({"prediction":str(path.relative_to(ROOT)),"file_sha256":hashlib.sha256(data).hexdigest(),
            "K":result["schedule"]["phase_count"],"period_s":result["schedule"]["period_s"],
            "invariants":{k:{"before_sha256":digest(original[k]),"after_sha256":digest(result[k])}
                          for k in ("schedule","phase_model_selection","period_inference")},
            "raw_segments_sha256":digest(result["schedule"]["raw_hsmm_segments"]),
            "baseline_segments_sha256":digest(result["schedule"]["baseline_segments"]),
            "model_history_extent_s":[lo,hi],"model_history_coverage_s":sum(b-a for a,b,_ in segments),
            "coverage_semantics":"validated_model_history_NOT_observed_lamp_coverage_or_accuracy",
            "physical_unknown_percent_on_covered_queries":100,
            "logical_unknown_query_count":sum(q["logical_phase"]=="UNKNOWN" for q in summaries),
            "query_count":len(summaries),"queries":summaries})
    assert len(report)==3
    protected=["app/core/v9/model.py","app/core/v9/events.py","app/core/v9/vehicle_evidence.py",
        "app/core/v9/fit.py","app/core/v9/decoder.py","app/core/v9/primitives.py",
        "app/core/v10/automatic_physical.py","benchmarks","app/api","app/templates","app/static",
        "scripts/v9_offline_visualizer.py","scripts/v9_spatial_visualizer.py"]
    subprocess.run(["git","diff","--exit-code",BASE,"--",*protected],cwd=ROOT,check=True)
    manifest={"base_sha":BASE,
        "implementation_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "protected_paths_unchanged":protected,"fitting_runs":0,"benchmark_runs":0,
        "trajectory_reads":0,"annotation_reads":0,"query_mode":"reconstructed",
        "query_validation":"once per prepared snapshot; core query binary search; no automatic mutable-input cache",
        "millis_source":"user-provided description from Инфо.docx: time vehicle left intersection; synchronization unverified"}
    for name,value in (("manifest.json",manifest),("prediction_query_checks.json",report)):
        with (OUT/name).open("x",encoding="utf-8",newline="\n") as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write("\n")
    print("3 frozen predictions: schedule/selection/period exact; V9/V10 queries share contract.")
    for row in report:
        print(row["prediction"],"K",row["K"],"period",row["period_s"],
              "queries",row["query_count"],"logical UNKNOWN",row["logical_unknown_query_count"],"physical UNKNOWN 100%")


if __name__=="__main__":
    run()
