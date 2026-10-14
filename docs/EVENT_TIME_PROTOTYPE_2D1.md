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

## Sealed single-run results

Pre-run code/config commit: `f30203bfe49e543ea3e367d570e1688ec4729ca9`.
Exactly 36 inference calls completed in 2.625 process CPU seconds including
output serialization. Maximum single-call CPU: 0.171875s; maximum reachable
states: 852; maximum examined edges: 15956. No timeout, truncation, numerical
rounding rejection, tuning, repeat or real run. 16/18 cases per prior have
complete feasible graphs; both permissive cases return NO_FEASIBLE_PATH.
There are 18 generated cases, not 36 independent data samples.

| Population / prior | Matched / truth / predicted | Precision | Recall | Matched MAE / p95 |
|---|---:|---:|---:|---:|
| All 18, uniform | 44 / 90 / 61 | .7213 | .4889 | .5909 / 2 s |
| All 18, nominal10 | 61 / 90 / 63 | .9683 | .6778 | .2951 / 2 s |
| 12 correctly specified, uniform | 40 / 60 / 52 | .7692 | .6667 | .6000 / 2 s |
| 12 correctly specified, nominal10 | 50 / 60 / 52 | .9615 | .8333 | .3200 / 2 s |
| 10 core, uniform | 36 / 50 / 48 | .7500 | .7200 | .6111 / 2 s |
| 10 core, nominal10 | 46 / 50 / 48 | .9583 | .9200 | .3478 / 2 s |

Aggregate recall does NOT pass the unchanged per-case recovery gate. Uniform
fails 4/10 core cases; nominal10 fails 1/10 (stable_K2 seed307, recall .6).
Both remain FAIL. The other uniform failures are stable_K3 seed101,
hold10_K2 seed101 and shorten5_K3 seed101. No prior was selected/promoted.
The unchanged evaluator also emits its existing permutation diagnostic; it is
not used for any gate or interpreted as lamp accuracy.

The feasible graphs contain all 12 correctly specified generation paths,
including the supplied gaps; containment is 60/60 internal truth boundaries,
with no unissued truth boundaries in that population. This verifies finite-model
consistency, not narrow reconstruction. For these cases there are 276 issued
ordinal sets, of which 224 are optional (do not exist in every feasible path).
Hull width median/p95 is 26/52s; 31/276 (11.23%) are <=4s. The 52 mandatory
sets have median/p95 26/51.45s and 0/52 <=4s. Every one of the 12 cases has
ambiguous transition count. A short optional high-ordinal set does not identify
a real transition. Full finite sets and their correlated DAG are retained.

Across all 18 cases, 80/90 truth boundaries are contained, 10/90 are unissued
(permissive cases), and no issued truth boundary is excluded. These mixed-model
figures do not validate misspecified inputs. There are 388 issued sets, 327
optional; median/p95 hull width 26/52s, 39/388 (10.05%) <=4s. All 16 complete
cases have ambiguous transition counts. Both priors have identical feasible
sets, as required by their identical hard support.

No event-constraint violations occur among 259 assessed events per prior;
36 events in the two unavailable permissive cases are unassessed, not silently
counted as zero violations. Changing-rate cases remain feasible and are not
recognized as rate misspecification. No-demand also remains feasible under the
positive-rate model: a very unlikely empty record is possible. Its cause is
unknown and UNKNOWN fraction is 1; diagnostic points there depend on the
supplied rates/prior and are not published observations.

Prior changes the diagnostic path in 15 of 16 complete cases. For comparable
ordinal points the largest displacement is 10s; both no-demand cases change
transition count, so no forced ordinal displacement is reported. The broad
feasible alternatives are unchanged; this explicitly separates point prior
dependence from hard observation compatibility. Positive count rates affect
scores, but do not eliminate any structurally compatible path merely because
it is unlikely. Narrowing by a score cutoff would change feasible-set semantics
and was not done.

Across all cases UNKNOWN is 833/1130 seconds (73.72%) under either prior;
supplied input coverage is 1090/1130s (96.46%); diagnostic candidate coverage
is 1010/1130s (89.38%). For the correctly specified subset those values are
494/770s UNKNOWN (64.16%), 730/770s supplied exposure, 770/770s diagnostic
candidate coverage. Points in missing windows can exist as prior-driven
diagnostics while interpretation stays UNKNOWN; there is no production history
publication. UNKNOWN therefore must not be replaced by point temporal coverage.

16 pre-run contract/reference tests and 4 post-run seal/artifact checks passed.
All sources, parameters, inputs, 36 outputs and evaluation adapters are hashed.
Production files, unchanged evaluator, and historical evidence remain identical
to base. Physical lamps and causes remain UNKNOWN throughout. The next design
decision would need an independently justified way to constrain silent cycles
or a separately specified probabilistic uncertainty model; this run does not
authorize such an extension or real-data acceptance.
