from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.v10.semantic_mapping import (
    build_phase_specs_from_signal_plan_dict,
    map_v9_to_physical,
    normalized_segments,
)
from app.core.v9.v9_discovery import discover_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Direction-agnostic traffic phase discovery V9"
    )
    parser.add_argument(
        "input",
        type=Path,
        help="JSON file, ZIP archive or directory with JSON trajectory files",
    )
    parser.add_argument(
        "--marks",
        type=Path,
        help="manual marks for post-hoc evaluation only",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("v9_output"),
    )
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument(
        "--physical-plan",
        type=Path,
        help=(
            "JSON produced by discover_signal_plan.py; when supplied, "
            "V10 semantic mapping is added to the V9 result"
        ),
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = discover_path(
        args.input,
        dt=args.dt,
        marks_path=args.marks,
    )

    if args.physical_plan is not None:
        physical_payload = json.loads(
            args.physical_plan.read_text(encoding="utf-8")
        )
        physical_phases = build_phase_specs_from_signal_plan_dict(
            physical_payload
        )
        mapping = map_v9_to_physical(result, physical_phases)
        result["semantic_mapping"] = mapping.to_dict()
        result["schedule"]["physical_segments"] = normalized_segments(
            result,
            mapping.mapping,
        )
        result["schedule"]["physical_phase_names"] = [
            phase.name for phase in physical_phases
        ]

    output = args.output_dir / "phase_discovery_v9.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("[V9] complete")
    print("  period_s:", round(float(result["period_inference"]["period_s"]), 3))
    print("  phases:", result["phase_model_selection"]["selected_phase_count"])
    print("  streams:", result["movement_stream_count"])
    print("  trajectories:", result["trajectory_count"])
    if "semantic_mapping" in result:
        print(
            "  physical_mapping:",
            json.dumps(
                result["semantic_mapping"]["mapping"],
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    print("  result:", output)
    if "evaluation" in result:
        print(
            "  evaluation:",
            json.dumps(result["evaluation"], ensure_ascii=False),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
