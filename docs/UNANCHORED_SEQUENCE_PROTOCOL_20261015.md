# Unknown start/count — protocol before implementation/run

Base: `2a039c8173396c60e70ee5ea863186bc0fe00292`.
Scope: opt-in finite-grid sequence inference, fixed supplied K2/K3, rate-row
mapping and cyclic order. Reuse rounded vehicle observation components and
joint track likelihood. No K search, real replay, changed extraction or defaults.

## Fully specified start/duration model

Both existing priors `flat` and `soft` from joint_track_model retained side by
side, not selected by results. Durations4..48s every2s; same distribution in all
phases. Observation starts at a uniformly sampled **grid instant** in a stationary
cyclic renewal process. Initial phase uniform over K. Initial age is marginalized:
P(first residual=r)=P(D>=r)/E[D/2] for r=2,4,...48s. This is a supplied start
assumption, not measured stationarity or exact continuous-time equilibrium.
First residual may be2s although a complete duration is at least4s.
Subsequent complete durations use original prior; final segment right-censored.
No switch is inserted at0 or horizon. Initial physical start remains unknown.

Enumerate all interior transition sequences allowed by prior support, including
zero/multiple/hidden cycles, and all initial phases. No supplied observed count.
Half-open segments; transition exactly at horizon is censored. Report posterior
over count/initial phase, conditional boundary distributions by count, every path
alternative, and diagnostic MAP. Do not mix ordinal intervals across counts.
Posterior is exact only over declared grid/model when search complete; resource
exhaustion returns unavailable, no posterior from truncated alternatives.
Logical published history and physical sections remain UNKNOWN: prototype not
calibrated/accepted; point path diagnostic only. Zero likelihood range is a
numeric prior-dependence diagnostic, not observability threshold.

## Frozen checks and resource limits

Default maximum horizon80s;10000 total paths,32MiB conservative allowance,
5 CPU seconds plus5 wall seconds per invocation,512 events, existing observation integration budget.
Wall deadline protects sub-tick limits on Windows, whose process CPU counter
is coarse. Deadlines checked between bounded work blocks, not OS hard preemption.
No changing these after recovery results. Tests use short horizons<=16s,
plus a long-horizon exhaustion check with tiny path budget.

Before tests: normalization prior over all paths for horizons2/4/8/12s, correct
left/right censoring, zero transitions, multiple full cycles, unknown initial
phase, nontrivial supplied order, both priors/no-demand, gaps, structural-zero
constraints through underlying observation tests, rename/immutability, path/time/
memory exhaustion, no truth/file access in inference. Compact fixed witness:
K2 path phase1@[0,2),phase0@[2,6),phase1@[6,10),phase0@[10,14),phase1@[14,16);
supplied strong but nonexclusive rates2/.01, observed release counts per2s cell
[4,4,4,4,4,4,4,4], timestamps cell_start+[.113,.457,1.021,1.789].
K3 order[2,0,1], phase2@[0,2),phase0@[2,6),phase1@[6,10),phase2@[10,14),
phase0@[14,16). Generation truth independent and never passed to inference.
These deterministic informative engineering witnesses are not Poisson population
accuracy tests. For each prior require diagnostic path equals supplied witness;
if not, retain FAIL without tuning. Count/phase uncertainty is still reported.
No-demand/all-camera-missing must have posterior=prior, UNKNOWN published states.
Point tolerance unchanged ±2s; witness exact recovery checked separately, not
a replacement of old recovery gate FAIL. Total targeted checks <30 CPU seconds.
