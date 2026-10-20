# Project status — 2026-10-20

The application is a **research prototype**, not an accepted universal physical
signal estimator. Python inference and one offline/online panel are implemented.
The default is v7; no inference change accompanies the repository cleanup.

## Delivered

- Whole-intersection JSON/ZIP ingestion, separated sources/sessions, recurring
  regime catalogue, automatic observed topology/configuration hypotheses.
- Saved model to causal per-second online packets, bounded vehicle histories,
  SQLite journal, idempotence, restoration and common car/signal player.
- Six-archive processing and synthetic/video-scoped evaluation. Exact scope,
  denominators and provenance are in [results](../results/README.md).
- English-default/Russian README, architecture/API guide, generated reports and
  research outputs excluded from the current Git tree while retained locally.

## Accuracy and remaining work

95% across the six archives is not established. No complete independent lamp
history is available for every head/second of any archive. Theoretical maximum
accuracy on those inputs is unknown. Empty demand, unseen obstructions and
permissive turns can leave physical colors/sections unidentifiable.

Production reaches 86.50% on 12 synthetic streams (77,280 head-seconds). A narrow
conditional N GREEN/YELLOW video window gives 147/153, but its counterfactual
+12s copy gives 147/165. Neither is full-intersection accuracy.

Joint color/duration, local-age learning and detector-onset correction are
implemented, measured and **default-off**. Learned 10s history reaches 92.79%
on four controls fresh at freeze, but real colors and some instantaneous cases
regress. Sensor-delay correction retains added green but regresses synthetic K2.

Next algorithm work: causal period/duration adaptation using multiple completed
cycles, distinguishing isolated extension from persistent timing change. Prior
naive median updates were rejected for yellow regression. Freeze candidates and
new controls, retain ordinary-yellow/K2/K3/blocked-queue checks, then integrate
only if acceptance passes. Video remains evaluation-only.

Enthusiasts crash is located around video 13:03:50 with a bus obstructing N;
visible E continues cycling. JSON/video clock link remains unaccepted, and the
invisible N cannot be labelled by reversing E. Four other archives lack paired
independent lamp truth. Hardware inference is a hypothesis, not certification.

Historical 2D.1 stays FAIL/default-off. Local research files and rejected attempts
are retained. Old full reports remain in revision `9924a35` and ignored local
folders; latest public summaries do not require those folders to run tests.
