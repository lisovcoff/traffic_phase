# Direct-video truth and delay calibration — 18.10.2026

User explicitly requests both local MP4 files, bottom-left clock readout, matching
JSON, visible-head frame truth and checking/correcting apparent late green.
This authorizes new video work and bounded model calibration. Main and all old
artifacts stay intact; use a separate branch. Do not silently fit clock offset
from signal predictions: that would erase the error being measured.

First identify the two recordings by metadata, saved byte identities and fresh
native frames. Read camera clocks visually. Use actual PTS, not requested seek
time; retain native ROI endpoint frames and intervals, including mixed/unknown
frames and variable-frame-rate gaps. Frame precision is an image appearance
bracket, not a calibrated physical exposure or device-clock precision.

Sverdlovsky: source archive is Ленина-Свердловский 27.02.25.zip. Previous
overlay readings are 27.02.2025 09:59:55 at PTS0.066667. Initial clock convention
remains a conditional camera-clock relation, to be checked independently from
signal changes. Existing vehicle/geometry uncertainty remains visible.
Enthusiasts: supplier-linked MP4 byte identity was established previously, but
overlay05.10.2024 and export23.02.2025 do not share an epoch. Do not substitute
the filename date or align cycles to claim clock verification. Match independent
vehicles/events or retain UNVERIFIED with an explicit request for useful help.

For any accepted clock/head mapping: freeze direct video labels BEFORE joining
predictions. Keep main head and lateral arrow separate; do not infer unobserved
heads by complement. The user is asked for orientation/movement mapping.

Candidate fresh Sverdlovsky windows: PTS900..1500s for calibration,
PTS2700..3300s for validation (six cycles/window approximately). Observe both
through a fixed coarse sampler then refine transitions with native neighboring
frames. These windows are fixed independently of new model errors. Earlier
reviewed windows near240..420s are development history, not new holdout.
If these windows are unusable, record the obstruction before choosing replacements.
Calibrate a single constant head-specific delay only if the sign and spread of
training errors support it; no threshold/phase/clock parameter search against
validation marks. Score the untouched second window once, include all misses
and extra green-onsets, signed delay and uncertainty. Retain original output and
compare before/after. Do not retrain existing classifier profiles or replace
default discovery under the guise of synchronization.

Initial budgets: four full-context frames per video, two native clock windows
per video up to2s each; coarse head sampling max3fps in the declared windows;
native refinement max2s/70frames per transition, max40transitions per source.
Increase only with a recorded reason tied to a specific unresolved observation.
No full-movie frame dump or deletion of user material.
