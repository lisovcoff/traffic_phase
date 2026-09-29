from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _manual_boundary_metrics(
    manual_path: Path,
    *,
    period: int,
    origin: int,
    anchor_ms: int,
    ew: int,
    arrow: int,
    ns: int,
) -> dict[str, tuple[float, float]]:
    data = json.loads(manual_path.read_text(encoding="utf-8"))
    manual_start_ms = int(data["start_ms"])
    # origin is relative to the trajectory-event anchor, while manual marks
    # are relative to the manual fixture start. Convert both to one clock
    # before computing circular boundary errors.
    anchor_offset_s = (anchor_ms - manual_start_ms) / 1000.0
    absolute_origin = anchor_offset_s + float(origin)
    predicted = {
        "EW": absolute_origin,
        "N_ARROW": absolute_origin + ew,
        "NS": absolute_origin + ew + arrow,
    }
    result: dict[str, tuple[float, float]] = {}
    for kind, phase in predicted.items():
        marks = [
            float(mark["offset_s"])
            for mark in data.get("marks", [])
            if mark.get("kind") == kind and "offset_s" in mark
        ]
        if not marks:
            continue
        errors = []
        for timestamp in marks:
            error = abs(
                ((timestamp - phase + period / 2.0) % period)
                - period / 2.0
            )
            errors.append(error)
        result[kind] = (sum(errors) / len(errors), max(errors))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Lenina three-state kinematic regression."
    )
    parser.add_argument("trajectory_json", type=Path)
    parser.add_argument(
        "--manual-marks",
        type=Path,
        default=Path("tests/fixtures/lenina_manual_signal_marks.json"),
    )
    args = parser.parse_args()

    output = Path("lenina_ci_three_state_cycle.json")
    command = [
        sys.executable,
        "-m",
        "scripts.discover_three_state_kinematic_cycle",
        str(args.trajectory_json),
        "--output",
        str(output),
        "--min-cycle",
        "60",
        "--max-cycle",
        "110",
    ]

    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        return completed.returncode

    result = json.loads(output.read_text(encoding="utf-8"))
    model = result["selected_model"]

    period = int(result["selected_cycle_seconds"])
    ew = int(model["EW_duration_s"])
    arrow = int(model["N_ARROW_duration_s"])
    ns = int(model["NS_duration_s"])

    # Regression envelope is derived from the user's manual video annotation:
    # EW -> N+arrow -> NS repeats every 80s, with approximately 30s/20s/30s.
    # This is a benchmark for the observed Lenina interval, not controller
    # telemetry and not an independently verified lamp-color ground truth.
    checks = {
        "cycle": 78 <= period <= 82,
        "EW": 27 <= ew <= 33,
        "N_ARROW": 17 <= arrow <= 23,
        "NS": 27 <= ns <= 33,
    }

    print(
        f"Lenina regression: T={period}s, EW={ew}s, "
        f"N+arrow={arrow}s, NS={ns}s"
    )

    if args.manual_marks.exists():
        boundary_metrics = _manual_boundary_metrics(
            args.manual_marks,
            period=period,
            origin=int(result["origin_offset_s"]),
            anchor_ms=int(result["origin_anchor_timestamp_ms"]),
            ew=ew,
            arrow=arrow,
            ns=ns,
        )
        print("Manual boundary diagnostics:")
        for kind in ("EW", "N_ARROW", "NS"):
            metrics = boundary_metrics.get(kind)
            if metrics is None:
                continue
            mae, max_error = metrics
            print(f"  {kind}: MAE={mae:.2f}s max={max_error:.2f}s")

    # Diagnostic comparison for the known competing hypotheses.  Keep this
    # in CI so a failed regression tells us which part of the objective makes
    # 78/80/95/100-second candidates win, instead of requiring a local rerun.
    print("Lenina candidate diagnostics:")
    candidates = result.get("candidate_cycles", [])
    by_period = {
        int(item["cycle_seconds"]): item
        for item in candidates
        if int(item["cycle_seconds"]) in {78, 80, 95, 100}
    }
    for candidate_period in (78, 80, 95, 100):
        item = by_period.get(candidate_period)
        if item is None:
            print(f"  T={candidate_period}s: not available")
            continue
        print(
            f"  T={candidate_period}s "
            f"joint={item['score']:.4f} "
            f"phase={item['phase_fit_score']:.4f} "
            f"periodicity={item['release_periodicity_score']:.4f} "
            f"EW={item['EW_duration_s']} "
            f"N+arrow={item['N_ARROW_duration_s']} "
            f"NS={item['NS_duration_s']}"
        )

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("FAILED regression checks:", ", ".join(failed))
        return 1

    print("Lenina regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
