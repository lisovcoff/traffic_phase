# Delivery roadmap

Read [current status](docs/PROJECT_STATUS.md), [product goal](docs/PRODUCT_GOAL.md)
and [validation](results/README.md) before choosing model work.

1. **Implemented:** whole-intersection JSON/ZIP ingestion, session isolation,
   saved models, observed topology/phase hypotheses and one offline/online panel.
2. **Implemented:** bounded causal observations, fixed offline structure online,
   packet journal, playback and restart recovery. Default inference is v7.
3. **Open:** causal adaptation to persistent new periods/durations while separating
   one-off extensions; preserve ordinary yellow, K2/K3 and blocked-queue behavior.
4. **Open:** independent clock-supported physical-head validation. Six archives
   are available, but full lamp truth and a numeric theoretical ceiling are not.
5. **Open:** candidate promotion only after separated regression/holdout gates,
   then integration and operational acceptance. Universal 95% is not established.

Validation milestone (2026-10-20): independent SUMO generator, lane/physics
gates, five separately scored controls and five new native-video brackets.
The fresh real replay confirms a 3.416s GREEN delay. Old custom-simulator
fidelity limitations are documented; transition fixes must pass the new checks.
See [physical validation](results/physical_validation.md).

Algorithm milestone (2026-10-20): joint timing hypotheses and robust completed-
interval adaptation are implemented and measured, default-off. Learned timing
change: 100s to 115s. Known real GREEN delay: 3.416s to 1.416s. Promotion FAIL
in that stage because another real window lost four correct seconds.
See [joint timing stage](results/transition_timing.md).

Section-support follow-up (2026-10-20): the four lost real seconds were caused
by phase ambiguity hiding an agreed main GREEN. Section marginals recover them:
147/153 on the original window and 154/165 on its +12s copy. Ten SUMO controls
and 45 targeted tests were checked. Promotion still FAIL: persistent timing
change loses GREEN recall and increases false GREEN against v7. Next work is
the physical transition/survival likelihood under that change, followed by new
reserved controls only after development gates pass.
See [section-support stage](results/section_consensus.md).

Queue-front follow-up (2026-10-20): causal front-release age correction and
conditional waiting survival restore persistent-change GREEN recall to v7's
1186/1238 and reduce false GREEN from 122 to 94 head-seconds. Five of seven
known SUMO controls exceed 95%; the known visible-N interior score is 148/153.
Promotion still FAIL: v7 has 78 false GREEN seconds in the period-change case,
and one real GREEN onset is 1s later than the previous candidate. Default v7
is retained. Next gate is physical intergreen/age uncertainty and the
onset/false-GREEN tradeoff, before new reserved controls and app integration.
See [queue-front timing stage](results/front_release_timing.md).

Historical 2D.1 remains FAIL/default-off and is not implicitly restarted.
Generated evidence, rejected attempts and the former detailed roadmap remain
locally preserved; pre-cleanup evidence is also in Git revision `9924a35`.
The public repository contains compact measurements under `results/`.
