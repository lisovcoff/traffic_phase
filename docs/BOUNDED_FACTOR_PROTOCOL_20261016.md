# Bounded-history exact inference: protocol before implementation/checks

Base `9cfec60b8b7f1d9cef9d442f2c838be953a11d8c`. Fixed supplied K2/K3/order,
same observation components and flat/soft duration priors,2s grid. No real replay,
new recovery suite, parameter search or production changes.

Close each vehicle factor on its last positive q cell. Retain the last W phase
labels and current observed run length. Prefixes may merge only when these agree;
all unfinished factors then see identical relevant past labels. W is complete
support span (last-first+1), including holes, not number of nonzero entries.
No positive q is dropped, including tiny mass. Default W<=3 cells, explicit
hard maximum5; wider input gives unavailable, not approximation.

Use survival hazards to marginalize unobserved duration tails. Until first
transition, hazard uses stationary residual distribution at observed run age;
afterward it uses full duration prior. Initial phase uniform. Initial flag is
equivalently run_age==j+1 at cell j; no transitioned path has that age.
Final cell has no outgoing transition. This parameterization gives one state
path per observed phase path; Viterbi does not maximize a hidden total duration.

Forward-count and backward messages give exact count/phase/boundary-existence
marginals. MAP retains one best prefix per sufficient state. No beam/pruning
except mathematically zero-weight paths. UNKNOWN published logical/physical.
No boundary publication threshold or oracle-conditioned interval rule.

Frozen limits: horizon<=80s, max span3(default)/5(hard),4096 states/layer,
100000 retained states,32MiB conservative retained-state allowance,5CPU+5wall
seconds checked between bounded steps. Resource failure has no partial posterior.

Checks before any output: exact factorization vs existing path_loglik for
small paths; oracle normalizer/count/phase/boundary/MAP on K2/K3 with2/3-cell
support, holes, crossing pairs, structural zeros, first/right censoring; equivalence
with cell-local DP; tiny off-cell mass not removed; limits/immutability/rename.
Technical64s example with bounded nonlocal kernels (no recovery truth); unknown
demand/observation remains UNKNOWN. Both priors reported, no best prior chosen.
Targeted tests<=30CPU seconds; no long-data fitting or phase labels.
