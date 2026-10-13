"""Bounded offline V9 benchmark. Worker interface accepts trajectories only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from app.core.offline_benchmark import evaluate_prediction, validate_annotation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = {"dt_s": 1.0, "boundary_tolerance_s": 2.0,
                  "grid_ms": 1000, "timeout_per_file_s": 90.0,
                  "mode": "offline_full_single_json", "split": "development_regression",
                  "movement_mapping": None, "seed": 0,
                  "boundary_endpoints": "exclude_first_and_last_truth_marks"}


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def code_manifest():
    files = sorted([*ROOT.glob("app/core/**/*.py"), ROOT / "scripts/offline_benchmark.py"])
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha256_file(p) for p in files}
    return {"git_commit": git("rev-parse", "HEAD"), "git_branch": git("branch", "--show-current"),
            "working_tree_status": git("status", "--porcelain"),
            "file_hashes": hashes, "code_digest": hashlib.sha256(canonical_bytes(hashes)).hexdigest()}


def inspect_prefix(path, limit=1024 * 1024):
    """Inspect bounded JSON prefix. Never claim its range represents the file."""
    with path.open("rb") as stream:
        text = stream.read(limit).decode("utf-8")
    if not text.lstrip().startswith("["):
        return {"status": "invalid_root", "reason": "trajectory_root_not_array"}
    decoder, remaining, rows = json.JSONDecoder(), text.lstrip()[1:], []
    for _ in range(16):
        remaining = remaining.lstrip(" ,\r\n\t")
        if remaining.startswith("]"):
            break
        try:
            row, end = decoder.raw_decode(remaining)
        except json.JSONDecodeError:
            break
        if not isinstance(row, dict):
            return {"status": "invalid_record", "reason": "trajectory_record_not_object"}
        rows.append(row)
        remaining = remaining[end:]
    times = [d["millis"] for r in rows for d in r.get("detections", [])
             if isinstance(d, dict) and isinstance(d.get("millis"), (int, float))]
    return {"status": "ok" if rows else "no_complete_record_in_prefix",
            "bytes_read_at_most": limit, "complete_sample_tracks": len(rows),
            "track_keys": sorted({k for r in rows for k in r}),
            "detection_keys": sorted({k for r in rows for d in r.get("detections", []) if isinstance(d, dict) for k in d}),
            "sample_range_ms": [min(times), max(times)] if times else None,
            "interpretation": "prefix_schema_sample_not_full_recording_range"}


def infer_to_file(source: Path, output: Path, dt: float, discover=None):
    # Annotation paths, payloads, phase names and semantic mappings are deliberately
    # absent from this interface. A single file is required, never its directory.
    if not source.is_file() or source.suffix.lower() != ".json" or source.name.endswith("_manual_marks.json"):
        raise ValueError("inference requires a single trajectory JSON, not annotations or directories")
    if discover is None:
        import numpy as np
        np.random.seed(DEFAULT_CONFIG["seed"])
        from app.core.v9.model import discover_path
        discover = discover_path
    prediction = discover(source, dt=dt)  # Never pass marks_path, even an empty payload.
    if "evaluation" in prediction:
        raise ValueError("prediction unexpectedly contains label-based evaluation")
    write_json(output, prediction)


def fixture_overlap(annotation):
    truth = {m["timestamp_ms"] for m in annotation.get("marks", [])}
    rows = []
    for path in sorted((ROOT / "tests/fixtures").glob("*marks*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            times = {m["timestamp_ms"] for m in payload.get("marks", [])}
        except (ValueError, KeyError, TypeError):
            continue
        rows.append({"fixture": str(path.relative_to(ROOT)), "sha256": sha256_file(path),
                     "same_timestamp_count": len(truth & times),
                     "interpretation": "timestamp_overlap_check_not_proof_of_independence"})
    return rows


def run_benchmark(data_dir, output_dir, config):
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "config": config,
              "config_sha256": hashlib.sha256(canonical_bytes(config)).hexdigest(),
              "code": code_manifest(),
              "runtime": {"python": sys.version, "platform": platform.platform(),
                          "packages": {n: importlib.metadata.version(n) for n in ("numpy", "scipy", "scikit-learn")}},
              "timezone": "Asia/Yekaterinburg", "rows": [],
              "interpretation": "development regression phase benchmark; NOT independent physical lamp accuracy",
              "inference_contract": "trajectory file only; no marks, no test phase mapping, no time offset fitting",
              "metrics_scope": "truth intervals between first and last marks; interior transitions only"}
    marks_files = sorted(data_dir.glob("*.json_manual_marks.json"))
    if not marks_files:
        report["status"] = "no_annotations_found"
    for marks_path in marks_files:
        name = marks_path.name.removesuffix("_manual_marks.json")
        source = data_dir / name
        row = {"source_name": name, "source_path": str(source.resolve()),
               "annotation_path": str(marks_path.resolve()),
               "annotation_sha256": sha256_file(marks_path)}
        print(f"Inspect {name}", flush=True)
        try:
            annotation = validate_annotation(json.loads(marks_path.read_text(encoding="utf-8")))
            row["annotation_validation"] = annotation
            row["fixture_overlap"] = fixture_overlap(annotation)
            if not annotation["valid"]:
                row.update(status="invalid_annotation", reason=annotation["errors"])
            elif not source.is_file():
                row.update(status="missing_trajectory", reason="paired_source_not_found")
            else:
                row["source_sha256"] = sha256_file(source)
                row["source_bytes"] = source.stat().st_size
                row["source_schema_sample"] = inspect_prefix(source)
                prediction_path = output_dir / "predictions" / (source.stem + "_v9.json")
                if prediction_path.exists():
                    raise ValueError("prediction already exists; choose a new output directory to avoid stale results")
                started = time.monotonic()
                env = {**os.environ, "PYTHONHASHSEED": str(config["seed"]),
                       "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
                print(f"Infer {name}; timeout={config['timeout_per_file_s']}s", flush=True)
                try:
                    process = subprocess.run([sys.executable, "-m", "scripts.offline_benchmark", "infer",
                                              str(source.resolve()), str(prediction_path.resolve()),
                                              "--dt", str(config["dt_s"])],
                                             cwd=ROOT, env=env, capture_output=True, text=True,
                                             timeout=config["timeout_per_file_s"])
                except subprocess.TimeoutExpired:
                    row.update(status="inference_timeout", reason="fixed_resource_budget_exceeded")
                else:
                    if process.returncode:
                        row.update(status="inference_failed", reason=process.stderr[-4000:])
                    else:
                        # Disk artifact and its hash exist before any label-based scoring.
                        row["prediction_file"] = str(prediction_path.relative_to(output_dir)).replace("\\", "/")
                        row["prediction_sha256_before_evaluation"] = sha256_file(prediction_path)
                        prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
                        row["prediction_summary"] = {k: prediction.get(k) for k in
                            ("trajectory_count", "event_count", "movement_stream_count", "recording_start_timestamp_ms",
                             "schedule_base_timestamp_ms", "recording_duration_s", "phase_evidence", "regime_detection")}
                        row["metrics"] = evaluate_prediction(prediction, annotation,
                                                              tolerance_s=config["boundary_tolerance_s"])
                        assert row["prediction_sha256_before_evaluation"] == sha256_file(prediction_path)
                        row["status"] = "ok"
                row["inference_runtime_s"] = round(time.monotonic() - started, 3)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            row.update(status="evaluation_failed", reason=str(exc))
        if row.get("status") != "ok":
            row["metrics"] = {"status": "unavailable", "reason": row.get("reason"),
                              "n_observations": 0,
                              "range_ms": row.get("annotation_validation", {}).get("known_range_ms")}
        report["rows"].append(row)
        write_json(output_dir / "baseline_metrics.json", report)
        print(f"Done {name}: {row['status']}", flush=True)
    report["status"] = "ok" if report["rows"] and all(r["status"] == "ok" for r in report["rows"]) else "partial_or_unavailable"
    write_json(output_dir / "baseline_metrics.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    infer = sub.add_parser("infer")
    infer.add_argument("source", type=Path)
    infer.add_argument("output", type=Path)
    infer.add_argument("--dt", type=float, default=1.0)
    bench = sub.add_parser("run")
    bench.add_argument("--data-dir", type=Path, required=True)
    bench.add_argument("--out", type=Path, required=True)
    bench.add_argument("--timeout", type=float, default=DEFAULT_CONFIG["timeout_per_file_s"])
    args = parser.parse_args()
    if args.command == "infer":
        if not math_is_positive(args.dt):
            parser.error("--dt must be positive and finite")
        infer_to_file(args.source, args.output, args.dt)
        return 0
    if not args.data_dir.is_dir() or not math_is_positive(args.timeout):
        parser.error("existing data directory and positive finite timeout required")
    config = {**DEFAULT_CONFIG, "timeout_per_file_s": args.timeout}
    return 0 if run_benchmark(args.data_dir, args.out, config)["status"] == "ok" else 1


def math_is_positive(value):
    import math
    return math.isfinite(value) and value > 0


if __name__ == "__main__":
    raise SystemExit(main())
