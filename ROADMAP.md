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

Historical 2D.1 remains FAIL/default-off and is not implicitly restarted.
Generated evidence, rejected attempts and the former detailed roadmap remain
locally preserved; pre-cleanup evidence is also in Git revision `9924a35`.
The public repository contains compact measurements under `results/`.
