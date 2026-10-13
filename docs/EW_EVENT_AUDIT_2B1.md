# Event-level E→W audit, recording 6

Scope: all 26 current A and all 8 legacy D selected events from the accepted,
sealed ablation. No fitting, phase evaluation, threshold changes or production
extractor changes. Selection was fixed before examining source tracks.

Initial HEAD: `6f75e81cf6f22d7e1e14f2fad0c0348e9811f9a1`.
Audit runner commit: `8b6c966bc0a1040f2dc4c47916ae320273bab215`.
Producer and contract are version 1; exact file hashes and the unchanged
`EventExtractionConfig` are in `manifest.json`. This branch descends from the
accepted ablation branch, which descends from `afcfaa2` on the requested fix
branch. Production files, old ablation artifacts and main remain unchanged.

## Observed facts

One streaming source pass traversed 1,901 records and retained the complete
union of 26 unique tracks. Source SHA256:
`57d04137cc1d8383d89edbd4a88084c1a874f8ee7e6eb2d206954624c2753651`.
Current fingerprints match saved provenance; all eight legacy times/methods
match the legacy view recomputed only on retained tracks. No missing or
ambiguous track IDs were found. All 26 current RELEASE times reproduce locally.

| Quantity | Result |
|---|---:|
| Current `kinematic_restart_proxy` events | 26 |
| Legacy `kinematic_release` events | 6 |
| Legacy `metadata_dwell_end_restart` events | 2 |
| Exact current/legacy timestamp pairs | 6 |
| Legacy metadata events replaced by different current image times | 2 |
| Additional current tracks absent from legacy selection | 18 |
| Current candidates after observed zone transition | 21/26 |
| Raw exact-zero speed observations in the union | 0 |
| Emitted sustained-zero STOP in the union | 0 |

The two replaced metadata events are tracks 4636959 and 4637670. Their metadata
candidates pass the observed speed-count, before/after median, gap, duration
and legacy plausibility guards, but fail the current sustained-zero prerequisite.
The current producer instead emits an image-motion candidate. The evidence
contains every guard outcome, not just these examples.

These facts establish timestamp selection mechanics. They do not establish a
physical stop, queue release, permissive movement or green lamp. Relative image
motion is coordinate displacement per second, with coordinate units UNKNOWN.
Zone transition is an observed label change, with stop-line relationship UNKNOWN.
The existing 1.3/3-second heuristic radii are unvalidated event heuristics;
neither calibrated vehicle timing intervals nor lamp-switch error intervals.

## Artifacts and independent review

`evidence/stage2b1_ew_event_audit/events.csv` has all 34 rows, with membership,
fingerprint, timestamps, zone runs, candidate position, support counts, raw
speed and image-motion summaries, and extractor reasons. `event_details.json`
also contains local observations, all sampling gaps, emitted provenance,
metadata guards and captured image-solver bounds/results. `source_tracks.json`
contains the retained raw track objects, without changing their field values.

`field_semantics.md` and `semantic_sources.json` separate verified consumer
operations from missing producer definitions. `independent_review_template.json`
has 34 unfilled review slots. Identifiers locate observations; truth type, timing,
visibility, geometry, source and uncertainty remain null. Review types should be
STOP / RESTART / ACCELERATION / NONE / UNOBSERVABLE; no lamp labels are required.

Independent vehicle-event validation alone is **BLOCKED** pending original video,
frame-to-millis synchronization, producer/calibration definitions, verified zone
polygons and stop-line geometry with a coordinate transform. Trajectory-based
mechanism diagnostics are complete. No phase annotation file was opened.
A historical report encountered while searching duration/line definitions also
contained aggregate phase results; none were used in selection, extraction,
tests or conclusions. The event set and extracted artifacts were already fixed.

## Diagnostic test correction and validation

C's actual interception now uses `candidate_upper_hook`, which delegates to the
previously tested bound helper. Tests invoke this actual hook and verify solver
arguments, detection identity, provenance and fallback when outgoing observations
are missing. Production extraction and accepted A–D results were not rerun.

Commands and full output are in `commands.log`, `extraction.log`, `tests.log` and
`verification.log`. Only the affected diagnostic modules were run: **10 passed**.
Pytest reported one cache-write warning; no test failure. No benchmark or fitting
was run. Extraction runtime (4.42 s) covers the event audit and is not a component
profile. The ZIP contains this report, runner/tests, source excerpts and checksums.

Recommended next task: obtain independent vehicle observations and calibrations,
then blind-review all 34 rows using the template. Assess whether each image
candidate is restart, acceleration or unobservable before proposing new evidence
rules. Do not infer signal semantics or tune thresholds from these tracks alone.
