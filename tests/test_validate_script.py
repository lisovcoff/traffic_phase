from __future__ import annotations

import pytest

from app.core.validation import ValidationDataset
from scripts.validate import select_datasets


def test_select_datasets_preserves_manifest_order():
    datasets = [
        ValidationDataset("reference", "reference.zip", "reference"),
        ValidationDataset("accident", "accident.zip", "accident"),
        ValidationDataset("closure", "closure.zip", "lane_closure"),
    ]

    selected = select_datasets(datasets, ["closure", "reference"])

    assert [dataset.name for dataset in selected] == ["reference", "closure"]


def test_select_datasets_rejects_unknown_name():
    datasets = [ValidationDataset("reference", "reference.zip", "reference")]

    with pytest.raises(ValueError, match="unknown dataset name"):
        select_datasets(datasets, ["missing"])
