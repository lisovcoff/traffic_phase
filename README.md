# traffic_phase

Research/prototype module for estimating traffic-signal phase structure when
the physical signal is not directly visible and only vehicle trajectories are
available.

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
