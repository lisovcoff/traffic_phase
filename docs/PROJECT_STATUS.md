# Project status — 2026-10-20

The application is a **research prototype**, not an accepted universal physical
signal estimator. Python inference and one offline/online panel are implemented.
The default is v7; no inference change accompanies the repository cleanup.

The subsequent [joint timing stage](../results/transition_timing.md) implements
intergreen/color hypotheses, leading braking and causal adaptation from repeated
completed intervals. The experimental model learns a 100s to 115s period change
and reduces a known real GREEN onset delay from 3.416s to 1.416s. Promotion
failed that stage because another known real window regressed from 147/153 to
143/153. The [section-support follow-up](../results/section_consensus.md) recovers
the four lost seconds by preserving a main color shared by ambiguous logical
phases. Results are now 147/153 on the original and 154/165 on its +12s copy.
Ten SUMO controls and 45 targeted tests passed their execution/physics checks;
algorithm promotion still FAILS: persistent timing change reduces GREEN recall
and increases false GREEN against v7. These changes remain disabled in the app.

The [physical-validation follow-up](../results/physical_validation.md) added
an independent SUMO generator with physics gates and five separate online
controls. V7 scores 87.89–90.75%, with zero yellow recall in four controls.
The legacy custom simulator has geometric/kinematic limitations and its earlier
scores must not serve alone as a realism or promotion gate.

Five new original-video brackets are sealed. An additional vehicle at 90min
supports the frozen Sverdlovsky clock mapping without refitting. A fresh
cross-day replay is 3.416s late on GREEN and 1.349s late on RED, relative to the
conditional clock envelope. Enthusiasts labels remain video-only pending clock
association. This follow-up does not change production inference.

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

Repeated-completed-interval duration adaptation is now implemented experimentally;
isolated extensions retain the ordinary duration. It has not passed product
acceptance. Lost known real-video seconds have been recovered; the remaining
algorithm work is the physical transition/survival likelihood during persistent
timing changes. Retain the K4 transition gain, restore GREEN recall and reduce
false GREEN, then freeze new controls and integrate only if acceptance passes.
Video remains evaluation-only.

Enthusiasts crash is located around video 13:03:50 with a bus obstructing N;
visible E continues cycling. JSON/video clock link remains unaccepted, and the
invisible N cannot be labelled by reversing E. Four other archives lack paired
independent lamp truth. Hardware inference is a hypothesis, not certification.

Historical 2D.1 stays FAIL/default-off. Local research files and rejected attempts
are retained. Old full reports remain in revision `9924a35` and ignored local
folders; latest public summaries do not require those folders to run tests.
