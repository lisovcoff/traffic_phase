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
        "85",
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
    score = float(model["score"])

    # Regression envelope comes from the manually annotated Lenina cycles:
    # cycle median 99s; EW median 49s; N+arrow median 22s; NS median 30s.
    checks = {
        "cycle": 95 <= period <= 103,
        "EW": 44 <= ew <= 55,
        "N_ARROW": 18 <= arrow <= 26,
        "NS": 24 <= ns <= 34,
        "score": score >= 0.75,
    }

    print(
        f"Lenina regression: T={period}s, EW={ew}s, "
        f"N+arrow={arrow}s, NS={ns}s, score={score:.4f}"
    )

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("FAILED regression checks:", ", ".join(failed))
        return 1

    print("Lenina regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
