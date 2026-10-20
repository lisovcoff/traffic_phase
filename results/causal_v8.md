# Integrated causal v8 - 2026-10-20

V8 is integrated into the research application for models with queue geometry.
It improves aggregate accuracy but **does not pass strict physical acceptance**.
The implementation is usable; universal 95% and a theoretical ceiling are not proven.
The earlier no-regression gate remains FAIL; integration does not turn it into PASS.

## Changes

- Learn bounded queue geometry automatically from the uploaded offline trajectories.
- Keep up to 16 competing joint color/age/duration hypotheses; one unusual completed
  interval proposes a new program without discarding the ordinary program.
- Use first queue-front starts as duration anchors; following cars remain permission evidence.
- Exclude arrow-ambiguous waiting from negative main-GREEN evidence.
- Admit the incoming prefix of an automatically inferred curved main route on a T junction.
- Preserve legacy v7 models/journals; repair transactional observation callbacks and render v8.

## Independent controlled roads

Automatic offline models learn K=2/3/3/4 from four separate training recordings.
Eight evaluation controls use seeds disjoint from offline training. Each lasts 900s;
scoring covers seconds 180-889. Every truth head is scored; UNKNOWN is incorrect.
The SUMO lane/conflict/acceleration/gap/collision/red-entry gates pass in all eight.
Truth stays outside the estimator. These roads are not fitted replicas of real archives.

| Case | v7 correct | v8 correct | v7 false GREEN | v8 false GREEN |
|---|---:|---:|---:|---:|
| k2_blocked | 2566/2840 | 2688/2840 | 134 | 78 |
| k2_extension | 2532/2840 | 2618/2840 | 130 | 98 |
| k2_normal | 2558/2840 | 2640/2840 | 140 | 90 |
| k2_regime | 2502/2840 | 2634/2840 | 70 | 86 |
| k2_two_changes | 2490/2840 | 2636/2840 | 134 | 96 |
| k3_normal | 2564/2840 | 2661/2840 | 81 | 81 |
| k4_normal | 2560/2840 | 2705/2840 | 140 | 77 |
| t3_normal | 1942/2130 | 2000/2130 | 91 | 60 |

Total: **19,714/22,010 = 89.57% -> 20,582/22,010 = 93.51%**.
False GREEN: 920 -> 666 head-seconds. All eight aggregate scores and GREEN
recalls improve; this does not mean that every color or scenario improves.

The strict gate FAILS: the period-change false-GREEN count is **70 -> 86**;
T3 RED_YELLOW recall is **29/42 -> 16/42**. The latter is partly offset by
YELLOW **0/63 -> 22/63**, but the short-color regression remains visible.
The integrated v8 is selected for its measured aggregate improvement, not because
the strict acceptance gate passed. Do not present it as an accepted 95% estimator.

The first fresh set revealed a curved-main queue-geometry deficiency and was
used for development. The table above uses a subsequent frozen seed set. It is
now revealed, too. A production-wrapper docstring was corrected after freezing;
the inference statements were unchanged. Exact hashes/receipts are in
[the machine-readable record](causal_v8.json).

## Known real head and counterfactual

- Visible N GREEN/YELLOW interiors: v7 147/153; v8 **148/153 (96.73%)**.
- The same input smoothly stretched by +12s: v7 148/165; v8 **153/165 (92.73%)**.
  This is a time-scaled counterfactual, not footage of an observed emergency.
- Separate 90-minute GREEN onset: **3.416s -> 1.416s** distance to the conditional
  vehicle-supported clock envelope. RED remains 1.349s. These are known
  development labels, not a newly sealed all-head holdout.

The real candidate is a fork of the seven-day offline model; its queue references
come from 20,000 tracks in that model's own earlier offline archive. February 27
online data and video labels are not training inputs. Catalogue/K are unchanged.
Video association on Enthusiasts and complete six-archive lamp truth remain open.

## Application checks

- Full current suite: 1,563 passed, 3 skipped; later migration/arrow-waiting checks also pass.
- HTTP: 120 real packets, idempotence, validation, exact history/seek; p95 0.375s.
- Fresh process: 120 journal rows reconstructed exactly, then sequence 120 accepted.
- Actual headless Edge: 120 packets, visible colors after startup, 88 recordings,
  seek/resume/reload, offline play/seek, mobile width, zero JavaScript errors.
- Browser automation through the desktop connectors was unavailable; headless Edge
  exercised the real local HTTP application and its rendered canvas.

## Reproduce

```sh
python -m scripts.validate_causal_v8 --sumo-home PATH_TO_SUMO --output .web_runtime/new_v8_check --require-acceptance
python -m scripts.qa_intersection_delivery --base http://127.0.0.1:8017 --project MODEL_ID --packets real_packets.jsonl --out .web_runtime/new_browser_check
```

Install `eclipse-sumo==1.28.0` only for optional independent simulation. The first
command trains four models from raw records and evaluates eight controls; its
strict acceptance currently exits with code 2. The browser check additionally
requires Playwright and installed Edge. Neither is a production inference input.
Use new output directories; originals and previous receipts are preserved.
