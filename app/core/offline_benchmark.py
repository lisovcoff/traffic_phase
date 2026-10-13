"""Annotation-only evaluation. No discovery imports or physical-label inference."""
from __future__ import annotations

import itertools
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def metric(value=None, *, n=0, interval=None, reason=None, **details):
    return {"value": value, "n_observations": n, "range_ms": interval,
            "reason": reason, **details}


def validate_annotation(payload: Any) -> dict:
    errors, warnings, marks = [], [], []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["root_not_object"], "warnings": [], "marks": []}
    start = payload.get("start_ms")
    if not finite_number(start) or start < 0 or start != int(start):
        errors.append("invalid_start_ms")
    source_marks = payload.get("marks")
    if not isinstance(source_marks, list):
        errors.append("marks_not_list")
        source_marks = []
    previous = None
    seen = set()
    for index, item in enumerate(source_marks):
        if not isinstance(item, dict):
            errors.append(f"mark_{index}:not_object")
            continue
        ts, kind = item.get("timestamp_ms"), item.get("kind")
        if not finite_number(ts) or ts < 0 or ts != int(ts):
            errors.append(f"mark_{index}:invalid_timestamp_ms")
            continue
        if not isinstance(kind, str) or not kind.strip():
            errors.append(f"mark_{index}:missing_kind")
            continue
        if ts in seen:
            errors.append(f"mark_{index}:duplicate_timestamp")
        if previous is not None and ts <= previous:
            errors.append(f"mark_{index}:timestamps_not_strictly_increasing")
        if finite_number(start) and ts < start:
            errors.append(f"mark_{index}:timestamp_before_start")
        if "offset_s" in item:
            offset = item["offset_s"]
            if (not finite_number(offset) or not finite_number(start)
                    or abs(ts - start - offset * 1000) > 0.01):
                errors.append(f"mark_{index}:offset_inconsistent")
        if "order" in item and item["order"] != index + 1:
            errors.append(f"mark_{index}:order_inconsistent")
        if "timestamp_local" in item:
            try:
                local = datetime.fromtimestamp(ts / 1000, timezone(timedelta(hours=5)))
                expected = local.strftime("%H:%M:%S.%f")[:12]
                if item["timestamp_local"] != expected:
                    errors.append(f"mark_{index}:local_time_not_UTCplus5")
            except (ValueError, OverflowError, OSError):
                errors.append(f"mark_{index}:timestamp_out_of_datetime_range")
        marks.append({"timestamp_ms": int(ts), "kind": kind})
        previous = ts
        seen.add(ts)
    if len(marks) < 2:
        errors.append("insufficient_marks_for_interval")
    if marks:
        if finite_number(start) and marks[0]["timestamp_ms"] > start:
            warnings.append("unknown_initial_phase_before_first_mark")
        warnings.append("missing_terminal_boundary_for_last_phase")
        if any(a["kind"] == b["kind"] for a, b in zip(marks, marks[1:])):
            warnings.append("consecutive_same_kind_not_phase_transition")
    labels = sorted({m["kind"] for m in marks})
    interval = [marks[0]["timestamp_ms"], marks[-1]["timestamp_ms"]] if len(marks) >= 2 else None
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "marks": marks, "labels": labels, "start_ms": start,
            "known_range_ms": interval, "complete_intervals": max(0, len(marks) - 1),
            "physical_lamp_truth_available": False,
            "phase_movement_mapping": None}


def percentile(values, fraction):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * fraction
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def match_boundaries(truth, predicted, tolerance_s):
    """Monotone one-to-one matching: max cardinality, then min absolute error."""
    if not finite_number(tolerance_s) or tolerance_s < 0:
        raise ValueError("tolerance_s must be finite and non-negative")
    truth, predicted = sorted(truth), sorted(predicted)
    scores = [[(0, 0.0) for _ in range(len(predicted) + 1)] for _ in range(len(truth) + 1)]
    actions = {}
    for i in range(1, len(truth) + 1):
        for j in range(1, len(predicted) + 1):
            options = [(scores[i - 1][j], "truth"), (scores[i][j - 1], "pred")]
            error = abs(truth[i - 1] - predicted[j - 1]) / 1000
            if error <= tolerance_s:
                count, cost = scores[i - 1][j - 1]
                options.append(((count + 1, cost - error), "match"))
            scores[i][j], actions[i, j] = max(options, key=lambda item: item[0])
    pairs, i, j = [], len(truth), len(predicted)
    while i and j:
        action = actions[i, j]
        if action == "match":
            pairs.append({"truth_ms": truth[i - 1], "predicted_ms": predicted[j - 1],
                          "signed_error_s": (predicted[j - 1] - truth[i - 1]) / 1000})
            i, j = i - 1, j - 1
        elif action == "truth":
            i -= 1
        else:
            j -= 1
    return list(reversed(pairs))


def segments_absolute(prediction, field):
    schedule = prediction.get("schedule", {})
    base = prediction.get("schedule_base_timestamp_ms", prediction.get("analysis_base_timestamp_ms"))
    if not finite_number(base):
        return [], "missing_schedule_time_anchor"
    raw = schedule.get(field)
    if not isinstance(raw, list) or not raw:
        return [], "missing_history"
    rows = []
    for row in raw:
        if (not isinstance(row, (list, tuple)) or len(row) != 3
                or not all(finite_number(v) for v in row)
                or row[1] <= row[0] or row[2] < 0 or row[2] != int(row[2])):
            return [], "invalid_history_segment"
        a, b, label = row
        a, b = base + a * 1000, base + b * 1000
        if rows and a < rows[-1][1] - 0.001:
            return [], "overlapping_or_unsorted_history"
        rows.append((a, b, int(label)))
    return rows, None


def state_at(segments, t):
    # No wraparound or extrapolation; gaps and outside support remain UNKNOWN.
    return next((label for a, b, label in segments if a <= t < b), None)


def evaluate_history(prediction, annotation, field, tolerance_s, grid_ms=1000):
    marks = annotation["marks"]
    interval = annotation["known_range_ms"]
    start, end = interval
    rows, error = segments_absolute(prediction, field)
    truth_rows = [(a["timestamp_ms"], b["timestamp_ms"], a["kind"])
                  for a, b in zip(marks, marks[1:])]
    # Only interior transitions have both adjacent truth intervals fully known.
    truth = [marks[i]["timestamp_ms"] for i in range(1, len(marks) - 1)
             if marks[i - 1]["kind"] != marks[i]["kind"]]
    predicted = [b[0] for a, b in zip(rows, rows[1:])
                 if abs(a[1] - b[0]) <= 0.001 and a[2] != b[2] and start < b[0] < end]
    matched = match_boundaries(truth, predicted, tolerance_s)
    errors = [abs(m["signed_error_s"]) for m in matched]
    common = {"truth_boundaries": len(truth), "predicted_boundaries": len(predicted),
              "matched_boundaries": len(matched), "tolerance_s": tolerance_s,
              "matching": "untyped_absolute_one_to_one_no_offset_fit"}
    unavailable = error or ("no_matches_within_tolerance" if not matched else None)
    boundary = {
        "mae_s": metric(statistics.mean(errors) if errors else None, n=len(errors),
                        interval=interval, reason=unavailable, **common),
        "p95_s": metric(percentile(errors, .95) if errors else None, n=len(errors),
                        interval=interval, reason=unavailable, **common),
        "precision": metric(len(matched) / len(predicted) if predicted and not error else None,
                            n=len(predicted), interval=interval,
                            reason=error or (None if predicted else "no_predicted_boundaries"), **common),
        "recall": metric(len(matched) / len(truth) if truth and not error else None,
                         n=len(truth), interval=interval,
                         reason=error or (None if truth else "no_interior_truth_transitions"), **common),
        "matches": matched,
        "missed_truth_ms": [t for t in truth if t not in {m["truth_ms"] for m in matched}],
        "extra_predicted_ms": [t for t in predicted if t not in {m["predicted_ms"] for m in matched}],
    }
    nearest = [min(abs(t - p) / 1000 for p in predicted) for t in truth] if predicted else []
    boundary["nearest_truth_boundary_mae_s_diagnostic"] = metric(
        statistics.mean(nearest) if nearest else None, n=len(nearest), interval=interval,
        reason=error or (None if nearest else "no_boundary_pairs"),
        interpretation="unbounded_nearest_prediction; may_reuse_prediction; not_one_to_one")
    covered_ms = sum(max(0, min(end, b) - max(start, a)) for a, b, _ in rows)
    coverage = metric(covered_ms / (end - start) if not error else None,
                      n=len(truth_rows), interval=interval, reason=error,
                      covered_duration_s=covered_ms / 1000,
                      truth_duration_s=(end - start) / 1000,
                      interpretation="temporal_support_not_correctness_or_lamp_observability")
    ticks = range(math.ceil(start / grid_ms) * grid_ms, end, grid_ms)
    pairs = [(state_at(rows, t), state_at(truth_rows, t)) for t in ticks]
    known = [(p, q) for p, q in pairs if p is not None]
    pred_labels = sorted({p for p, _ in known})
    truth_labels = annotation["labels"]
    agreement_reason = error or ("unequal_phase_cardinality" if len(pred_labels) != len(truth_labels)
                                 else "no_covered_grid_points" if not known else None)
    best, mapping = None, None
    if not agreement_reason:
        for perm in itertools.permutations(truth_labels):
            candidate = dict(zip(pred_labels, perm))
            score = sum(candidate[p] == q for p, q in known) / len(known)
            if best is None or score > best:
                best, mapping = score, candidate
    agreement = metric(best, n=len(known), interval=interval, reason=agreement_reason,
                       total_grid_points=len(pairs), grid_ms=grid_ms,
                       diagnostic_mapping=mapping,
                       interpretation="test_permutation_invariant_phase_agreement_only_NOT_physical_lamp_accuracy")
    return {"history_field": field, "status": "unavailable" if error else "ok",
            "reason": error, "coverage": coverage, "boundaries": boundary,
            "phase_agreement_diagnostic": agreement}


def evaluate_prediction(prediction, annotation, *, tolerance_s=2.0):
    if not annotation["valid"]:
        return {"status": "invalid_annotation", "reason": annotation["errors"]}
    interval = annotation["known_range_ms"]
    marks = annotation["marks"]
    labels = annotation["labels"]
    schedule = prediction.get("schedule", {})
    k = schedule.get("phase_count")
    count = metric(k == len(labels) if finite_number(k) else None, n=1,
                   interval=interval, reason=None if finite_number(k) else "missing_predicted_phase_count",
                   predicted=k, annotation_distinct_labels=len(labels),
                   interpretation="observed_phase_labels; not_proof_of_full_controller_K")
    # Consecutive returns to the same label: provisional recurrence period,
    # not a controller period in skip/hold regimes. No modulo/offset fitting.
    returns = []
    previous = {}
    for mark in marks:
        label, ts = mark["kind"], mark["timestamp_ms"]
        if label in previous:
            returns.append((ts - previous[label]) / 1000)
        previous[label] = ts
    truth_period = statistics.median(returns) if returns else None
    period = schedule.get("period_s")
    valid_period = finite_number(period) and period > 0
    error = abs(period - truth_period) if valid_period and truth_period is not None else None
    reason = "missing_predicted_period" if not valid_period else "insufficient_same_label_returns" if not returns else None
    period_metric = metric(error, n=len(returns), interval=interval, reason=reason,
                           predicted_s=period, truth_recurrence_median_s=truth_period,
                           recurrence_intervals_s=returns,
                           relative_error_percent=100 * error / truth_period if error is not None else None,
                           interpretation="median_same_label_recurrence; skip_hold_can_change_recurrence")
    plan = prediction.get("physical_signal_plan", {})
    return {"status": "ok", "phase_count_match": count, "period_absolute_error_s": period_metric,
            "histories": {field: evaluate_history(prediction, annotation, field, tolerance_s)
                          for field in ("raw_hsmm_segments", "baseline_segments")},
            "physical_plan_phase_count": metric(len(plan.get("phases", [])) if plan.get("enabled") else None,
                                                n=1, interval=interval,
                                                reason=None if plan.get("enabled") else "physical_plan_disabled_or_missing"),
            "physical_lamp_accuracy": metric(n=0, interval=interval,
                                              reason="no_independent_per_lamp_truth_or_fixed_semantic_mapping")}
