# Count phase rewrite: frozen design, 18.10.2026

User explicitly requests a new implementation and self-checks on real archives.
Base1657598; main/old implementation/data/results remain intact. New phase core
does not call V9 em_fit, Bernoulli templates or its decoder. Reuse source parsing,
vehicle evidence, source/session scope and demand-based period estimation.

One supported event per source/track/movement (own RELEASE else eligible crossing),
with movement AND observation kind as distinct feature channels. No manual phase
names, counts, timings or fixed time shift in inference. Count-valued observations,
conditional multinomial likelihood, no negative vote from no observed vehicles.
Global circular change-point DP selectsK1..6 via declared BIC,100folded bins,
minimum3s phase, maximum90%cycle forK>1. Positive results are estimates, not
observed lamps. Local event-count cyclic dynamic programming retains full time,
uses learned duration targets with sigma=max(3s,.2target), min3s and broad
maximum target+max(10s,.5target); first/last durations censored. No selector or
seed/decoder code borrowed from V9 fitting. Empty bins never compress time.

One frozen run on each of three complete existing event caches,120s/file,
360s total. Seal all outputs before unchanged absolute +/-2s evaluation plus
separate operator[mark-3s,mark] compatibility. No post-result tuning or per-file
choice of best model. Compare automaticK and raw/resolved histories separately.
Familiar development data are not an independent holdout.

Raw archive integration: two preselected180MB archives, Sverdlovsky27.02.25 and
Enthusiasts05.10.24. For multi-member archives select lexicographically first
trajectory JSON and first observation session, document exact scope, no claim
that unprocessed members were analysed. Bound120s/file; preserve timeouts.
No independent lamp truth for these archives; integration cannot prove accuracy.

No global-default switch unless no per-file raw strict match/K regression and
no false-extra increase, with at least one improvement plus meaningful tests.
If not met, retain explicit experimental mode and full negative evidence.
No promise of theoretical ideality or universal millisecond accuracy.
