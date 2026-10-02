from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import urllib.error
import urllib.request
import uuid

from app.core.v9.events import load_event_views
from app.core.v9.v9_discovery import discover_path


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    intersection: str
    role: str
    filename: str
    description: str


AVAILABLE_DATASETS = (
    DatasetSpec("lenina_entuziastov_reference", "Ленина–Энтузиастов", "reference",
                "Ленина-Энтузиастов 10.02.25-17.02.25.zip",
                "будние дневные данные без наблюдаемых аномалий"),
    DatasetSpec("lenina_entuziastov_accident", "Ленина–Энтузиастов", "accident",
                "Ленина-Энтузиастов 05.10.24.zip", "данные во время ДТП"),
    DatasetSpec("chicherina_reference", "Чичерина–40 Лет Победы", "reference",
                "Чичерина-40 Лет Победы 12.04.24.zip", "данные без аномалии"),
    DatasetSpec("chicherina_lane_closure", "Чичерина–40 Лет Победы", "lane_closure",
                "Чичерина-40 Лет Победы 19.04.24.zip", "перекрытие одной полосы"),
    DatasetSpec("lenina_sverdlovsky_reference", "Ленина–Свердловский", "reference",
                "Ленина-Свердловский 11.02.25-19.02.25.zip", "данные без аномалии"),
    DatasetSpec("lenina_sverdlovsky_accident", "Ленина–Свердловский", "accident",
                "Ленина-Свердловский 27.02.25.zip", "данные во время ДТП"),
)

DATASETS = AVAILABLE_DATASETS


def _run_offline_job(spec: DatasetSpec, path: Path) -> dict[str, object]:
    return summarize_offline(spec, path)


def _stream_flow_rates(row: dict[str, object]) -> dict[str, float]:
    duration_s = float(row.get("recording_duration_s", 0.0))
    if duration_s <= 0.0:
        return {}
    streams = row.get("archive_stream_event_counts", row.get("stream_event_counts", {}))
    if not isinstance(streams, dict):
        return {}
    scale = 3600.0 / duration_s
    items = streams.items()
    return {
        str(stream): float(count) * scale
        for stream, count in items
    }


def _duration_multiset(result: dict[str, object]) -> list[float]:
    values = result.get("schedule", {}).get("baseline_duration_targets_s", {})
    if not isinstance(values, dict):
        return []
    return sorted(float(value) for value in values.values())


def summarize_offline(spec: DatasetSpec, path: Path) -> dict[str, object]:
    result = discover_path(path, dt=1.0)
    physical = result.get("physical_signal_plan")
    physical_enabled = (
        isinstance(physical, dict) and bool(physical.get("enabled"))
    )
    deviations = result.get("anomaly_detection", {}).get(
        "temporary_phase_deviations", []
    )
    stream_names = result.get("movement_streams", {})
    archive = result.get("archive", {})
    return {
        "dataset": asdict(spec),
        "path": str(path),
        "status": "ok",
        "source_file_count": int(archive.get("source_file_count", 0)),
        "trajectory_count": int(result.get("trajectory_count", 0)),
        "event_count": int(result.get("event_count", 0)),
        "recording_duration_s": float(result.get("recording_duration_s", 0.0)),
        "period_s": float(result["period_inference"]["period_s"]),
        "phase_count": int(result["phase_model_selection"]["selected_phase_count"]),
        "phase_durations_s": _duration_multiset(result),
        "stream_count": int(result.get("movement_stream_count", 0)),
        "streams": sorted(stream_names) if isinstance(stream_names, dict) else [],
        "stream_event_counts": {
            str(stream): int(count)
            for stream, count in stream_names.items()
        } if isinstance(stream_names, dict) else {},
        "physical_signal_plan_enabled": physical_enabled,
        "physical_signal_plan_reason": (
            str(physical.get("reason", ""))
            if isinstance(physical, dict) and not physical_enabled
            else None
        ),
        "temporary_phase_deviation_count": (
            len(deviations) if isinstance(deviations, list) else 0
        ),
    }


def _multipart_file(field: str, filename: str, payload: bytes, boundary: str) -> bytes:
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode("utf-8")
    return head + payload + b"\r\n"


def post_analyze(base_url: str, path: Path, *, timeout_s: float) -> dict[str, object]:
    boundary = "----traffic-phase-" + uuid.uuid4().hex
    payload = (
        _multipart_file("file", path.name, path.read_bytes(), boundary)
        + f"--{boundary}--\r\n".encode("ascii")
    )
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/v1/v9/analyze",
        data=payload,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def post_realtime(
    base_url: str,
    *,
    model_id: str,
    stream_id: str,
    timestamp_ms: int,
    stream: str,
    timeout_s: float,
) -> dict[str, object]:
    body = json.dumps(
        {
            "model_id": model_id,
            "stream_id": stream_id,
            "event": {"timestamp_ms": int(timestamp_ms), "stream": stream},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/v1/v9/realtime",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def replay_online(
    spec: DatasetSpec,
    path: Path,
    *,
    base_url: str,
    max_events: int,
    timeout_s: float,
) -> dict[str, object]:
    analysis = post_analyze(base_url, path, timeout_s=timeout_s)
    api = analysis.get("api", {})
    model_id = api.get("model_id") if isinstance(api, dict) else None
    if not isinstance(model_id, str):
        raise RuntimeError("analyze response did not contain api.model_id")

    events, _, _, _, _, _ = load_event_views(path)
    if max_events > 0 and len(events) > max_events:
        step = (len(events) - 1) / max(1, max_events - 1)
        selected = [events[round(index * step)] for index in range(max_events)]
    else:
        selected = events

    stream_id = "benchmark-" + spec.key
    synchronized = 0
    phases: list[str] = []
    confidences: list[float] = []
    final_snapshot: dict[str, object] | None = None

    for timestamp_ms, stream, *_ in selected:
        response = post_realtime(
            base_url,
            model_id=model_id,
            stream_id=stream_id,
            timestamp_ms=int(timestamp_ms),
            stream=str(stream),
            timeout_s=timeout_s,
        )
        snapshot = response.get("snapshot", {})
        if not isinstance(snapshot, dict):
            continue
        final_snapshot = snapshot
        if snapshot.get("status") == "SYNCHRONIZED":
            synchronized += 1
        phase = snapshot.get("phase")
        if isinstance(phase, str):
            phases.append(phase)
        confidence = snapshot.get("confidence")
        if isinstance(confidence, (int, float)):
            confidences.append(float(confidence))

    return {
        "status": "ok",
        "model_id": model_id,
        "event_count_source": len(events),
        "event_count_replayed": len(selected),
        "synchronized_snapshots": synchronized,
        "synchronized_fraction": synchronized / len(selected) if selected else 0.0,
        "distinct_anonymous_phases": sorted(set(phases)),
        "max_confidence": max(confidences) if confidences else 0.0,
        "final_snapshot": final_snapshot,
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def compare_pairs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_key = {row["dataset"]["key"]: row for row in rows}
    pairs = (
        ("lenina_entuziastov_reference", "lenina_entuziastov_accident"),
        ("chicherina_reference", "chicherina_lane_closure"),
        ("lenina_sverdlovsky_reference", "lenina_sverdlovsky_accident"),
    )
    output = []
    for reference_key, anomaly_key in pairs:
        reference = by_key.get(reference_key)
        anomaly = by_key.get(anomaly_key)
        if not reference or not anomaly:
            continue
        rp = float(reference["period_s"])
        ap = float(anomaly["period_s"])
        reference_rates = _stream_flow_rates(reference)
        anomaly_rates = _stream_flow_rates(anomaly)
        common_streams = sorted(set(reference_rates) & set(anomaly_rates))
        flow_changes = {
            stream: {
                "reference_veh_per_h": round(reference_rates[stream], 3),
                "anomaly_veh_per_h": round(anomaly_rates[stream], 3),
                "delta_percent": round(
                    100.0 * (anomaly_rates[stream] - reference_rates[stream])
                    / reference_rates[stream]
                    if reference_rates[stream] > 0.0
                    else 0.0,
                    3,
                ),
            }
            for stream in common_streams
        }
        output.append({
            "reference": reference["dataset"]["filename"],
            "anomaly": anomaly["dataset"]["filename"],
            "period_delta_s": ap - rp,
            "period_delta_percent": 100.0 * (ap - rp) / rp if rp else None,
            "phase_count_reference": reference["phase_count"],
            "phase_count_anomaly": anomaly["phase_count"],
            "phase_count_changed": reference["phase_count"] != anomaly["phase_count"],
            "stream_jaccard": _jaccard(set(reference["streams"]), set(anomaly["streams"])),
            "flow_rates_veh_per_hour": flow_changes,
            "largest_common_stream_drop_percent": (
                min(
                    float(item["delta_percent"])
                    for item in flow_changes.values()
                )
                if flow_changes
                else None
            ),
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run V9 across the six available archives and optionally replay them through FastAPI."
    )
    parser.add_argument("root", type=Path, help="directory containing the six available source ZIP archives")
    parser.add_argument("--output", type=Path, default=Path("v9_dataset_benchmark.json"))
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when any available archive is missing",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="also run analyze -> model_id -> realtime replay against a running API",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--max-online-events",
        type=int,
        default=500,
        help="maximum evenly-spaced events per archive; 0 means all",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="parallel archive workers; 1 is safest for RAM, 2 can reduce wall time",
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    rows_by_key = {}
    missing = []
    jobs = []

    for spec in DATASETS:
        path = args.root / spec.filename
        if not path.is_file():
            missing.append(spec.filename)
            rows_by_key[spec.key] = {
                "dataset": asdict(spec),
                "path": str(path),
                "status": "missing",
            }
        else:
            jobs.append((spec, path))

    def record_row(row):
        rows_by_key[row["dataset"]["key"]] = row
        print(
            f"[V9] {row['dataset']['key']}: {row['status']}",
            flush=True,
        )

    if args.workers == 1:
        for spec, path in jobs:
            print(
                f"[V9] processing {spec.key} ...",
                flush=True,
            )
            try:
                record_row(_run_offline_job(spec, path))
            except Exception as exc:
                record_row({
                    "dataset": asdict(spec),
                    "path": str(path),
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(_run_offline_job, spec, path): spec
                for spec, path in jobs
            }
            for future in as_completed(futures):
                spec = futures[future]
                try:
                    record_row(future.result())
                except Exception as exc:
                    record_row({
                        "dataset": asdict(spec),
                        "path": str(args.root / spec.filename),
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    })

    rows = [
        rows_by_key.get(spec.key, {
            "dataset": asdict(spec),
            "path": str(args.root / spec.filename),
            "status": "error",
            "error": "internal benchmark bookkeeping error",
        })
        for spec in DATASETS
    ]

    errors = [row for row in rows if row.get("status") == "error"]
    if args.strict and (missing or errors):
        if missing:
            print("Missing archives:")
            for filename in missing:
                print("  " + filename)
        if errors:
            print("Archives with errors:")
            for row in errors:
                print("  " + row["dataset"]["filename"] + ": " + str(row.get("error", "")))
        return 2

    if args.online:
        for row, spec in zip(rows, DATASETS):
            if row.get("status") != "ok":
                continue
            try:
                row["online_replay"] = replay_online(
                    spec,
                    args.root / spec.filename,
                    base_url=args.base_url,
                    max_events=args.max_online_events,
                    timeout_s=args.timeout,
                )
            except (
                OSError,
                RuntimeError,
                ValueError,
                urllib.error.URLError,
                json.JSONDecodeError,
            ) as exc:
                row["online_replay"] = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }

    successful = [row for row in rows if row["status"] == "ok"]
    report = {
        "algorithm": "direction-agnostic-v9",
        "manual_labels_used": False,
        "dataset_root": str(args.root),
        "documents_expected": len(DATASETS),
        "archives_found": len(successful),
        "archives_missing": len(missing),
        "archives_with_errors": sum(row["status"] == "error" for row in rows),
        "archives": rows,
        "reference_vs_anomaly": compare_pairs(successful),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("V9 dataset benchmark")
    print("Archives found:", len(successful), "/", len(DATASETS))
    print()
    print("| Intersection | Role | Period, s | Phases | Streams | Physical | Deviations |")
    print("|---|---|---:|---:|---:|---|---:|")
    for row in rows:
        dataset = row["dataset"]
        if row["status"] != "ok":
            print(f"| {dataset['intersection']} | {dataset['role']} | — | — | — | — | — |")
            continue
        print(
            "| {intersection} | {role} | {period:.2f} | {phases} | {streams} | {physical} | {deviations} |".format(
                intersection=dataset["intersection"],
                role=dataset["role"],
                period=row["period_s"],
                phases=row["phase_count"],
                streams=row["stream_count"],
                physical="yes" if row["physical_signal_plan_enabled"] else "no",
                deviations=row["temporary_phase_deviation_count"],
            )
        )

    pairs = report["reference_vs_anomaly"]
    if pairs:
        print()
        print("Reference -> anomaly:")
        for pair in pairs:
            print(
                "  {reference} -> {anomaly}: "
                "period Δ={period_delta_s:+.2f}s ({period_delta_percent:+.2f}%), "
                "phase_count={phase_count_reference}->{phase_count_anomaly}, "
                "stream Jaccard={stream_jaccard:.3f}".format(**pair)
            )
    print()
    print("Report:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
