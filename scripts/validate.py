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
            intersection_id=str(item["intersection_id"]),
            kind=str(item.get("kind", "scenario")),
            description=str(item.get("description", "")),
        )
        for item in datasets
    ]


def select_datasets(
    datasets: list[ValidationDataset],
    names: list[str] | None,
    intersection_ids: list[str] | None = None,
) -> list[ValidationDataset]:
    """Select a cheap validation subset while preserving reference context."""
    scoped = datasets

    if intersection_ids:
        requested_intersections = set(intersection_ids)
        available_intersections = {
            dataset.intersection_id for dataset in datasets
        }
        unknown_intersections = sorted(
            requested_intersections - available_intersections
        )
        if unknown_intersections:
            raise ValueError(
                "unknown intersection id(s): "
                + ", ".join(unknown_intersections)
            )
        scoped = [
            dataset
            for dataset in datasets
            if dataset.intersection_id in requested_intersections
        ]

    if not names:
        return scoped

    requested_names = set(names)
    available_names = {dataset.name for dataset in scoped}
    unknown_names = sorted(requested_names - available_names)
    if unknown_names:
        raise ValueError(
            "unknown dataset name(s): " + ", ".join(unknown_names)
        )

    targets = [
        dataset for dataset in scoped if dataset.name in requested_names
    ]
    supporting_intersections = {
        dataset.intersection_id
        for dataset in targets
        if dataset.kind != "reference"
    }
    selected_names = {dataset.name for dataset in targets}

    for intersection_id in supporting_intersections:
        references = [
            dataset
            for dataset in scoped
            if dataset.kind == "reference"
            and dataset.intersection_id == intersection_id
        ]
        if not references:
            raise ValueError(
                "selected dataset has no matching reference for intersection: "
                + intersection_id
            )
        selected_names.update(dataset.name for dataset in references)

    return [
        dataset for dataset in scoped if dataset.name in selected_names
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
        "--dataset",
        action="append",
        dest="dataset_names",
        metavar="NAME",
        help=(
            "validate this manifest dataset; scenario selections also include "
            "their matching reference context"
        ),
    )
    parser.add_argument(
        "--intersection",
        action="append",
        dest="intersection_ids",
        metavar="ID",
        help=(
            "validate only this physical intersection; repeat to select "
            "several intersections"
        ),
    )
    parser.add_argument(
        "--transition-tolerance-seconds",
        type=float,
        default=3.0,
    )
    args = parser.parse_args()

    datasets = select_datasets(
        load_manifest(args.manifest),
        args.dataset_names,
        args.intersection_ids,
    )

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
