# Exact scalable subset: cell-local vehicle factors

Base `08f82c3b382388fc201baa82a4ec37302ef8c4e4`.
Scope amendment frozen in CONTEXT_OBSERVATION_PROTOCOL before implementation/tests.
Module: `app.experimental.local_factor_sequence`; entry `infer_local_context`.

## Factorization and exactness

For every vehicle i, require q[i,j]>0 at exactly one cell j_i. No small-value
threshold. Then log integral_i = log(lambda[m_i,j_i]*exposure*dt*q[i,j_i]), so
the entire joint-track likelihood is sum_j emission[j,z_j]. Compensator already
factors by cell. Pairing marks stays inside q; there is still one term per
vehicle. Nonlocal kernels, even a second support value1e−100, return
NONLOCAL_TRACK_KERNEL_REQUIRES_EXPANDED_STATE; no independent-mark fallback.

Sum-product state=(phase,remaining duration,transition count). Initial remaining
duration has the same stationary grid residual prior as the exhaustive oracle.
Remaining>1 decrements; remaining1 switches cyclic phase and samples an unchanged
full duration prior. No transition is counted after the last observed cell.
Sum over all remaining durations at the right edge gives correct censoring.
Backward messages yield phase marginals and interior-boundary existence.

Diagnostic MAP uses a separate segment-level max recurrence with initial-residual
and final-duration **survival** terms. Viterbi over an individual remaining-duration
state would wrongly maximize an unobserved final duration rather than sum it.
This distinction is explicitly tested against oracle MAP scores. Structural-zero
emissions are supported without invalid infinity subtraction in segment sums.

Count messages require O(n²*K*R) array storage, with R=24 existing duration cells;
no full paths retained. Horizon remains<=80s under current observation contract.
Both flat/soft priors retained; no production prior chosen. Existing4..48s
duration support remains a separate limitation for longer holds.

## Output and checks

Outputs: diagnostic context MAP, count posterior, phase posterior and existence
probability for **every** interior grid boundary. No truth count/threshold chooses
which hypothesis to report. These are supplied-model probabilities, not calibrated
lamp probabilities or a validated publication rule. Logical/physical outputs stay
UNKNOWN; target metadata keeps context and target separate.

12 targeted tests pass; final combined context/regression/DP check152 passed.
On short2/8/12s cases, both priors agree with exhaustive
path calculations for normalizer, count, phase/boundary marginals and MAP score
(numerical tolerance1e−11, not changed ±2s evaluation tolerance). Also checked
factorization, nonlocal rejection, structural zeros, right censoring, resources,
context entry and immutable inputs. This is algorithm equivalence, not recovery
accuracy or a new synthetic benchmark.

Technical64s K3 zero-demand input completes without enumeration: log normalizer0,
count posterior normalized, sum of boundary existence equals expected count,
phase marginals1/3. Recorded DP self wall time~.046s and array allowance1966336
bytes. Neither is end-to-end throughput/peak RSS. No-demand leaves prior-driven
alternatives, not a reconstructed lamp. A short context example is also saved.

Budgets:5CPU+5wall seconds between bounded blocks;32MiB array allowance;
unavailable without partial posterior on failure. No beam/truncation claims.
General nonlocal factors need expanded history state or explicitly approximate
search; this code does not silently merge their prefixes into scalar scores.

## Remaining product work

Scalability blocker is removed for local factors only. No claim of arbitrary
real RELEASE support, hold+30 recovery or acceptance2D.1. Need bounded nonlocal
kernel inference and real observation-model calibration/validation; existing
K/discovery/physical mapping are unchanged. No real replay, tuning or new recovery
suite was run. Old FAIL and predictions remain. See context results for the
population-edge proof and its unverified real-delay assumptions.
