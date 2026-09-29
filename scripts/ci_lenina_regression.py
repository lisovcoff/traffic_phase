from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Lenina three-state kinematic regression."
    )
    parser.add_argument("trajectory_json", type=Path)
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

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("FAILED regression checks:", ", ".join(failed))
        return 1

    print("Lenina regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
