# traffic_phase

2026-10-19: [independent four-car clock check and N-main calibration](docs/CARDINAL_CLOCK_LINK_RESULTS_20261019.md).
Open `evidence/cardinal_clock_link_20261018/visible_head_comparison.html`, select
the Sverdlovsky MP4 and compare before/after. Supported JSON clock delta1.254s;
source-time green/red corrections2.644/3.685s. Main-only export, separate from
production profiles. Enthusiasts clock remains unresolved; concrete car review:
`evidence/cardinal_clock_link_20261018/enthusiasts_identity_review/index.html`.

Direct video check: [clock readouts, native frames and conditional delay](docs/DIRECT_VIDEO_TRUTH_RESULTS_20261018.md).
Open `evidence/direct_video_truth_20261018/visible_head_comparison.html` and select
the Sverdlovsky MP4 to compare the visible head and before/after timing proposals.
No server/upload needed. These proposals remain separate from the app pending
independent JSON/video clock and cardinal-head confirmation.

2026-10-18: [new calibrated model and real-data results](docs/LEARNED_PHASE_RESULTS_20261018.md).
Run `START_WEB.cmd`, then open http://127.0.0.1:8017/visualization/learned.
Choose the intersection and upload JSON/ZIP; prediction needs no annotation file.
Restart an already running server to load this route. Three frozen intersection
models are included. On the chronological second-half holdout, timing matches
improve from7/13 to11/13 in ±2s (11/15 predicted boundaries match).
Training uses first-half operator marks and supplies the number of phases;
this is same-session validation, not automatic phase discovery or lamp truth.
Open `evidence/learned_release_20261018/summary.html` for results and ready viewers.

2026-10-18: [five post-review algorithm checks and duration correction](docs/ALGORITHM_CHECK_RESULTS_20261018.md).
K2 refinement now supports the same duration flexibility as K3 (verified20/80-cycle
counterexample). Real timing scores remain15/17,1/8,3/9; four other candidates
are not enabled because they did not pass the frozen comparison.

2026-10-18: [manual-marks validation and corrected Sverdlovsky signal scheme](docs/MANUAL_MARKS_VALIDATION_20261018.md).
The default signal estimate uses four main heads with additional sections only
on N/E for the confirmed Sverdlovsky profile; W/S have no extra sections.
All three labelled JSON files rerun. Strict timing matches:15/17,1/8,3/9;
remaining timing errors are recorded, not hidden by the display correction.

2026-10-18: [spatial view now shows colored phase/movement estimates](docs/MODEL_PHASE_VIEW_20261018.md).
Use the display selector to inspect physical lamps separately; unverified lamps stay UNKNOWN.

Delivery candidate, 2026-10-18: [launch, verification and measured accuracy](docs/DELIVERY_20261018.md).
Windows/Python 3.12: `INSTALL.cmd`, then `START_WEB.cmd`.
The tested dependency versions are in `requirements-tested-py312.txt`.

Local web launch: `START_WEB.cmd`, then http://127.0.0.1:8017/visualization.
Automatic archive/session jobs: http://127.0.0.1:8017/visualization/batch.
The batch page exports predictions, per-session HTML and a reproducible manifest;
timeouts/unprocessed sessions stay UNKNOWN. [Budgets and verified scope](docs/BOUNDED_ARCHIVE_BATCH_20261016.md).
This is a working development workflow, **not final accuracy acceptance**:
local extensions remain 2D.1 FAIL; physical sections/lamps require independent evidence.

Development roadmap: [ROADMAP.md](ROADMAP.md). Manual review tool:
double-click `START_ANNOTATION.cmd` or run `py -3 -m scripts.run_annotation`;
open http://127.0.0.1:8011/annotation. [Instructions](docs/ANNOTATION_WORKBENCH.md).

Research/prototype module for estimating traffic-signal phase structure when
the physical signal is not directly visible and only vehicle trajectories are
available.

Product objective and completion criteria: [PRODUCT_GOAL](docs/PRODUCT_GOAL.md).
Current acceptance status: [PROJECT_STATUS](docs/PROJECT_STATUS.md).
The [2026-10-15 readiness audit](docs/PROJECT_AUDIT_20261015.md) records remaining
algorithm/physical-validation and HTML-contract gaps. The historical viewer and
baseline descriptions below do not establish verified lamp reconstruction.

## V9 direction-agnostic discovery

V9 is the discovery core. It does not require phase names, compass-direction
semantics, a fixed number of phases, or manual labels as inputs to discovery.

The pipeline is:

    JSON / ZIP
        |
        v
    trajectory records
        |
        v
    release + input-entry event views
        |
        v
    hybrid period inference
        |
        v
    anonymous movement streams
        |
        v
    cyclic HSMM phase segmentation
        |
        v
    PHASE_A / PHASE_B / PHASE_C ...
        |
        +--> periodic baseline
        |
        +--> temporary phase-deviation diagnostics
        |
        +--> causal realtime tracker
        |
        +--> V10 physical signal semantics / visualization

The V9 implementation lives under app/core/v9/.

## Run V9

Single JSON, ZIP archive, or directory of JSON files:

    python -m scripts.v9_phase_discovery path/to/input.json
    python -m scripts.v9_phase_discovery path/to/archive.zip
    python -m scripts.v9_phase_discovery path/to/json_directory

The command writes:

    v9_output/phase_discovery_v9.json

## Canonical spatial visualizer control point

The known-good spatial viewer control point is commit:

    0768f510c0dc93e1fbac16877c1c5440b5faa76e

The canonical renderer is scripts/v9_spatial_visualizer.py. The offline CLI and
the Uvicorn endpoint /visualization/analyze must use the same builder
build_spatial_visualization(). This keeps V9 discovery, V10 physical signal
semantics, additional arrow sections, timing, and the final HTML viewer on one
code path.

Large JSON/ZIP archives use the same path-based discovery as V9 CLI, including
streaming event extraction and large-recording regime selection. The web layer
must not switch back to discover_records(load_source(...)) for archive analysis.

Offline reference command:

    python -m scripts.v9_spatial_visualizer path/to/input.zip --output spatial.html

Do not maintain a second independent spatial-rendering implementation in the
web layer. Changes to the spatial viewer should be checked against the control
point above before being accepted.

## Unified web visualization

Start the application:

    python -m uvicorn app.main:app --reload

Open:

    http://127.0.0.1:8000/visualization

Upload a JSON or ZIP archive and press **Запустить анализ**. The server runs V9
discovery, applies the V10 physical signal semantics when the model contains a
physical plan, and opens the spatial visualization with reconstructed vehicle
flows, signal heads, additional arrow sections, phase timeline, period and
deviation diagnostics.

The visualization is self-contained after the server generates it; the browser
does not need direct access to the original archive.

## API

    GET  /api/v1/v9/info
    POST /api/v1/v9/analyze
    POST /api/v1/v9/realtime

V9 realtime currently consumes timestamped anonymous movement events. It is
causal and does not infer a specific cause for a sustained phase deviation.

## Validation

The repository CI runs Python compilation, the full pytest suite, an end-to-end
smoke test, and the Lenina regression fixture.


## Known-good Lenina–Sverdlovsky baseline

Reference baseline:

    commit: df544b18e844c17059cfa678237e70885c3a8cac
    input: 17_2025_2_19_10.json
    V9: 2735 trajectories / 2728 events / 9 streams / 3 phases
    period: 99.842813 s

This is the reference regression point for Lenina–Sverdlovsky. Physical-signal
changes must preserve its NS protected-turn signature and its EW/NS through
signals.

For every web analysis the server writes a complete run trace under
logs/<run_id>/, including the V9 result, V10 physical plan, 0.1-second signal
timeline, manifest, and generated HTML viewer.
