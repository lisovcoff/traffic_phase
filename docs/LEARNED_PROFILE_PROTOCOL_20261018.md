# Calibrated learned traffic profile, frozen 18.10.2026

User authorizes a fresh algorithm and self-verification. Automatic count models
did not beat baseline; preserve their results/default-off. This separate mode
learns from available operator marks, explicitly not automatic K discovery.

For each of3 original annotated JSON: cut=(first_mark+last_mark)/2. Only marks
at or before cut enter training. First mark is left-censored and excluded from
onset estimation. Test annotations remain out of training and prediction.
Evaluate marks after cut with same first/last censoring and unchanged metrics;
compare baseline on exactly that held-out interval. Do not report full34 as
held-out. Same-session temporal holdout, not an independent site/day/lamp test.

Unlabelled period estimation may use the complete offline recording (same
demand estimator); explicitly transductive offline, not a causal-online claim.
Learn periodic100-bin observation densities per movement+event type using
training-window vehicle events. One vehicle contributes unit total event mass,
split across its supported restart/eligible crossing. Smooth circularly2bins,
Dirichlet0.5, no label-tuned parameters. Training marks supply K and circular
phase-onset means. Predict using only model+vehicle events+numeric window:
100-state forward cyclic Viterbi, step0..ceil(100/period)+2 bins/s,
Gaussian step penalty sd0.5bins/s; unknown initial phase, no test timestamps
supplied as switches. Empty seconds no emissions; no time compression.

One frozen fit/prediction per source,120s/file,360s total. Seal models/predictions
before evaluation. No retries/seed/parameter tuning after outcomes. Model
estimates operator-calibrated phase time, not independent observed lamp time;
operator reaction0..3s remains uncertainty, never a claimed physical accuracy.
Do not replace automatic/default discovery with this conditional mode.
