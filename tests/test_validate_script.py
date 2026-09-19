from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_validate_script_supports_direct_execution():
    script = Path(__file__).parents[1] / "scripts" / "validate.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Run the complete traffic-phase validation pipeline." in result.stdout
