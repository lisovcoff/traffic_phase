from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.phase_comparison import compare_phase_discovery


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare old and event-based traffic phase discovery."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    report = []
    for path in args.paths:
        comparison = compare_phase_discovery(path)
        row = {"file": str(path), **comparison.to_dict()}
        report.append(row)

        print(f"\n{path}")
        for model_name in ("old", "event_based"):
            model = row[model_name]
            print(
                f"{model_name}: cycle={model['cycle_seconds']:.2f}s "
                f"coverage={model['cycle_coverage']:.4f} "
                f"overlap={model['overlap']:.4f} "
                f"support={model['supporting_event_count']} "
                f"contradictory={model['contradictory_event_count']}"
            )
            for phase in model["phases"]:
                print("  ", json.dumps(phase, ensure_ascii=False))

    print("\nJSON report")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
