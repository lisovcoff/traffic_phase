# Section support during phase ambiguity

[Русский](section_consensus.ru.md) · 2026-10-20

**Experimental candidate v2; production remains v7. Promotion still fails the
persistent-timing-change gate.** [Counts and provenance](section_consensus.json).
This follows the [joint timing stage](transition_timing.md).

## What changed

Four lost real-video GREEN seconds were caused by the output projection: two
logical phases disagreed about an arrow, so neither phase reached 0.5 support,
although the main GREEN marginal exceeded 0.998. The projection hid that main
section as UNKNOWN.

An unsupported section can now retain the state of the selected joint
configuration when its marginal reaches 0.65 and recent vehicle evidence exists.
The threshold is the existing v7 section-support threshold, not a fit to video.
Each arrow has its own marginal. A different marginal-winning state is never
substituted: emitted sections remain compatible with one joint configuration.
The posterior, duration learning and already-known colors are unchanged. This
fix improves UNKNOWN coverage; it does not correct the physical timing law.

## Real-data checks

| Known visible-N scope | Production v7 | Previous candidate | Candidate v2 |
|---|---:|---:|---:|
| Original GREEN/YELLOW interiors | 147/153 | 143/153 | 147/153 |
| Smooth +12s time-warped copy | 148/165 | 147/165 | 154/165 |
| Added-green portion of that copy | 3/12 | 6/12 | 7/12 |

All variants receive the same chronological vehicle packets, starting at video
PTS1980 for warmup. Only the evaluator receives the labels and conditional clock
mapping. The copy is a counterfactual, not an observed emergency. RED and
RED_YELLOW are not labelled in these denominator intervals. Candidate v2 has
141/144 GREEN and 6/9 YELLOW, compared with v7's 142/144 and 5/9: equal totals
do not mean identical errors or improved GREEN recall.

The separate 90-minute window retains the earlier onset result: GREEN is
1.416s late versus v7's 3.416s, and RED is 1.349s late for both. Distances are
to the conditional vehicle-clock envelope, not a calibrated hardware clock.
These are known development windows, not newly reserved video tests.

## Independent simulator regression

The seven previously generated SUMO controls were replayed after freezing the
fix. All fixtures pass the native collision, lane-gap, acceleration, red-entry,
conflicting-green and approach-export checks. They are controlled straight-route
scenarios, not replicas of the real intersections. Offline models were fitted
on different trajectories; K and the phase catalogue remain fixed online.
UNKNOWN counts as incorrect; all main colors and exported heads are scored.

| Scenario | V7 correct/total | Candidate v2 | False GREEN seconds: v7 → v2 |
|---|---:|---:|---:|
| K2 ordinary | 2556/2840 | 2668/2840 | 140 → 84 |
| K2 +12s extension | 2532/2840 | 2588/2840 | 134 → 104 |
| K2 persistent new period | 2518/2840 | 2544/2840 | 78 → 122 |
| K2 downstream obstruction | 2556/2840 | 2666/2840 | 146 → 90 |
| K3 ordinary | 2557/2840 | 2675/2840 | 96 → 83 |
| Three approaches | 1938/2130 | 2022/2130 | 88 → 51 |
| K4 ordinary | 2560/2840 | 2668/2840 | 140 → 88 |

The JSON also includes three older K2 controls and an ablation of only this
projection change. Filled UNKNOWN sections can still be wrong; they are counted
as errors. False GREEN here includes GREEN issued during RED, YELLOW or
RED_YELLOW, and counts head-seconds rather than independent episodes.

**Remaining blocker:** under the persistent change, GREEN recall is 1172/1238
versus v7's 1186/1238, and false GREEN increases. This is an underlying timing
error, not solved by recovering UNKNOWN. The known real aggregate regression
is repaired, but product promotion is still rejected. New reserved acceptance
controls are deferred until these development failures are fixed. No universal
95% or numeric theoretical maximum is established.

## Verification and reproduction

45 targeted tests passed, including positive/negative main and arrow support,
joint-configuration consistency, identical latent updates with the projection
disabled, causal packets, clock translation, duration adaptation and native SUMO
integration. One existing Starlette/httpx deprecation warning remains.

Use `scripts.score_sumo_validation --estimator adaptive` and
`scripts.compare_transition_timing --estimator adaptive` as described in the
[previous stage](transition_timing.md#reproduction-and-verification). Model,
input, truth, code and receipt hashes are recorded in the JSON. Full diagnostic
replays and earlier evidence remain local; original archives are unchanged.

Next work: separate GREEN survival from predicted transition onset when the
period changes, retain the K4 short-color gain, and measure GREEN recall and
false GREEN before freezing new acceptance controls or integrating the candidate.
