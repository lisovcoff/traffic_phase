# Project status — 2D.1, 2026-10-14

2026-10-15 method-specific event/video join: one1.351s extraction from243 raw
tracks sealed548 events before loading signal references. Strict conditional-clock
window347 events:155 entry/154 crossing proxy/38 kinematic release. Existing
selector retains only38 releases (38 groups); lossless channels retain155 known
permission groups,117 absent from selected. Same-track dependence preserved.
Five N->S release offsets to the one observed H1 green onset range0.35–2.41s;
two N->E2.75/3.71s. These are associations, not causal reaction-time calibration;
mapping/independent stop support unresolved and shared clock uncertainty retained.
54 targeted tests passed. No phase fit/replay/default/threshold changes;2D.1 FAIL.
See EVENT_SIGNAL_ASSOCIATIONS_20261015.md. Next: H1 mapping plus direct restart
review for all7 N release tracks, more independent calibration cycles and validation.

2026-10-15 vehicle clock calibration: empirical H/clock registration fitted on9
video points from van9915665 and recovery truck9915986, sealed before5 trolleybus
9916124 points were scored. Max image residual7.80px training/23.31px heldout
within preregistered30/50px allowances. Candidate delta1.288667s relative to
09:59:55UTC+5; differs from manual binding by0.494s. Frozen-H conditional delta
set[0.700099,1.643698]s is NOT calibrated joint clock uncertainty. Local scope
273–393s only; no drift/production mapping or lamp accuracy claim.11 tests passed.
Initial solve invalid from epoch finite-difference cancellation, preserved with
exact code/seal; one documented numerical correction and technical repeat before
heldout inspection. No phase fitting/replay/default changes;2D.1 remains FAIL.
See VEHICLE_CLOCK_ALIGNMENT_20261015.md. Next: local method-specific event delay
calibration with explicit timing assumptions and H1 approach mapping; separate
validation session remains open.

2026-10-15 direct video check:90 source-pixel H1 crops reviewed; yellow/red,
red+yellow/green and lateral blinking distinguished. Group2 markers correspond
to different colors; first occurs during red, second during yellow under the saved
binding. Sampled presentation brackets saved with frame hashes; not calibrated
physical-switch intervals. Initial lateral-off onset is censored; final blink
cessation remains a candidate rather than a certified continuous OFF transition.
5 provenance/precision tests passed. Three full-context frames and nearby JSON
detections checked; no independently confirmed same-car synchronization anchors.
Video review progresses calibration but does not calibrate event delay or certify
lamp accuracy. No inference/default/main changes. See VIDEO_BOUNDARY_VERIFICATION_20261015.md.

2026-10-15 operator clarification: group1=additional-section off;
group2=possible yellow onset (explicitly tentative); group3=main green plus
additional section on. First group2 start corrected by user to10:04:28.028 in
derived evidence only, removing the overlap. Original export/intake retained.
These are onset claims, not continuous lamp states; no yellow duration inferred.
Video/JSON sync, section-to-movement mapping and independent validation remain
open. No inference, replay, default or historical metric changes.

2026-10-15 video review intake: five user intervals accepted structurally;
source SHA256/size/time extent match the prepared243-track sample. User reports
one visible head, yellow ignored, green/red onsets and additional-phase switch-off.
Export retains group1/2/3 without explicit event mapping; clarification requested.
One27.828s overlap is preserved pending confirmation. All share one unverified
manual video binding; no same-car synchronization certification or lamp accuracy
claim.16 existing validator tests passed. No inference/default changes. See
VIDEO_CALIBRATION_INTAKE_20261015.md.2D.1 FAIL and historical metrics unchanged.

2026-10-15 calibration preparation: existing 27.02 video is playable and a visible
signal section can be magnified for manual review. A single bounded scan of one
matching hourly JSON produced243 whole raw tracks for10:04–10:07; other ZIP entries
remain unopened. Workbench adds exact media cursor, +/-0.1s seeks and source-pixel
ROI with immutable per-mark provenance.24 targeted tests and browser checks passed.
Camera overlay differs from filename by about5s; JSON/video synchronization remains
UNVERIFIED until matching individual cars. No lamp truth, mapping, calibrated delay,
or production prior inferred. See VIDEO_CALIBRATION_PILOT_20261015.md for the prepared
local sample and review instructions.2D.1 FAIL/default-off and real0/11/19/34 unchanged.
Next: independently review video/vehicle anchors and visible section states, then
certify a separate validation split before fitting any real observation parameters.

2026-10-15 joint-track model: an isolated correlated Poisson observation prototype
was tested once on24 declared synthetic inputs after59 targeted tests. Both
priors retained: core stable/hold/shortening matches29/30 and30/30, per-case gate
9/10 and10/10 (flat has one FAIL). Finite-grid posterior intervals are conditional
on supplied rates/delays/exposure and known K/order/start/count; no real accuracy
or nominal coverage claim. No-demand/all-missing outputs are prior-only; logical
and physical publication remain UNKNOWN. Production/default and historical gates
unchanged; no real replay. See JOINT_TRACK_OBSERVATION_RESULTS_20261015.md.
Next: verify suitability/synchronization of the existing video and matching JSON
for independent calibration before transferring synthetic parameters to real data.

2026-10-15 local evidence experiment: isolated app.experimental.local_evidence
preserves method/type channels and same-track dependence, without changing the
production selector. 49 pre-run tests passed. One bounded transformation of three
saved sidecars retained all 80 old selected events and recovered 256 crossing
proxies; 336 events represent 256 known track groups, not independent lamp
observations. No labels, extraction, fitting, boundary evaluation or defaults changed.
No calibrated signal delay/exposure is asserted. Legacy timestamp union is
explicitly unavailable; the subsequent joint model is now tested only in the
declared synthetic setting with supplied nonexclusive marks/delay/exposure. See
LOCAL_EVIDENCE_CHANNELS_RESULTS_20261015.md. 2D.1 FAIL and 0/11/19/34 remain.

2026-10-15: one authorized bounded baseline on the three NEW expert-reviewed
dates completed after protocol/code freeze and 50 tests. K=3/2/2 matches operator
groups; raw and baseline each match 0/11 internal boundaries at +/-2s (10 predicted).
This is separate from the unchanged historical raw19/34 cohort. Censored 0/180s
edges excluded. Temporal coverage=100% of labelled blocks; physical UNKNOWN540/540.
No default, period solver, selector, K search or decoder changes. No retries/tuning.
A further one-test diagnostic confirms the existing selector's remote-RELEASE
removal of local crossing proxies; it is a mechanism witness, not an accepted fix.
The preregistered evidence-preserving representation is now tested separately;
method-specific observation likelihood and independent calibration remain open.
See EXPERT_INTERVAL_BASELINE_20261015.md. 2D.1 remains FAIL.

2026-10-15 manual intake: three new development review exports accepted as
operator phase-duration hypotheses (14 intervals). All source SHA256/size and
schema checks passed. Operator reports <=2s signal timing error and sparse
Enthusiasts traffic; these claims are recorded, not independently calibrated.
Two small interval overlaps and window censoring remain explicit. See
MANUAL_REVIEW_INTAKE_20261015.md. No fitting/evaluation or default changes.

2026-10-15: user authorized the root ROADMAP.md and its first step. The local
annotation workbench is implemented at /annotation (START_ANNOTATION.cmd): raw
trajectory playback, vehicle selection, interval marks, expert intersection
knowledge, optional local video anchor, source-bound export/import and drafts.
Trajectory-based phase labels remain hypotheses; external labels remain review
claims pending verification. 18 targeted tests and browser round-trip checks
passed; no phase fitting/replay or production algorithm/default changes.
The interval-label adapter and first baseline are complete; continue the independent calibration pilot. See
docs/ANNOTATION_WORKBENCH.md. Original 2D.1 FAIL and known regressions remain.

Product goal reaffirmed 2026-10-15: see PRODUCT_GOAL.md (JSON/archive -> phase
count/composition -> approach signal sections -> local history -> HTML, including
nonstandard intersections and RF operating scenarios). Readiness audit:
PROJECT_AUDIT_20261015.md. Core acceptance does not imply HTML contract parity;
confirmed integration defects remain open. No new decoder or real replay run.

Checkpoint base: `c99268b700b2b46bc0202a2a37f635e3af93f70d`.
2C and the protective state/query contract are accepted. **2D.1 remains FAIL**,
experimental opt-in/default-off. The event-time prototype was checked only in
its declared finite synthetic model; neither prior is selected for production.
Exclusive-mark constraints must not be transferred to real RELEASE evidence.
Unchanged real development results: predicted K **3/2/3**, truth **3/2/2**,
raw boundaries **19/34 within +/-2s**. The three familiar recordings are
development data, not an untouched holdout; these are not lamp-accuracy scores.
Next step: an independent calibration pilot with a separate validation session,
as specified in VALIDATION_PROTOCOL.md, section 8. Work is paused pending those
materials: no new decoder/likelihood/prior experiments or real replay.
Main and production defaults remain unchanged. The history below is retained.

Stages 1 and 2A are accepted as audit/planning and a reproducible offline baseline.
Stage 2B.1 is accepted as an engineering improvement in temporal evidence,
provenance and per-stream selection. Its event timing and lamp semantics have
not been independently validated. Accepted A–D and event-level recording-6
diagnostics are preserved; they were not repeated for 2B.2.

2B.2 adds conservative result semantics and abstention; it does not improve or
retrain phase discovery. Physical UNKNOWN is reported separately from model
history coverage. External vehicle-event and lamp validation remain open.
Known regressions (including recording 6 K 2→3 and degraded boundary results
after changed evidence ingestion) remain in the unchanged
`benchmarks/stage2b1_20261013/comparison.json`. No parameters were selected to
repair these results.

Production base: `afcfaa2b38e106201d7e819570425acfc4c5487f`.
Only uncertainty/structured-abstention code and its tests were taken from
`1207344bdcbc46edbf19bace65382ee0252d1f4d`; diagnostic runners/artifacts were
not used as the production base. Main remains unchanged.

Top-level `millis`: according to the supplied description from `Инфо.docx`,
this is the time when the vehicle left the intersection. This is provided field
semantics, not a measured stop-line crossing. Camera/controller synchronization,
endpoint timing accuracy and the relation to the stop line remain unverified.
The historical `millis - move_duration_millis` calculation remains a proxy.

The canonical V9 core renderer now delegates to the shared state contract.
Prepared immutable history supports repeated queries without repeated validation.
Malformed histories give UNKNOWN/INVALID_PHASE_HISTORY; valid gaps/out-of-range
queries give UNKNOWN/NO_TEMPORAL_COVERAGE. Explicit configured/simulated modes
remain distinct from reconstructed physical states. Follow-up base:
`8bb7ca1a9d8137001028f2c6b6e8e6af98d42201`.

2B.2 including canonical V9 query follow-up is accepted. 2C is accepted:
universal candidate admission and bounded, transparent phase-count comparison.
Base: `36b6752a4794e482570944b22656d6cc58f0db31`. Prior baseline/regressions remain
preserved; any new development metrics do not close independent event/lamp
validation.

The original 2D.1 scope was a single fixed-model local duration decoding,
separate from recurring-plan discovery. Raw/baseline fields are preserved.
No-demand/missing local evidence remains UNKNOWN; camera coverage and lamp
switch timing are not inferred. External validation and known development
regressions remain open. Base `b248b4c7bac27def4a131ba61301f2678cd0b05a`.
No 2D.2, skip/reorder, multiple-regime extension or online work is authorized.

2D.1 is **FAIL / NOT ACCEPTED**. Its supported real history has0/34 matched
boundaries; its diagnostic candidate has7/34, versus accepted raw19/34. Removing
the UNKNOWN mask does not fix the candidate failure. Historical results remain
unchanged. Local reconstruction is now explicitly opt-in/default-off; accepted
2C discovery/query behavior is restored. Experimental queries require explicit
source selection and abstain in gaps/unavailable results without raw fallback.

A single predeclared sparse-event review also failed its per-case recovery gate
(7/16 core cases fail) and publishing/identifiability gate. No real replay was
allowed or performed. The conditional-mark candidate is diagnostic only; no
replacement history is approved. A justified observation/demand/exposure model
and interval-uncertainty/support method are required before further publication.
See SPARSE_OBSERVATION_2D1_REVIEW.md. External event/lamp validation remains open;
no2D.2/online work is started. Await further instruction.

An isolated event-time feasible-set prototype (2026-10-14) was evaluated once
on 18 new synthetic cases with two preregistered priors, outside production.
All 12 correctly specified truth paths are feasible, but sets remain broad and
transition counts ambiguous. The unchanged per-case point-recovery criterion
fails for both priors (4/10 and 1/10 core cases). Historical 2D.1 remains FAIL;
default/production, old gates, results and evaluator are unchanged. No real
replay, fitting, K search or 2D.2 work occurred. See EVENT_TIME_PROTOTYPE_2D1.md.
