# Observation checks, frozen 18.10.2026

Equal-duration candidate produced identical3-file strict scores and K; removing
coherence worsened17 from15/17 to1/17. Both results are preserved. No parameter
adjustment or seed retry of those variants. User's explicit implementation
authorization remains active. This new round addresses two different mechanisms.

Candidate4 `positive_onsets`: in periodic boundary evidence, take positive part
of each stream's smoothed signed derivative before averaging. Keep derivative
standard-deviation scaling and final normalization, all likelihoods, event
selection, durations, seeds and quality coefficient0.05 unchanged.
Hypothesis: averaging signed complementary fronts cancels genuine boundaries.

Candidate5 `silent_censoring`: rows with zero permission events in every stream
are unobserved rather than Bernoulli negative observations. Apply the same mask
to template fitting, pointwise likelihood, decoder emissions and effective
observation count in path-quality normalization and approximate BIC. Preserve
original timeline indices, durations and all real timestamps; do not compress
time. Original onset evidence and original event selection retained. This is
a conditional observation model, not a claim that silence proves any signal.
No fitted empty-bin weight, fixed time shift or new geometry.

Separate runs, not a combination, on original three verified lossless caches.
dt1,seed0,K2..6,one worker/file,90s/file,270s/candidate,540s total. All source and
worker hashes frozen first. Seal predictions before labels/scoring. No tuning
after results. Stop further model candidates after this round; preserve default
unless one complete variant has no per-file strict-match/K regression or false
extra increase and a measurable improvement. Keep raw/resolved and reaction
scores separate; existing evaluators and denominators unchanged. No independent
holdout claim. Full regression and release verification follow any promotion.
