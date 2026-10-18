# Yellow/clearance and transferable head-timing method

User explicitly requests yellow, video ground truth at both intersections and
universal algorithm improvement. This authorizes this new bounded round; main
and prior evidence remain intact. Branch feature/yellow-universal-timing-20261019.

Reference: GOST R52289-2019,7.5.2 (official government-hosted copy and Rosstandart
status): yellow3s, red-yellow<=2s, optional no-red-yellow sequence and legacy
controller exception. Red-yellow does not permit movement. Green blinking is
different from yellow and LED camera alias; do not invent its timing from dark
frames. Normative durations are model assumptions until video confirms them.

Video development: existing first-window labels900..1500 plus native crops
around Sverd1019/1067..1070,1119/1167..1170; Enth1008.75/1074..1078 and nextcycle.
At most two calibration cycles per site for detailed yellow/red-yellow review.
Freeze the universal transition construction and calibration parameters before
reading fresh lamp validation3300..3600 at both sites. Existing baseline second
window2700..3300 has been seen; never present it as an untouched holdout.

Shared algorithm: obtain per-head stable binary runs from actual local history,
merge GREEN->GREEN across phase changes, insert yellow immediately BEFORE a
predicted red onset, red-yellow immediately BEFORE green onset. Keep arrows
GREEN/OFF (no invented yellow arrow), gaps UNKNOWN, no circular replay or
transitions at unobserved recording edges. Refuse contradictory short runs;
do not shorten a nominal3s to conceal contradictory inferred timing. Annotate
normative vs calibrated timing provenance, no physical observed-state claim.
Optional constant onset-specific delays are learned from clock-linked first
window only by the same generic median rule for any supplied head/site; never
fit clock to light colors. Apply calibrated offsets only under explicit source/
site/time provenance. No blanket universal2.644s offset for unlabelled roads.

Fresh evaluation: three cycles3300..3600 per site, video labels sealed before
prediction comparison. Scalar JSON/video accuracy requires a supported vehicle
clock link. Enth has no such transform: evaluate observed durations/sequence,
not invented JSON timing accuracy. Report missing/dim/ambiguous endpoints.
Check frozen Sverd clock at a moving car near3600 if extrapolation matters.
Compare original binary, normative transitions, and frozen calibrated transitions
on identical confident frame/state samples; per-color boundaries and duration-
weighted state errors separately. No repeated tuning on this new window.
