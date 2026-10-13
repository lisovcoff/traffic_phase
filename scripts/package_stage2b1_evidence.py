"""Read-only provenance verification and compact ZIP packaging; no model imports."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/stage2b1_verification"
CORE = ["app/core/temporal_evidence.py", "app/core/v9/vehicle_evidence.py",
        "app/core/v9/events.py", "app/core/v9/model.py", "scripts/compare_temporal_evidence.py",
        "tests/test_vehicle_temporal_evidence.py"]
PROTECTED = ["app/core/offline_benchmark.py", "scripts/offline_benchmark.py",
             "app/core/v9/decoder.py", "app/core/v9/fit.py", "app/core/v9/primitives.py",
             "app/core/v10/automatic_physical.py", "app/core/v10/semantic_mapping.py"]


def git(*args, binary=False):
    result = subprocess.check_output(["git", *args], cwd=ROOT)
    return result if binary else result.decode("utf-8").strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def hash_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    refs = {ref: git("rev-parse", ref) for ref in ("aa2c4a3", "161f32f", "afcfaa2", "HEAD", "main")}
    refs["origin_main_live"] = git("ls-remote", "--heads", "origin", "main").split()[0]
    assert refs["main"] == refs["origin_main_live"] == "a005a2521f62ce3b2c9f9d52f9f0d73913754e01"
    links = {ref: git("rev-list", "--parents", "-n", "1", ref).split() for ref in ("161f32f", "afcfaa2", "HEAD")}
    assert links["161f32f"][1] == refs["aa2c4a3"]
    assert links["afcfaa2"][1] == refs["161f32f"]
    assert not git("diff", "161f32f", "afcfaa2", "--", "app", "scripts", "tests")
    protected = {}
    for path in PROTECTED:
        previous = git("show", "aa2c4a3:" + path, binary=True)
        measured = git("show", "161f32f:" + path, binary=True)
        current = git("show", "HEAD:" + path, binary=True)
        assert previous == measured == current
        protected[path] = {"git_blob_sha256": digest(previous), "unchanged": True}
    # Same baseline/deviation functions inside the modified events module.
    original = ast.parse(git("show", "aa2c4a3:app/core/v9/events.py", binary=True).decode())
    current = ast.parse((ROOT / "app/core/v9/events.py").read_text(encoding="utf-8"))
    def functions(tree):
        return {n.name: ast.dump(n, include_attributes=False) for n in tree.body if isinstance(n, ast.FunctionDef)}
    old_f, new_f = functions(original), functions(current)
    for name in ("periodic_baseline_from_segments", "detect_temporary_phase_deviations", "_kinematic_release_candidate"):
        assert old_f[name] == new_f[name]
    (OUT / "producer_code.diff").write_bytes(git("diff", "aa2c4a3", "161f32f", "--", *CORE, binary=True))
    (OUT / "implementation_without_prediction_json.diff").write_bytes(
        git("diff", "aa2c4a3", "afcfaa2", "--", ".",
            ":(exclude)benchmarks/stage2b1_20261013/predictions/**", binary=True))
    (OUT / "contract_clarification.diff").write_bytes(git("diff", "afcfaa2", "HEAD", "--", "app", "tests", binary=True))
    (OUT / "changed_paths.txt").write_text(git("diff", "--name-status", "aa2c4a3", "afcfaa2") + "\n", encoding="utf-8")
    for path in CORE:
        destination = OUT / "producer_source" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(git("show", "161f32f:" + path, binary=True))
    # Artifact verifier reads evaluation reports solely for integrity metadata.
    # Diagnostic worker has no report/annotation argument and does no fitting.
    before_folder = ROOT / "benchmarks/stage2a_20261013"
    after_folder = ROOT / "benchmarks/stage2b1_20261013"
    before = json.loads((before_folder / "baseline_metrics.json").read_text(encoding="utf-8"))
    after = json.loads((after_folder / "baseline_metrics.json").read_text(encoding="utf-8"))
    assert before["config"] == after["config"] and before["config_sha256"] == after["config_sha256"]
    assert before["config"]["boundary_tolerance_s"] == 2.0
    old_rows = {r["source_name"]: r for r in before["rows"]}
    inputs = []
    for row in after["rows"]:
        old = old_rows[row["source_name"]]
        entry = {"source": row["source_name"]}
        for key, file_key in (("source_sha256", "source_path"), ("annotation_sha256", "annotation_path")):
            assert row[key] == old[key] == hash_file(Path(row[file_key]))
            entry[key] = row[key]
        inputs.append(entry)
    artifacts = {}
    attachments = []
    for label, folder in (("before", before_folder), ("after", after_folder)):
        for path in sorted(folder.rglob("*.json")):
            relative = str(path.relative_to(ROOT)).replace("\\", "/")
            measured_commit = "aa2c4a3" if label == "before" else "afcfaa2"
            data = path.read_bytes()
            blob = git("show", measured_commit + ":" + relative, binary=True)
            # Historical write_text() emitted Windows CRLF, Git stored LF.
            # Preserve original raw bytes in ZIP and record both digests; never
            # rewrite old predictions/reports or silently ignore this mismatch.
            assert data.replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n")
            artifacts[relative] = {"sha256": digest(data), "git_blob_sha256": digest(blob),
                                   "bytes": len(data), "unchanged_content_from": refs[measured_commit],
                                   "raw_bytes_equal_git_blob": data == blob,
                                   "newline_normalized_equal_git_blob": True}
            attachments.append((path, "artifacts/" + label + "/" + str(path.relative_to(folder)).replace("\\", "/")))
        report = before if label == "before" else after
        for row in report["rows"]:
            assert hash_file(folder / row["prediction_file"]) == row["prediction_sha256_before_evaluation"]
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.suffix not in {".zip"} and path.name not in {"manifest.json", "archive_sha256.json"}:
            artifacts[str(path.relative_to(ROOT)).replace("\\", "/")] = {"sha256": hash_file(path), "bytes": path.stat().st_size}
    for name in ("verify_stage2b1.py", "package_stage2b1_evidence.py"):
        path = ROOT / "scripts" / name
        artifacts["scripts/" + name] = {"sha256": hash_file(path), "bytes": path.stat().st_size}
        attachments.append((path, "diagnostic_tools/" + name))
    manifest = {"refs": refs, "parents": links, "producer_code_unchanged_161f_to_afcf": True,
                "protected_files": protected, "protected_functions_AST_unchanged": True,
                "config": before["config"], "config_sha256": before["config_sha256"], "inputs": inputs,
                "artifacts": artifacts,
                "historical_artifact_newline_issue": "Windows raw CRLF hashes in reports differ from Git LF blob hashes; ZIP preserves exact run bytes. Fresh LF checkout cannot validate historical raw digests directly.",
                "diagnostic_no_labels_boundary": "verify_stage2b1 worker opens predictions and raw trajectories only; integrity verifier reads reports/digests without inference",
                "no_new_full_benchmark": True}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive_path = OUT / "stage2b1_evidence.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(OUT.rglob("*")):
            if path.is_file() and path != archive_path and path.name != "archive_sha256.json":
                archive.write(path, "verification/" + str(path.relative_to(OUT)).replace("\\", "/"))
        for path, name in attachments:
            archive.write(path, name)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
    (OUT / "archive_sha256.json").write_text(json.dumps({"archive": archive_path.name,
        "sha256": hash_file(archive_path), "bytes": archive_path.stat().st_size}, indent=2) + "\n", encoding="utf-8")
    print("verified and packaged", archive_path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
