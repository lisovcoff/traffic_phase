# Stage 2 — Logical Signal-Group Discovery

## Scope

Stage 2 infers **logical signal groups** from movement-level trajectory evidence produced by Stage 1. It does not claim to recover the physical number or hardware arrangement of signal heads.

Terminology:
- **Movement**: one approach-to-destination movement such as N->E.
- **Logical signal group (SG)**: a controller timing/output group whose movements share the same effective signal interval.
- **Signal head**: a physical signal housing. Physical redundancy is not identifiable from trajectories alone.
- **Additional / arrow head**: a physical/UI hypothesis derived only after a logical signal-group hypothesis exists and only with sufficient topological evidence.

## Hard structural constraints

1. Signal-group discovery is performed **independently per approach**. Movements from different approaches are never merged into one logical signal group merely because their green intervals coincide.
2. The discovered cycle from Stage 1 is treated as fixed input for Stage 2.
3. A movement may have a strict subset of another movement's effective active interval. This is evidence for a protected sub-stage, but is not by itself proof of a physical arrow.
4. A movement may be active during both a protected interval and a broader permissive interval. The model must represent inclusion/overlap rather than force a single interval equivalence.
5. Sparse/no-demand movements must produce an ambiguity/insufficient-evidence result instead of a fabricated group.
6. Physical heads that display the same logical signal group remain unidentifiable from trajectory kinematics alone.

## Mathematical model

For approach a, let M_a be its movements and C the Stage-1 cycle.

Each movement is represented by phase-folded departure/release evidence on the circular domain [0, C).

For each candidate logical group g, estimate a circular active interval I_g = [start_g, end_g).

For each movement m, evaluate its relationship to candidate intervals:
- equivalent: approximately the same interval;
- contained: I_m is a stable subset of I_g;
- contains: I_g is a stable subset of I_m;
- partial-overlap;
- disjoint;
- insufficient evidence.

The optimization should be a constrained, regularized model-selection problem, not unconstrained clustering:

objective = negative evidence likelihood + complexity penalty + domain penalties

The complexity term discourages creating a separate logical group for every movement. A split is accepted only when its improvement in evidence exceeds the model-complexity cost.

## Evidence

Primary evidence:
- RELEASE timestamps;
- CROSSING timestamps when available;
- repeatability across cycles;
- temporal stability of boundaries;
- event support.

STOP is not direct proof of RED and is not sufficient to establish a signal group.

Crossing/departure observations are censored by demand and by vehicle reaction/queue discharge. Therefore the first observed departure is not the literal green onset.

## Protected/permissive distinction

A turn movement with a strict recurring high-support sub-interval may be a protected movement, but trajectory data alone cannot establish the exact lamp semantics (solid green arrow, flashing yellow arrow, etc.).

Permissive turns can appear during gaps in opposing traffic. A short, sparse turn interval must therefore not automatically become an arrow group.

The implementation should keep the logical relationship as an evidence-backed hypothesis and expose ambiguity when the protected/permissive distinction is not identifiable.

## Confidence

At minimum expose:
- support;
- cycle-to-cycle repeatability;
- boundary stability;
- assignment ambiguity/entropy;
- final confidence;
- explicit insufficient-evidence reason.

Confidence must not be derived solely from traffic volume. A high-volume movement with unstable phase timing is not a high-confidence signal-group candidate.

## Planned module boundaries

The implementation should remain small and composable:
- app/core/signal_group_signature.py — phase-fold movement evidence, circular density/histogram representation, interval extraction;
- app/core/signal_group_discovery.py — approach-local candidate construction, equivalence/inclusion relations, constrained regularized model selection;
- app/core/signal_group_mapping.py — map logical groups to the existing SignalHead domain only when the mapping is supported by topology and evidence.

Diagnostics should report hypotheses and identifiability limits rather than silently turning hypotheses into physical facts.

Do not introduce HMM/HSMM at Stage 2. Stage 1 already provides the recurring cycle and phase segmentation; Stage 2 is a circular interval model-selection problem.

## Required validation cases

Before Stage 2 is considered complete, tests must cover:
1. two identical movements on one approach -> one logical group;
2. two clearly separated movement intervals -> two groups;
3. strict turn subset of a through interval -> inclusion hypothesis;
4. sparse turn demand -> ambiguous/insufficient evidence;
5. permissive gap-acceptance-like sparse turn events -> no automatic arrow;
6. coincident stages on different approaches -> groups remain separate;
7. synchronized physical-head ambiguity -> logical group only;
8. cyclic intervals crossing phase zero;
9. variable/actuated duration -> no artificial group split solely from duration variation;
10. one movement with no observed demand -> no hallucinated signal group.

## Acceptance principle

Stage 2 is successful when it can produce a conservative, reproducible logical signal-group model from trajectory evidence and explicitly distinguish:
- directly supported logical timing structure;
- structural hypotheses such as additional/arrow sections;
- physically unidentifiable hardware details.

The Stage-1 Lenina regression must remain green throughout the implementation.
