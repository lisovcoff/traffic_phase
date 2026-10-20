# Joint timing and causal duration adaptation

[Русский](transition_timing.ru.md) · 2026-10-20

**The new estimator is experimental. Its promotion gate failed; the application
continues to use v7.** [Counts, hashes and receipts](transition_timing.json).

The stage implements joint hypotheses for green, yellow, red, red+yellow and
intergreen duration, using the same state posterior for colors and timing.
It adds unimpeded leading-vehicle braking, a stopping-target check against an
offline learned queue front, and adaptation from repeated completed front-release
intervals. K, movements and hardware hypotheses remain fixed from offline data.
No video, lamp label or evaluation clock is supplied to inference.

Three semantic problems were examined:

- V7 forecasts yellow in the last three seconds of a logical phase; that phase
  can also include other transition intervals.
- A motion onset and the later time at which enough samples confirm it differ.
  Bounded replay of already observed onsets is implemented and tested; it did not
  independently improve the first SUMO control.
- Offline logical-phase-age histograms are not calibrated physical GREEN-age
  kernels. Reusing them in the explicit physical-state model shifted short
  transitions. The final experimental estimator does not equate those clocks.

Timing constants remain uncalibrated priors. The intergreen hypotheses span
3–10 seconds, with 3s yellow and 2s red+yellow; this is a tested model family,
not a claim about every real controller. An additional long-duration branch
preserves the possibility of isolated extensions.

## Frozen initial candidate: new SUMO controls

Seven 900s scenarios were generated after candidate freeze using four reserved
arrival seeds. The four K2 variants share a seed and are correlated. All passed
the implemented physics checks. Scoring covers seconds 180–889; UNKNOWN and
missing heads are incorrect. These data are now revealed development controls.

| Scenario | V7 | Initial joint candidate |
|---|---:|---:|
| Four approaches, K2 | 90.00% | 95.28% |
| K2, isolated +12s green | 89.15% | 92.75% |
| K2, persistent period +15% | 88.66% | 88.66% |
| K2, stopped downstream vehicle | 90.00% | 94.23% |
| Four approaches, K3 | 90.04% | 93.49% |
| Three approaches, K3 | 90.99% | 95.92% |
| Four approaches, K4 | 90.14% | 91.94% |

These aggregate improvements did **not** justify promotion: on persistent timing
change, false GREEN rose from 78 to 120 head-seconds; K4 red+yellow recall fell
from 28/56 to 0/56. The downstream-stop scenario is a controlled stalled car,
not a reconstruction of the Enthusiasts crash. Its signal program remains
unchanged. The network has no additional arrows or permissive turns.

## Final experimental candidate: development checks

The final `AdaptiveRobustTimingIntersection` adds robust completed-interval
adaptation, retains the production 15% long-duration prior, requires a braking
trajectory to target the queue front, and separates the two age clocks.
The following cases were already revealed when this candidate was frozen:

| Scenario | V7 correct / total | Final candidate correct / total |
|---|---:|---:|
| K2 normal | 2558 / 2840 | 2654 / 2840 |
| K2 isolated extension | 2534 / 2840 | 2582 / 2840 |
| K2 persistent period change | 2496 / 2840 | 2510 / 2840 |
| K2 downstream stop | 2556 / 2840 | 2666 / 2840 |
| K4 normal | 2560 / 2840 | 2665 / 2840 |

K4 red+yellow recovered to **29/56**, versus v7's 28/56. On the normal K2 stream,
the learned ordinary intervals remain `[50, 50]` seconds. An isolated extension
also leaves them `[50, 50]`. Persistent timing change is learned as
`[57.8, 57.2]`, totaling **115 seconds**, using only completed vehicle-release
intervals. The offline phase catalogue and previous issued outputs are retained.
Detection delay and residual transition errors still reduce overall accuracy.

## Real video checks

The same earlier February 11–19 model is used with February 27 vehicle packets.
Queue references come from an earlier offline recording. Both estimators receive
the same packets and warmup; video clocks and labels are evaluator-only.

| Known development scope | V7 | Final experimental candidate |
|---|---:|---:|
| Visible N GREEN/YELLOW interiors | 147 / 153 | 143 / 153 |
| Time-warped +12s copy, same color scope | 148 / 165 | 147 / 165 |
| Added-green part of that copy | 3 / 12 | 6 / 12 |
| New N GREEN onset, 90min video | 3.416s late | 1.416s late |
| New N RED onset, 90min video | 1.349s late | 1.349s late |

The first two rows use warmup beginning at video PTS1980; this is why the paired
extension baseline differs by one second from older full-prefix receipts.
Onset errors are distances to the conditional vehicle-clock envelope, not
absolute hardware-clock guarantees. These scopes must not be pooled.

**Promotion remains FAIL:** the known original video loses four correct seconds,
the warped copy loses one, and GREEN recall under persistent timing change is
still lower than baseline. Neither the initial 95% cases nor the faster new
onset prove universal accuracy. Enthusiasts clock association and full-six-archive
physical-lamp accuracy remain unresolved.

## Reproduction and verification

`scripts.score_sumo_validation` accepts `--estimator v7`, `leading_brake` or
`adaptive`; the default is v7. Candidate models need queue references learned
from **offline training JSON**, never from the scored recording. The automatic
training models, phase catalogue and input hashes were retained locally.

```sh
python -m scripts.score_sumo_validation --model offline_model_with_queue_references.json --case sumo_control --output new_result.json --estimator adaptive
python -m scripts.compare_transition_timing --model offline_model.json --candidate-model offline_model_with_queue_references.json --packets held_packets.jsonl --truth sealed_video_brackets.json --output new_video_run
```

Every output path must be new. Native images, full SUMO output, candidate-source
snapshots and issued predictions remain under the ignored local evidence path
recorded in the JSON receipt. No original archive or earlier evidence was removed.

**57 targeted checks passed**, including native SUMO integration, a downstream
stop, future-packet rejection, immutable issued outputs, normalized posteriors,
absolute-clock translation, isolated extensions and repeated interval changes.
This is not a repeat of the complete repository suite.

Next acceptance work is the observation-time likelihood linking motion
confirmation, logical phase ages and physical colors. It must retain the K4
transition gain and recover the lost real-video seconds before new reserved
controls and product integration.
