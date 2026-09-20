from __future__ import annotations

import json

import pytest

from app.core.validation import ValidationDataset
from scripts.validate import load_manifest, select_datasets


def _dataset(name, intersection_id, kind):
    return ValidationDataset(
        name=name,
        path=f"{name}.zip",
        intersection_id=intersection_id,
        kind=kind,
    )


def test_select_datasets_preserves_manifest_order_and_reference_context():
    datasets = [
        _dataset("reference_a", "A", "reference"),
        _dataset("accident_a", "A", "accident"),
        _dataset("reference_b", "B", "reference"),
        _dataset("closure_b", "B", "lane_closure"),
    ]

    selected = select_datasets(datasets, ["closure_b"])

    assert [dataset.name for dataset in selected] == [
        "reference_b",
        "closure_b",
    ]


def test_select_datasets_filters_one_intersection():
    datasets = [
        _dataset("reference_a", "A", "reference"),
        _dataset("accident_a", "A", "accident"),
        _dataset("reference_b", "B", "reference"),
        _dataset("closure_b", "B", "lane_closure"),
    ]

    selected = select_datasets(datasets, None, ["A"])

    assert [dataset.name for dataset in selected] == [
        "reference_a",
        "accident_a",
    ]


def test_select_datasets_rejects_unknown_name():
    datasets = [_dataset("reference", "A", "reference")]

    with pytest.raises(ValueError, match="unknown dataset name"):
        select_datasets(datasets, ["missing"])


def test_select_datasets_rejects_unknown_intersection():
    datasets = [_dataset("reference", "A", "reference")]

    with pytest.raises(ValueError, match="unknown intersection id"):
        select_datasets(datasets, None, ["missing"])


def test_load_manifest_requires_and_preserves_intersection_id(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "name": "reference",
                        "path": "ref.zip",
                        "intersection_id": "Ленина-Свердловский",
                        "kind": "reference",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    datasets = load_manifest(manifest)

    assert datasets[0].intersection_id == "Ленина-Свердловский"


def test_load_manifest_rejects_missing_intersection_id(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "name": "reference",
                        "path": "ref.zip",
                        "kind": "reference",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(KeyError, match="intersection_id"):
        load_manifest(manifest)
