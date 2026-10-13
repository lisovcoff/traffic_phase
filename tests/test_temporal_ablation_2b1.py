import copy
from pathlib import Path

import pytest

from scripts.temporal_ablation_2b1 import (
    drop_sparse, substitute_movement, candidate_upper_hook, deny_annotation_reads, save,
)


def event(movement, ts):
    return {"movement": movement, "timestamp_ms": ts, "event_type": "RELEASE", "provenance": {"id": ts}}


def test_b_only_removes_single_sparse_release_without_mutation():
    a = [event("E->W", 1), event("S->N", 2), event("N->S", 3)]
    original = copy.deepcopy(a)
    b, removed = drop_sparse(a)
    assert a == original
    assert b == [a[0], a[2]] and removed == [a[1]]
    assert all(e in a for e in b)


def test_d_only_replaces_ew_timestamps_without_mutating_other_streams():
    a = [event("E->W", 1), event("S->N", 2), event("N->S", 3)]
    replacement = [event("E->W", 5), event("E->W", 6)]
    d = substitute_movement(a, replacement)
    assert [e for e in d if e["movement"] != "E->W"] == a[1:]
    assert [e for e in d if e["movement"] == "E->W"] == replacement
    assert a[0]["timestamp_ms"] == 1


def test_c_only_changes_candidate_upper_argument():
    ds = [{"millis": 1, "zone": "N"}, {"millis": 4, "zone": "S"}, {"millis": 9, "zone": "S"}]
    seen = []
    def solver(points, entry, upper):
        seen.append((points, entry, upper))
        return "candidate"
    calls = []
    hook = candidate_upper_hook(solver, "S", lambda z: z, 42, calls)
    assert hook(ds, 1, 9) == "candidate"
    assert seen == [(ds, 1, 4)]
    assert seen[0][0] is ds
    assert calls == [{"track_id": 42, "from_upper_ms": 9, "to_upper_ms": 4, "changed": True}]
    assert ds[-1]["millis"] == 9


def test_c_actual_hook_falls_back_to_end_without_outgoing_observation():
    ds = [{"millis": 1, "zone": "N"}, {"millis": 9, "zone": None}]
    calls = []
    hook = candidate_upper_hook(lambda points, entry, upper: (points, entry, upper),
                                "S", lambda z: z, 43, calls)
    assert hook(ds, 1, 9) == (ds, 1, 9)
    assert calls[0]["changed"] is False


def test_annotation_read_guard_rejects_truth_before_fit(tmp_path):
    annotation = tmp_path / "source.json_manual_marks.json"
    annotation.write_text("{}", encoding="utf-8")
    with deny_annotation_reads():
        with pytest.raises(AssertionError, match="annotation access"):
            annotation.read_text(encoding="utf-8")


def test_manifest_cannot_be_replaced_or_reprepared(tmp_path, monkeypatch):
    import scripts.temporal_ablation_2b1 as module
    monkeypatch.setattr(module, "OUT", tmp_path)
    save("manifest.json", {"variants": ["A", "B", "C", "D"]})
    before = (tmp_path / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        save("manifest.json", {"variants": ["X"]})
    assert (tmp_path / "manifest.json").read_bytes() == before


def test_evaluator_cannot_read_labels_without_prediction_seal(tmp_path, monkeypatch):
    import scripts.temporal_ablation_2b1 as module
    monkeypatch.setattr(module, "OUT", tmp_path)
    with deny_annotation_reads():
        with pytest.raises(FileNotFoundError):
            module.evaluate()  # Fails checking seal before touching annotation.
