# Isolated event-time prototype: preregistered design

Base `161dd0b5642ba312b1e930a4640c153b2bd799e5`.
Production/default and historical FAIL remain unchanged. All new inference is
under `scripts/`; production imports none of it. No real replay or fitting.

## Model and scope

We choose finite-grid **feasible sets**, not posterior intervals. Cyclic K2/K3,
exclusive mapping, initial phase/start at t=0, supplied integer observation
windows and positive phase-specific stationary rates are known synthetic inputs.
Each completed duration is an integer in [2,40]s. The final duration is right
censored. These are hard assumptions, not claims about real RELEASE.

The observation log density for a phase-z segment is
`N_z log(lambda_z) - lambda_z * observed_exposure`, with -infinity for any
incompatible exclusive mark. Event counts retain multiplicity; no occupancy or
Bernoulli templates are used. Missing windows contribute zero exposure and no
events. Silence in observed windows informs the likelihood ONLY under the
supplied positive-rate assumption; it does not prove RED or identify blockage.
For rounded observations whose whole rounding cells lie inside grid bins,
integrated Poisson cell likelihood differs from the implemented density only by
path-independent timestamp-cell and factorial constants. Counts are sufficient
because all possible boundaries are on that grid.

Timestamp resolution is 1ms, boundary resolution 1s. If a rounding cell straddles
ANY potential grid boundary, the case is explicitly unavailable instead of
silently assigning it a side. Continuous subsecond paths are not represented.
This numerical restriction is reported, not repaired after results.

A DAG state is (segment start time, number of completed transitions). All
reachable structurally compatible duration edges are retained, then pruned by
terminal reachability. It represents alternative cycle counts and correlated
boundary choices without enumerating full paths. Boundary sets are ordinal
projections of that DAG; their hulls summarize widths but can contain holes.
They must not be combined as independent Cartesian intervals. Complete means
complete ONLY within the declared discrete model. Resource exhaustion returns
unavailable, with no claim to complete alternatives.

Two duration priors share exactly the same hard support: discrete uniform and
normalized exp(-abs(d-10)/5), d=2..40. They are declared design hypotheses, not
estimated from test truth. The latter encodes a nominal 10s plan; the former is
broad. Intermediate edges use duration mass; final edges use survival P(D>=d).
Each produces its own likelihood-plus-prior diagnostic point; neither is chosen
as the winner. Feasible sets are prior-weight-independent because both priors
are positive on identical support. Prior effects on point estimates are reported.

UNKNOWN includes multiple possible phases, missing input windows and no-event
cases. A singleton feasible phase is conditional on the hard assumptions (which
can include known initial phase/minimum duration), not an observed lamp.
Published physical states and causes are always UNKNOWN. Diagnostic points may
still be computed with no events, explicitly rate/prior-driven, never identified.

## Frozen suite, criteria and budgets

Manifest: `evidence/stage2d1_event_time_prototype/manifest.json`. New seeds
101 and 307; 18 cases, 36 inference calls, one suite run. Stable K2/K3,
hold+10 K2, hold+20 K3, shortening-5 K3, changing-rate, permissive mark, supplied
gap, and no-demand. Independent generator outputs timestamps and separate truth.
Inference receives `inputs.json`, which contains no truth segments. Supplied
rates are 0.6/0.4/0.5 events/s. Misspecified cases retain the nominal supplied
rates/model to expose limitations; no universal detection claim is made.

Limits: 30s total inference-and-output CPU budget, 3s per call, horizon<=120s,
100000 edges and 5000 states per call. Conservative graph-object allowance is
16MB per sequential call; this is not an operating-system process RSS cap and
excludes Python/NumPy runtime and artifact buffers. Input corpus is small and
fixed. No new library/framework. If the suite budget is depleted, remaining
cases are unavailable without attempts to rerun. Tests use tiny independent
examples and do not tune against the declared suite.

Point: unchanged evaluator and +/-2s; matched/truth/predicted, precision/recall,
MAE/p95 and coverage reported separately. Original per-core-case >=0.8 recall
criterion remains unchanged, evaluated for both priors, not substituted by
interval containment. Old published-history gate is still FAIL; this prototype
does not publish accepted histories.

Feasible: every correctly specified truth path must exist in the DAG and all
its ordinal boundaries must be in their sets; exclusion is FAIL, unavailable
is unassessed. Report true-boundary denominators, unissued boundaries, optional
ordinal sets, ambiguous transition counts, median/p95 hull widths and <=4s.
All-sets and mandatory-sets widths are separate. Mispecified cases are explicitly
separate from the feasible-model gate. Report event constraints and UNKNOWN,
input coverage, prior point displacement, and limits even on failures.

Outputs and hashes are sealed before truth evaluation; adapters are separate
and hashed. The prior reference estimator and tests are included in the compact
evidence archive for provenance, without repeating historical predictions.
