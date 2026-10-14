# 2D.1: observation model and conditional boundary brackets

Base: `3ce49ae6ac998049443884413968db9e153efa09`. Diagnostic only.
Production/default and the old recovery gate remain unchanged; 2D.1 is FAIL.
No decoding, fitting, real replay, parameter search or template modification.

## Generative versus fitted observation models

Sources: `scripts/sparse_event_suite_2d1.py::generate`,
`app/core/v9/primitives.py::build_occupancy_matrix`,
`app/core/v9/decoder.py::decode_cyclic_hsmm`, and
`scripts/sparse_observation_review_2d1.py::conditional_mark_emissions`.

The generator has structural zeros: given phase z, only Mz can arrive. Its
Poisson rate is 0.25 events/s (unequal-demand case: 0.35/0.12/0.25), with
independent exponential inter-arrivals, rounded to milliseconds. A generated
event is a synthetic phase-exclusive mark, not a real RELEASE or lamp reading.
No-demand/blockage events are removed; missing observation intervals are
explicitly supplied. Coverage is known by construction, not inferred from silence.

The frozen templates are 0.90 diagonal and 0.02 off-diagonal. They allow
off-phase events, unlike the generator. That can represent errors/permissive
movement in another model, but neither their rates nor that interpretation have
been calibrated here. Changing them now would change the already failed experiment.

Rate is not occupancy probability. For a fully covered 1s bin and rate 0.25,
P(N>0)=1-exp(-0.25)=0.2212, not 0.90. Unequal rates give approximately
0.2953/0.1131/0.2212. Boundary bins have partial phase exposure. The occupancy
builder sets x=1 whenever at least one event occurs: multiplicity and within-bin
timing are discarded. Two marks can occupy one boundary bin. Count Poisson
likelihood and Bernoulli occupancy likelihood are therefore different models.

Legacy emissions are sum[x log(p)+(1-x) log(1-p)]. Local history neutralizes
all-empty bins via its mask, but zeros for other movements in a nonempty bin
still contribute. Such terms describe absence under a specified exposure/demand
model; they do not observe a prohibiting signal. The diagnostic proposal uses
x@log(q), q=p/row_sum(p): no negative-zero terms, but binary occupied marks are
still not event counts. For K2 q_diag=0.97826; K3=0.95745, both nonexclusive.
It also retains the duration prior. Removing negative terms does not make this
the true generator likelihood or resolve event sparsity.

For real trajectories, observed intensity can involve exposure, demand, queue
release, permissive behavior and tracking errors. The unrestricted-demand
nonidentifiability witness establishes a limit under those unrestricted
assumptions, not impossibility of the project. Independently constrained demand,
geometry, sensor availability or calibrated mark distributions can add information.

## Reference semantics and sealing

`scripts/exclusive_mark_reference.py::reference` receives only events, known
synthetic mapping/order, supplied coverage and 1ms rounding resolution. It has
no truth, period, cycle-count, duration or decoder inputs. Adjacent observed
phase runs yield [last_previous-0.5ms, first_next+0.5ms]. These conservative
closed bounds account for timestamp rounding. They are single-boundary brackets
CONDITIONAL on no hidden transitions. They are not calibrated intervals or
lamp-switch intervals. Start/end boundaries are unavailable.

Order alone cannot rule out additional full silent cycles, even between equal
marks; all global outputs explicitly retain ambiguity. A skipped mark requires
multiple transitions, a coverage gap is ambiguous, and simultaneous unlike
marks cannot establish order. No single boundary is invented for these cases.
Same-mark runs cannot prove the absence of unobserved phases.

All 24 outputs were saved and SHA256-sealed before loading the suite truth.
Predictions are hash-checked against the existing seal. Evaluation uses ordinal
association only when the COMPLETE observed phase-run sequence equals the
candidate/truth sequence. This correspondence rule is fixed independently of
timestamps; it does not choose a closest boundary, permutation or offset by truth.
When sequences differ, correspondence remains ambiguous, even if some local
matches look plausible. Event compatibility is checked independently for every
candidate: at least one time in the rounded event cell must lie in a segment
with the exclusive event phase. Violations here concern only this ideal model.

## Results (24 saved cases, seeds 11 and 29)

| Quantity | Result |
|---|---:|
| Generated internal truth boundaries | 216 |
| Conditional single-transition brackets | 180 |
| Explicit gap-ambiguous edges | 2 |
| Brackets with unambiguous ordinal truth association | 166 |
| Truth inside these brackets | 166/166 |
| Width median / p95 (all 180 conditional brackets) | 5.592 / 17.08635 s |
| Width <=4s | 48/180 (26.67%) |
| Midpoint within +/-2s (separate diagnostic) | 110/166 (66.27%) |
| Unconditionally identified boundaries | 0 |

Four empty-event cases yield no brackets. Two observation-gap cases have
ambiguous full-sequence correspondence: 14 otherwise conditional brackets plus
2 gap edges are not truth-scored. The 166/166 denominator excludes these and
does not mean 100% temporal coverage or point recovery. Midpoint is not an
upper bound on achievable accuracy; a model with additional justified information
can do better or worse. These brackets impose no production publication policy.

| Saved candidate | Ordinal comparable boundaries | Inside / before / after bracket | Incompatible exclusive events |
|---|---:|---:|---:|
| Legacy | 152 | 151 / 0 / 1 | 2/1777 |
| Conditional-mark proposal | 159 | 156 / 1 / 2 | 10/1777 |

Legacy correspondence is ambiguous in both hold30_K2 cases, all empty cases and
both observation-gap cases. Proposal correspondence is ambiguous in hold30_K2
seed11, all empty cases and both gap cases. Event violations are reported even
when boundary correspondence is ambiguous; full per-case event indices,
boundary positions, time ranges and missing-result reasons are in metrics JSON.
They are not proof that real RELEASE events contradict real signals.
Specifically, legacy violates 2 event cells in hold30_K3 seed11; the proposal
violates 5 in hold30_K2 seed11, 2 in hold30_K2 seed29, 2 in hold30_K3 seed11,
and 1 in hold30_K3 seed29. The saved candidates were read, never recomputed.

## One proposed next experiment (not implemented or executed)

Test an event-time, interval-censored ordered-phase model on a NEW preregistered
synthetic suite. First scope: ideal exclusive marks, known observation exposure,
phase-specific stationary Poisson rates supplied by the generator, and an
independently declared duration prior. Use actual counts/timestamps, structural
zeros, and censor missing observation windows. Retain alternate silent-cycle
paths rather than choosing one by floating-point emission maxima. Separately
test misspecified rate/demand and permissive-mark cases, declared before running;
these must trigger a model-assumption warning, not an ideal-model accuracy claim.

Proposed criteria to freeze before implementation/results: zero exclusive-event
constraint violations on covered inputs; report conditional interval containment
and width median/p95/<=4s against independently generated truth, with all
ambiguous and unavailable boundaries in the denominators; report point +/-2s
precision/recall separately, retaining the original 0.8 recovery gate unchanged
where that gate applies. Never pass point recovery via interval containment.
For a deterministic feasible interval set, truth exclusion is a FAIL under its
assumptions. For posterior intervals, nominal coverage must instead be declared
and assessed over independently generated repetitions, with sampling uncertainty.
Report UNKNOWN fraction separately from input coverage. Declare two duration
priors in advance and report their resulting point/interval displacement as
prior dependence, without selecting the better prior against truth. No-demand
must not produce an evidence-identified point; gaps retain multiple feasible
paths. No physical lamp inference is authorized by synthetic success.

Trajectory-only data can establish event timestamps, sampling support, proxy
kinematics and model-conditioned logical sequences, and reveal sensitivity to
assumptions. External calibration is needed for independent RELEASE semantics,
units, stop-line geometry, signal relationship, sensor missingness and lamp
accuracy. This reference supplies an observation-model diagnostic, not a new
decoder or a reason to accept the failed old algorithm.

Artifacts: `evidence/stage2d1_interval_reference/`. Existing predictions are
referenced by hash, not repackaged. Six lightweight tests passed; pytest issued
only a cache-directory warning. No heavy run was performed.
