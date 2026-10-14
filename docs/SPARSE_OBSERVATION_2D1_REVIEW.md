# Rejected 2D.1: isolated sparse-event review

Base `714a0917bfe4f46ab5022e25e88cc4410a9539ea`. 2D.1 is **FAIL**, not accepted.
Previously confirmed real counts: supported0/34, diagnostic candidate7/34
(3/17,1/8,3/9), versus accepted raw19/34. These user-confirmed results are retained
as historical evidence; no new real decoding/evaluation was run in this review.

## Isolation and accepted default

`discover_records`/`discover_path` now default to experimental_local_history=False.
Only an explicit boolean True enables the rejected experimental decoder. Ordinary
discovery does not call it. Ordinary reconstructed queries select accepted raw
history even if a serialized experimental payload exists. Its physical states
remain UNKNOWN under the accepted2C contract.

Choose history_source='experimental' explicitly in prepare_logical_query,
build_signal_model or signal_state_at to inspect experimental history. V10's
core caller forwards the same selection. Unavailable/missing experimental
history and its gaps remain UNKNOWN, without raw fallback. A prepared query's
source cannot be silently changed. Producing experimental history and selecting
it are intentionally separate decisions. Existing experimental output is marked
FAIL_2D1_NOT_ACCEPTED; it is not an approved reconstruction.

## Predeclared sparse experiment

Declaration commit `2917b28` predates decoding; proposal seal `50a05e6` predates
results. Seeds11 and29,24 cases, four cycles, fixed30s phase durations and K2/K3.
The independent generator samples timestamps/movements with exponential waiting
times at rate.25/s. Cases cover stable, hold+10/+30, shortening−10, unequal demand
rates.35/.12/.25, no-demand/blockage and explicit observation gaps. It does not
emit dense active columns or insert boundary-probe events. The real unchanged
occupancy builder bins these timestamps. Truth is generated independently and
never passed to either decoder.

Exactly one synthetic review compares the rejected legacy candidate/support
with one declared conditional-mark candidate. K/templates/order/period, duration
prior strength2, bounds, transitions and budgets are fixed. No fitting, seed
search, confidence weighting or real-label tuning occurs. Publication is not
implemented for the new hypothesis until interval support and uncertainty are
validated; it stays unavailable/UNKNOWN rather than copying its candidate.

Predeclared recovery gate: every core case candidate recall≥.8 at ±2s. Publishing
also requires recall/coverage≥.8 and identifiability checks. The engineering
contract tests pass, but the actual scientific recovery gate **FAILS**. Seven of
16 core cases fail the candidate threshold. Aggregate core results:

| Output | Matched/truth/predicted | Recall | Temporal coverage meaning |
|---|---|---|---|
| Rejected legacy supported | 15/144/15 | .104 | sparse positive-bin mask; not observation exposure |
| Rejected legacy candidate | 122/144/148 | .847 | full diagnostic path; not approved support |
| Conditional-mark candidate | 118/144/142 | .819 | full diagnostic path; not approved support |
| Proposed published history | unavailable, empty | unavailable | 0 returned intervals,100% UNKNOWN; evaluator reports missing_history |

An aggregate passing.8 does not pass the per-case gate. Failed cases are
hold10_K2/seed11, both hold30_K2 seeds, shorten10_K2/seed11, hold10_K3/seed11,
and both hold30_K3 seeds. The new candidate is worse in aggregate than the old
candidate. Removing the mask does not repair the decoder. Dense tests remain
technical controls, not proof of sparse recovery. Every synthetic prediction and
separate evaluator adapter is preserved and hashed; comparison.json/compact CSV
include denominators, coverage, UNKNOWN and missing metric reasons.

## Observation likelihood and concrete blocker

The previous likelihood includes `(1-x_m) log(1-p_zm)` for other zero movements
even in a bin containing a vehicle. Masking only all-zero rows does not remove
that negative evidence. Under unknown demand a zero can mean no arrival, no
observation, obstruction or low detection exposure; it is not a lamp observation.
One unique floating-point emission maximum is not identifiability.

The single diagnostic hypothesis uses `x @ log(q).T`, where
q_zm=p_zm/sum_j(p_zj). Zero counts contribute no likelihood term. This treats
frozen occupancy templates as a proxy for a stationary conditional mark mix,
conditional on event count. A common unknown intensity multiplier cancels,
but unknown movement-specific demand/exposure does not. No probability of a
lamp or calibrated phase error interval is implied.

A concrete generative model would use marked counts with
lambda_m(t)=E_m(t) D_m(t) r_zm and an independently justified duration prior:
`sum_m [N_m log(lambda_m) - lambda_m*dt]` up to count constants. The zero-count
term is justified only when exposure is known and demand constrained. Missing
observation requires censoring/marginalization. No-demand/obstruction requires
latent arrival/service assumptions, not a RED assignment. Conditioning on marks
gives `E_m D_m r_zm / sum_j E_j D_j r_zj`; relative demand must still be constrained.

The unit-test witness uses two different boundaries,30s and40s, and strictly
positive demands D2=D1*r_z1/r_z2. Both yield exactly the same marked-Poisson
intensity. Thus vehicle data alone cannot distinguish those histories under
unrestricted unknown demand. Frozen Bernoulli occupancy templates supply neither
exposure nor demand ratios or a calibrated duration distribution. Sparse event
likelihood also changes the relative scale of the old uncalibrated duration
penalty. Its effect cannot be repaired by inventing a confidence weight after
the failed experiment.

**BLOCKED only for publishing a new local-history model**: it requires explicit
approved demand/exposure assumptions or independent inputs/calibration and a
sequence-level uncertainty/support method. For example, forward/backward
posterior or censored-boundary sets could express ambiguity under a specified
observation model; a Viterbi path/unique emission is insufficient. Choosing such
assumptions, recalibrating the duration prior or adding latent demand states goes
beyond this single sealed hypothesis and needs a separately agreed experiment.
No gap-fill thresholds, emission weights or prior parameters were tried next.

## Gate outcome and reproducibility

Real replay count is **0**, because both sparse readiness and publishing gates
did not pass. check_sparse_gate_2d1 returns exit1 deliberately. CI contract/dense
checks passed (60 isolation,87 preexperiment,53 postreview,8 boolean-safety checks;
selections overlap). Existing K solver, extraction/selection, period, mapping
objective, offsets, evaluator and historical artifacts are unchanged. Read-only
queries on the three saved models verify accepted2C default behavior and explicit
experimental abstention without decoding or phase annotation reads. No inference
or output correctness claim is made for recording6's incorrect fixed K3.

All seeds/config/source hashes, generated events/truth, candidate predictions,
unavailable published output, evaluation adapters, gate reasons and logs are in
evidence/stage2d1_sparse_review. No2D.2/online work is started. Accepted2C remains
the default while the local-history publication problem is open.
