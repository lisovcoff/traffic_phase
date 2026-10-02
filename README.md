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
