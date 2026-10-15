# Sparse stochastic duration validation — before any run

Base `41563f5852ec2708a0db6a590d04888b256baae9`. No inference/likelihood/prior
code changes. One frozen suite; seeds7/23; fixed supplied K2/K3/order. Original
point gate2D.1 stays FAIL. These tests are conditional synthetic development.

For each K and seed: stable/hold+10/shortening. Horizon34s, initial age2s
(seed7)/6s(seed23), nominal complete duration10s. First residual8/4s;
next full duration10/20/6s respectively, then full10s durations to horizon.
K2 initial phase1/order[0,1];K3 initial phase2/order[2,0,1]. Duration10 is a
generation parameter, NOT chosen production prior. Both existing flat/soft priors
are used unchanged. Truth generated before inference; no boundary/count/anchor
passed. Phases live on2s grid; events have arbitrary rounded millisecond times.

Generate per-movement Poisson counts with intensity0.6/s in primary phase and
0.03/s otherwise, times uniform inside each latent2s cell, rounded nearest1ms
on explicit origin0. This is an ordinary marked nonexclusive Poisson model,
not exclusive movements or active column each second. Exposure1, detection1,
release delay0, no crossing marks. Parameters supplied to inference, not
estimated from test truth; no real RELEASE interpretation implied.

Additional cases: K2/seed7 unequal supplied demand[.25,1.5]; zero demand;
camera gap[10,18); hold+30 with horizon64s (full duration40s), same limits.
Total16 inference calls maximum. Long hold may exceed full-enumeration budget;
retain unavailable, do not increase budget or rerun. No search/tuning/retries.

Per call: existing10000 paths,5CPU+5wall seconds,32MiB allowance. Suite60CPU/90wall
seconds; if exhausted, remaining cases recorded unrun with reason. Tests first,
freeze code/config before suite. Inputs/outputs seals before truth evaluation.

Point evaluation: unchanged match_boundaries±2s; matched/truth/predicted,
precision/recall, matched MAE/p95. Per informative core case/prior gate recall>=.8,
plus separate exact point count/initial phase diagnostics; unavailable counts
as FAIL for recovery, not silently excluded. Compare all rows; choose no prior.
No-demand/gap cases do not get an unsupported accuracy claim. UNKNOWN100% for
published states, diagnostic temporal extent reported separately.

Intervals: equal-tailed90% ordinal boundary posterior CONDITIONAL on true count
only in evaluator, after output seal. Report posterior mass on that count;
conditional containment/width cannot hide wrong-count MAP. Also report mass of
all boundary hypotheses within±2s, and count/initial phase posterior uncertainty.
Do not pool ordinal intervals across counts, call them lamp intervals or claim
nominal calibration. Absent count/numeric-zero conditional → unissued with reason.
No new real replay, K search, extraction/mapping/default changes or large archives.
