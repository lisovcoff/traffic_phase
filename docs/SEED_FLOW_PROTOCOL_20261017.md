# Native verification of external reviews — one isolated seed-flow correction

Base `b7675c70bf191a20454fe974baa18cc161f01856`.
Branch `fix/review-seed-flow-20261017`. Main remains unchanged.
Both external reviews are preserved verbatim under evidence/review_intake_20261017.
Their instructions/results are review input, not automatically trusted evidence.

Only D1 is changed in production: move existing seed deduplication after the
existing K3 split generator. No changed generator, dedup signature, threshold,
criterion, score, ensemble preference, event selection, period, decoder or mapping.
The other seven findings get independent local counterexamples, remain explicitly
open strict xfails, and will not be bundled or adjusted after real metrics.
Gemini's assumed2s lag, fixed transition times, queue=RED, motion=GREEN,
observed-event exposure mask, likelihood-drop confidence intervals and baseline
accuracy guarantees are NOT adopted. No new observation model/prior is inferred.

Local before test: imported fully inspected tests with --runxfail. All8 reported
defects must reproduce in their own counterexamples; before/after logs retained.
Structural gate for D1: both distinct parents visit seed fit and refinement at
dt.5/1/2; duplicate seed not repeated; K2 route preserved; both splits finish the
actual decoder. Existing recurrence/K4/renaming/shared/budget/cache/query tests.
An xfail is an open defect, never evidence of a passing quality requirement.

Native experiment is new and separate from Astra's stopped cross-platform run.
At most1 unchanged native control19 +3 patched cached discovery workers,90s each,
360s total worker allowance, max1 suite, no tuning/retries. Cache inputs and prior
b767 results hashed before fitting; exact TemporalEvent/selection/anchor checks.
Raw trajectory files/ZIP not opened. Seed0,dt1,K2..6/max5/cooperative60s unchanged.
Control gate predeclared before native control: raw segments and K exact;
selected indices exact; finite baseline/period diagnostic floats atol1e-12s,
rtol0, remaining discrete fields exact. This accounts only for tiny numerical
roundoff; evaluator tolerance remains exactly2s. Report exact equality separately.
Stop on any other mismatch. Do not rewrite/waive the external failed exact gate.
Capture passive seed/refinement traces without changing decisions or scores.

Commit code/config after tests and before patched comparison. Seal every output
hash before opening original *_manual_marks.json. Use unchanged full evaluator
and original annotations by pinned hashes (available locally), not reconstructed
labels or optimal test permutations for physical claims. No UI, videos or tuning.

Report K/period; raw AND baseline matched/truth/predicted counts, precision/recall
±2s, matched MAE/p95, nearest MAE, temporal coverage/UNKNOWN, runtime and candidates.
Useful development change requires no loss of prior K matches, and either more
correct K or raw matched>19/34, no per-record raw matched/precision/nearest-MAE
regression, aggregate precision>=19/41 and complete requested K search in budget.
Otherwise report no gain/tradeoff/FAIL, not production accuracy acceptance.
Period, selection, event hashes are invariants. Mark 2D.1 FAIL/default-off and
physical state UNKNOWN regardless of synthetic success. Known records remain
development, not holdout. Stop after the single comparison.
