from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.validation import ValidationDataset, ValidationRunner, write_report


def load_manifest(path: Path) -> list[ValidationDataset]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    datasets = payload.get("datasets", [])
    if not datasets:
        raise ValueError("manifest must contain datasets")
    manifest_dir = path.parent.resolve()
    return [
        ValidationDataset(
            name=str(item["name"]),
            path=(
                str((manifest_dir / str(item["path"])).resolve())
                if not Path(str(item["path"])).is_absolute()
                else str(Path(str(item["path"])).resolve())
            ),
            kind=str(item.get("kind", "scenario")),
            description=str(item.get("description", "")),
        )
        for item in datasets
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the complete traffic-phase validation pipeline."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("validation_output"),
    )
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument(
        "--transition-tolerance-seconds",
        type=float,
        default=3.0,
    )
    args = parser.parse_args()

    datasets = load_manifest(args.manifest)

    def progress(message: str) -> None:
        print(f"[validation] {message}", flush=True)

    report = ValidationRunner(
        datasets,
        sample_seconds=args.sample_seconds,
        transition_tolerance_seconds=args.transition_tolerance_seconds,
        progress=progress,
    ).run()
    json_path, markdown_path = write_report(report, args.output_dir)

    print(f"machine_report={json_path}")
    print(f"human_report={markdown_path}")
    print(markdown_path.read_text(encoding="utf-8"))

    errors = []
    for item in report.get("datasets", []):
        for section in ("cycle", "phase", "signal", "realtime"):
            if item.get(section, {}).get("status") == "error":
                errors.append(
                    f"{item['dataset']['name']}: {section}: "
                    f"{item[section].get('error', 'unknown error')}"
                )
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(error)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
