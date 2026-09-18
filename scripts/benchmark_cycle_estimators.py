from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.cycle_comparison import compare_cycle_estimators


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare trajectory-based and event-based cycle estimators."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    report = []
    for path in args.paths:
        result = compare_cycle_estimators(path)
        row = {"file": str(path), **result.to_dict()}
        report.append(row)

        print(f"\n{path}")
        for method in ("trajectory_based", "event_based"):
            item = row[method]
            print(
                f"{method}: cycle={item['estimated_cycle']:.2f}s "
                f"strength={item['autocorrelation_strength']:.4f} "
                f"confidence={item['confidence']:.4f} "
                f"used_events={item['used_events']} "
                f"used_trajectories={item['used_trajectories']}"
            )
            print(
                "  candidates:",
                [
                    candidate["period_seconds"]
                    for candidate in item["candidate_periods"]
                ],
            )

    print("\nJSON report")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
