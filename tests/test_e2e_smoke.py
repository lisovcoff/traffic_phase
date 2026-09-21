from __future__ import annotations

from scripts.e2e_smoke import run_smoke


def test_end_to_end_batch_to_realtime_smoke():
    result = run_smoke()

    assert result["batch_status"] == "ok"
    assert result["phase_count"] == 2
    assert result["realtime_status"] == "SYNCHRONIZED"
    assert result["phase_id"] in {1, 2}
    assert result["phase_offset_s"] is not None
