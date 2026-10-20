# Queue-front release and waiting likelihood

[Русский](front_release_timing.ru.md) · 2026-10-20

**Experimental/default-off. Production remains v7; promotion is not accepted.**
[Counts, alternatives and hashes](front_release_timing.json).
This continues the [section-support stage](section_consensus.md).

## Diagnosis and implementation

A known SUMO period-change replay showed a GREEN age near 15s shortly after the
actual new GREEN began. Movement evidence selected the right phase but did not
resynchronize its age. Separately, the intergreen posterior favored short
intervals: the earlier development receipt assigned about 85% to 3–4s. These
are inferred timing hypotheses, not measured clearance durations.

Two causal experimental estimators were added:

- `FrontReleaseTimingIntersection` checks geographic positions for a continuous
  stationary run at the offline-learned queue front, then a newly confirmed
  restart. Upstream cars, stale/gapped positions, ambiguous phase assignments
  and detected obstructions do not supply age anchors. Correlated releases in
  one phase/packet are deduplicated. The update changes only conditional GREEN
  age, preserving phase/regime mass, topology, K and previously issued results.
- `FrontWaitingTimingIntersection` also uses continued, position-supported
  front waiting. A conditional survival ratio accounts for successive waiting
  observations without repeatedly applying the whole survival probability.
  Missing vehicles are not RED evidence; detected obstruction suppresses this
  channel. Actual observed waiting refreshes evidence time.

The shared reaction hypothesis is an **uncalibrated** uniform 0–4s interval plus
20% unchanged-age contamination. It is not a Russian signal-timing standard or
a measured driver delay. Waiting contamination also accounts for the existing
obstruction hypothesis. Videos, manual labels, absolute phase clocks and future
destinations never enter either estimator. Physical age remains uncertain.

## Seven known SUMO development controls

All fixtures retain their native physics PASS checks. They have stochastic
arrivals, separate lanes and straight routes; they are not complete replicas
of real intersections. Models use different offline training trajectories.
All exported main heads/colors are scored over [180,890) seconds, and UNKNOWN
counts as incorrect. These are previously revealed controls, not fresh holdouts.

| Scenario | V7 correct/total | Earlier adaptive v2 | Release + waiting | Accuracy | False GREEN: v7 → new |
|---|---:|---:|---:|---:|---:|
| K2 ordinary | 2556/2840 | 2668 | 2712 | 95.49% | 140 → 58 |
| K2 +12s extension | 2532/2840 | 2588 | 2680 | 94.37% | 134 → 70 |
| K2 persistent new period | 2518/2840 | 2544 | 2594 | 91.34% | 78 → 94 |
| K2 downstream obstruction | 2556/2840 | 2666 | 2708 | 95.35% | 146 → 66 |
| K3 ordinary | 2557/2840 | 2675 | 2703 | 95.18% | 96 → 65 |
| Three approaches | 1938/2130 | 2022 | 2042 | 95.87% | 88 → 42 |
| K4 ordinary | 2560/2840 | 2668 | 2709 | 95.39% | 140 → 73 |

Persistent-change GREEN recall recovers from the earlier candidate's 1172/1238
to **1186/1238**, equalling v7. False GREEN falls from 122 to **94** head-seconds,
but remains above v7's 78. K4 RED_YELLOW improves to 37/56 from the earlier
candidate's 29/56 and v7's 28/56. Three-approach RED_YELLOW remains 25/42 versus
v7's 26/42. False GREEN includes GREEN during RED, YELLOW or RED_YELLOW; these
are head-seconds, not independent episodes.

Release-only and configuration-MAP ablations are retained in the JSON. Switching
to configuration MAP loses short colors (K4 RED_YELLOW 1/56) and is rejected.
A 2s reaction-bound sensitivity check trades GREEN recall for a higher aggregate
period-change score, and is also not selected. No threshold was chosen by
claiming these development controls were new validation.

## Known real-video checks

The existing offline model and frozen conditional clock are retained. Only
visible N GREEN/YELLOW interiors are labelled in the first window:

| Scope | V7 | Earlier adaptive v2 | Release + waiting |
|---|---:|---:|---:|
| Original labelled interiors | 147/153 | 147/153 | 148/153 |
| Smooth +12s time-warped copy | 148/165 | 154/165 | 154/165 |
| Added-green portion | 3/12 | 7/12 | 7/12 |

Warmup starts at video PTS1980. The original new-candidate score comprises
141/144 GREEN and 7/9 YELLOW; v7 has 142/144 and 5/9. The copied stream is a
counterfactual, not an observed emergency. RED/RED_YELLOW are outside these
denominators; this is not full-intersection accuracy.

**A separate real onset regresses:** in the known 90-minute window, GREEN is
2.416s late versus the earlier candidate's 1.416s and v7's 3.416s. RED remains
1.349s late. Distances use the conditional vehicle-clock envelope, not a
calibrated hardware clock. The combined real/synthetic improvements do not erase
this regression or establish 95% on six archives.

## Verification and remaining gate

54 targeted tests pass, including native SUMO integration, geographic front
checks, obstruction handling, conserved phase mass, bounded waiting evidence,
no-demand behavior, rejected future packets and immutable issued results.
The earlier 4s waiting implementation and the final evidence-refresh correction
have identical scored counts on these seven controls; source snapshots and
separate receipts remain local.

The evaluation CLIs accept `--estimator front_release` or `front_waiting`;
`scripts.score_sumo_validation` still defaults to v7. Use new output paths and
offline models with queue references, as in the [previous reproduction guide](transition_timing.md#reproduction-and-verification).

Promotion remains FAIL for excess false GREEN under persistent timing change,
the real onset regression and remaining short-color losses. New reserved
acceptance controls and application integration are deferred. Next work must
address physical intergreen/age uncertainty and the onset/false-GREEN tradeoff,
not optimize only the aggregate score. Enthusiasts clock association and complete
six-archive lamp truth are still unresolved. All original archives and earlier
evidence are retained.
