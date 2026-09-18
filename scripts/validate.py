from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.validation import ValidationDataset, ValidationRunner, write_report


def load_manifest(path: Path) -> list[ValidationDataset]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    datasets = payload.get("datasets", [])
    if not datasets:
        raise ValueError("manifest must contain datasets")
    return [
        ValidationDataset(
            name=str(item["name"]),
            path=str(item["path"]),
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
    report = ValidationRunner(
        datasets,
        sample_seconds=args.sample_seconds,
        transition_tolerance_seconds=args.transition_tolerance_seconds,
    ).run()
    json_path, markdown_path = write_report(report, args.output_dir)

    print(f"machine_report={json_path}")
    print(f"human_report={markdown_path}")
    print(markdown_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
