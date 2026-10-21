# Measurements

**English** · [Русский](README.ru.md)

The tables and figures use pandas-aggregated counts from the frozen
[v8 receipt](causal_v8.json). [Exact statistics and source hash](statistics.json).
The plotting script, raw archives, videos and generated runs remain local.

## Controlled scenarios

Eight SUMO scenarios use different random seeds from the four offline training
recordings. Each lasts 900s; scoring covers seconds 180-889, every main head and
all colors. UNKNOWN is incorrect. Seven scenarios have four heads, one has three:
22,010 head-seconds in total. One head-second means one head evaluated for one second.

The simulator's lane, conflict, acceleration, gap, collision and red-entry checks
pass. These are controlled roads, not calibrated replicas of the real sites.
The controls are now revealed; further tuning needs a new frozen evaluation set.

![Scenario accuracy and per-color recall](figures/replay_evaluation.png)

| Metric | v7 | v8 |
|---|---:|---:|
| Correct / total | 19,714/22,010 | 20,582/22,010 |
| Overall accuracy | 89.57% | **93.51%** |
| GREEN recall, n=7,966 | 96.77% | **99.37%** |
| RED recall, n=12,969 | 91.10% | **94.66%** |
| YELLOW recall, n=645 | 3.72% | **22.64%** |
| RED_YELLOW recall, n=430 | 38.60% | **56.51%** |
| False GREEN, head-seconds | 920 | **666** |

Accuracy improves in each scenario, but not every error type improves. In the
period-change case false GREEN rises **70 -> 86**. On the T junction RED_YELLOW
recall falls **29/42 -> 16/42**. The strict no-regression gate therefore **FAILS**.
Short transition timing remains the main weakness; overall accuracy is dominated
by the much longer GREEN/RED intervals. UI labels do not repair these errors.

## Real-data coverage

| Archive | Independent lamp-reference coverage |
|---|---|
| Lenina-Sverdlovsky, February 11-19 | Offline model; no complete lamp history |
| Lenina-Sverdlovsky, February 27 | Known visible-N windows; conditional vehicle-supported clock |
| Lenina-Enthusiasts, October 5 | Visible E and crash footage; JSON/video association unaccepted |
| Lenina-Enthusiasts, February 10-17 | No paired independent lamp history |
| Chicherina-40 Let Pobedy, April 12 | No usable paired lamp video |
| Chicherina-40 Let Pobedy, April 19 | No usable paired lamp video |

Known visible-N GREEN/YELLOW interiors: **148/153 = 96.73%**. A smoothly stretched
copy with +12s green: **153/165 = 92.73%**, a counterfactual rather than an observed
emergency. Separate GREEN onset error is **1.416s**, versus 3.416s for v7; RED
remains 1.349s. These known development measurements use a conditional clock and
do not establish all-color/all-head accuracy across six archives.

The corpus processed 219 sources: 216 ZIP members and three loose JSONs. Parsing,
phase discovery and lamp-color accuracy are different measurements. There is no
full independent lamp reference for every archive. A numerical theoretical
maximum and universal 95% are not established. Empty traffic, unseen obstructions
and permissive turns can leave different signal histories observationally identical.

## Reproduction

See the [guide](../GUIDE.md) for automated application checks and the optional
SUMO validator. Simulator truth and video labels never enter runtime inference.
Per-second labels are correlated; they are not independent statistical trials.
