# Independent traffic simulation and additional video truth

[Русский](physical_validation.ru.md) · 2026-10-20

**The production estimator remains v7. This is a validation correction, not an
accuracy fix or a release acceptance.**

The previous custom simulator is retained for reproducibility. Its geometry uses
shared centerlines for opposing movements, the stopping coordinate lies inside
the schematic junction, and a position clamp can reset speed instantaneously.
Changing its random seed also changes controller splits. Its historical scores
are therefore software stress-test results, not evidence of realistic road
accuracy. They must not be used alone to select a production candidate.

An independent optional [SUMO](https://eclipse.dev/sumo/docs/Simulation/Safety.html)
generator now provides separate lanes, car following, junction geometry and
native controller output. It checks collisions, teleports, acceleration,
same-lane bumper gaps, conflicting greens, red entries, signal-output coverage
and exported approaches. Lamp truth stays outside the vehicle JSON; the
application discovers topology and K from a separate training recording.

Five 900-second controls were scored after 180 seconds of warmup, ending at
890 seconds. UNKNOWN and absent predicted heads count as incorrect:

| Case | Correct / head-seconds | Overall | Mean color recall |
|---|---:|---:|---:|
| Four approaches, K2 | 2558 / 2840 | 90.07% | 58.66% |
| K2, one green extended 12s | 2534 / 2840 | 89.23% | 57.36% |
| K2, persistent period +15% | 2496 / 2840 | 87.89% | 51.76% |
| Four approaches, K3 | 2569 / 2840 | 90.46% | 60.12% |
| Three approaches, K3 | 1933 / 2130 | 90.75% | 61.92% |

All five scored fixtures passed the implemented physics checks. Automatic
discovery found the intended K and approach count in their training inputs.
Yellow recall was zero in four of the five cases. These controls are now
revealed; subsequent tuning needs new reserved seeds. Passing these checks is
not proof of realistic demand, detector noise or every possible road movement.
This generator does not yet cover additional arrows, permissive turns, blocked
queues or emergency vehicles.

The first T-network export omitted N/S because SUMO normalized its coordinates.
That export was rejected, preserved and corrected before T-model fitting.
Integration tests now cover both network shapes. See
[counts, physics checks and hashes](independent_simulation.json).

## Additional original-video review

Five new image-appearance brackets were sealed from native, un-interpolated
frames, each 0.067–0.100 seconds wide:

- Sverdlovsky N main: GREEN and RED near video PTS 5418s and 5469s.
- Enthusiasts E main: YELLOW, RED and GREEN near PTS 670s, 673s and 709s.

A fifth independently reviewed moving car at 90 minutes supports the existing
Sverdlovsky vehicle/clock mapping without refitting. With the February 11–19
offline model and February 27 causal packets, the new GREEN onset is **3.416s
late** and RED **1.349s late**, measured to the conditional clock envelope.
These are two transitions, not an all-color accuracy percentage.

Enthusiasts remains video-only: its JSON/video clock association is unaccepted.
The middle display makes a precise RED_YELLOW onset ambiguous; it is not labelled
by assuming a duration. Strong sun also leaves the new Sverdlovsky yellow
boundary unaccepted. Native-frame precision does not calibrate exposure timing,
LED aliasing, identity or geometric uncertainty.
[Sealed brackets, hashes and replay](video_truth_extension.json).

## Reproduction

Use a separate development environment for optional `eclipse-sumo==1.28.0`.
`--sumo-home` is the installed `sumo` directory containing `bin/`; SUMO is not a
runtime dependency of the web application. Every output directory must be new.

```sh
python -m scripts.sumo_validation --sumo-home /path/to/sumo --output .web_runtime/train --seed 101
python -m scripts.intersection_project .web_runtime/train/vehicles.json --output .web_runtime/model
python -m scripts.sumo_validation --sumo-home /path/to/sumo --output .web_runtime/control --seed 102
python -m scripts.score_sumo_validation --model .web_runtime/model/model.json --case .web_runtime/control --output .web_runtime/control/evaluation.json
```

Set `TRAFFIC_TEST_SUMO_HOME` to run both native integration tests:
`python -m pytest tests/test_sumo_validation.py -q`.

Release remains blocked on real transition delays, yellow/RED_YELLOW behavior,
joint variable-duration handling and the Enthusiasts clock link. No new
all-six-archive lamp accuracy or theoretical optimum is claimed.
