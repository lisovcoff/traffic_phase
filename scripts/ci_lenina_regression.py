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

    # The earlier 80s envelope came from a short transient video interval.
    # The full manual fixture contains repeated boundaries across ~21 minutes;
    # phase-folding those marks at T=100s gives approximately:
    #   EW -> N_ARROW: 48s
    #   N_ARROW -> NS: 21s
    #   NS -> EW: 31s
    # Use conservative envelopes around that observed structure. This is a
    # benchmark for the annotated Lenina interval, not controller telemetry
    # and not independently verified lamp-color ground truth.
    checks = {
        "cycle": 96 <= period <= 104,
        "EW": 42 <= ew <= 52,
        "N_ARROW": 18 <= arrow <= 28,
        "NS": 26 <= ns <= 34,
    }

    print(
        f"Lenina regression: T={period}s, EW={ew}s, "
        f"N+arrow={arrow}s, NS={ns}s"
    )

    boundary_metrics = {}
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

    # Manual boundary MAE is diagnostic rather than a hard gate for now:
    # the marks are human observations and may miss a transition by several
    # seconds or omit a cycle. Duration/period envelopes remain the primary
    # regression gate until we have independently verified transition timing.
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("FAILED regression checks:", ", ".join(failed))
        return 1

    print("Lenina regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
