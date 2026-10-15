# Context and censored query — scope before checks

Base `08f82c3b382388fc201baa82a4ec37302ef8c4e4`. Opt-in only; default remains
strict complete-query validation. No new decoder/prior/recovery suite or real replay.

Implement explicit query-selection kernel for rounded marks: query acts on clock
centres, not true detection times. Consecutive retained centres define the union
of rounding cells. Intersect that union with supplied camera windows; use it for
BOTH joint pattern probabilities and detected-vehicle compensator. This is exact
under supplied rounding/delay/detection assumptions, not inferred camera exposure.
Reuse existing piecewise integration, not a second likelihood implementation.

For finite nonnegative vehicle delay atoms, let Dmax be the largest enabled
release/crossing shift. A context query is safe from vehicles outside latent
[0,h) if every retained true mark lies in [Dmax,h). Choose reported clock centres
whose entire rounding cells lie inside that interval. This may censor additional
sub-ms edges; report them explicitly. With t>=Dmax and shift<=Dmax, u=t-shift>=0;
with t<h and shift>=0, u<h. No claim for unknown/unbounded real event delays.

Build one query from an existing immutable evidence index, keep global vehicle
identities/provenance. Supply desired target strictly inside a declared context;
no phase state or camera coverage is inferred from silence. Output identifies
context, queried marks, desired target and excluded edges. Context phase history
is still needed; standalone target-only phase inference is NOT equivalent.
No independent multiplication of overlapping window likelihoods.

Predeclared checks: closed-form2s query exposure including rounding edge;
paired RELEASE inside/CROSSING outside query is censoring, not missing detection;
normalization of all retained joint patterns to detected exposure; legacy strict
mode remains rejection; shifted absolute clock; pre-context vehicle witness;
zero camera/no demand; rename/immutability; invalid/unbounded delays, empty safe
range, unsupported backend, budgets. Existing finite-population tests preserved.
No tuning; tests<=30CPU seconds; up to512 events, horizon<=80s,64 delay pairs,
32 windows, existing2M integration-piece budget. Scientific inference calls0.
Physical/logical outputs remain UNKNOWN.2D.1 FAIL unchanged.

## Subsequent bounded scaling check, frozen before its implementation/tests

Add exact semi-Markov inference ONLY if every vehicle q factor has positive
support in exactly one latent cell. Then log-likelihood factors by cell; no
approximation/thresholding q. Nonlocal factor => unavailable, no scalar-HSMM
fallback. Same flat/soft priors, same stationary grid residual, fixed K2/K3/order.
Count forward messages and phase/boundary marginals, diagnostic MAP computed
with censored segment probabilities (not Viterbi on a single remaining-duration
state, which would maximize rather than marginalize censored final durations).
Output all boundary existence hypotheses without truth/count selection; no new
publication/observability threshold. Logical/physical remain UNKNOWN.

Check both priors against exhaustive path posterior on short8/12s finite cases:
normalizer, count, phase marginals, boundary existence and MAP score. No recovery
truth used. Long64s/no-demand is a normalization/scaling check, not accuracy;
never enumerate its millions of paths. Explicit memory/time refusal; numerical
budget<=32MiB,5CPU/5wall seconds; horizon<=80s remains. No beam/truncation here.
No scientific suite, no real replay. Extra targeted tests<=30CPU seconds.
