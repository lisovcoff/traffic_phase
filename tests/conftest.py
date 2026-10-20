"""Keep unit/API tests independent of private, locally retained research runs."""
from pathlib import Path

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "local_evidence: checks saved research runs, unavailable in a clean clone"
    )


def pytest_collection_modifyitems(config, items):
    if (Path(__file__).resolve().parents[1] / "evidence").is_dir():
        return
    unavailable = pytest.mark.skip(reason="Saved local research evidence is not distributed")
    for item in items:
        if item.get_closest_marker("local_evidence"):
            item.add_marker(unavailable)
