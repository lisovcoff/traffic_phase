# Project status — 2026-10-20

The application is a **research prototype**, not an accepted universal physical
signal estimator. Python inference and one offline/online panel are implemented.
The default is v7; no inference change accompanies the repository cleanup.

Delivery check: the saved seven-day Sverdlovsky model and 120 real February 27
packets pass HTTP player/journal/seek/validation checks; p95 request time is
0.478s. A cold independent process reconstructs the journal and continues it.
The [delivery guide](../DELIVERY.md) includes installation, replay conversion
and source-package verification. 75 targeted checks pass. The experimental
waiting detector now rejects a newly moving latest sample; K3 gains two correct
seconds, but the known real onset and period-change blockers remain. Functional
readiness is not physical-estimator acceptance. See [receipt](../results/delivery_readiness.json).

Latest [queue-front timing stage](../results/front_release_timing.md): front
release ages and continued waiting are now causal experimental observations.
Persistent-change GREEN recall equals v7 (1186/1238), and false GREEN decreases
from the earlier candidate's 122 to 94 head-seconds. Five of seven known SUMO
controls exceed 95%, and known visible-N interiors reach 148/153. Promotion
still FAILS: false GREEN remains above v7's 78, and a separate real GREEN onset
regresses by 1s against the previous candidate. 54 targeted tests pass; the
application remains on v7. These development results are not new holdouts or
six-archive all-head accuracy.

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
algorithm work is physical intergreen/age uncertainty during persistent timing
changes. GREEN recall has been restored on the known period-change control;
false GREEN and a separate onset regression remain. Retain K4 short colors,
then freeze new controls and integrate only if acceptance passes.
Video remains evaluation-only.

Enthusiasts crash is located around video 13:03:50 with a bus obstructing N;
visible E continues cycling. JSON/video clock link remains unaccepted, and the
invisible N cannot be labelled by reversing E. Four other archives lack paired
independent lamp truth. Hardware inference is a hypothesis, not certification.

Historical 2D.1 stays FAIL/default-off. Local research files and rejected attempts
are retained. Old full reports remain in revision `9924a35` and ignored local
folders; latest public summaries do not require those folders to run tests.
