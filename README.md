# traffic_phase

Research/prototype module for estimating traffic-signal phase structure when
the physical signal is not directly visible and only vehicle trajectories are
available.

## V9 direction-agnostic discovery

V9 is the new research path in this repository. It does not require phase
names, compass-direction semantics, a fixed number of phases, or manual labels
as inputs to discovery.

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

The V9 implementation lives under app/core/v9/.

## Run V9

Single JSON, ZIP archive, or directory of JSON files:

    python -m scripts.v9_phase_discovery path/to/input.json
    python -m scripts.v9_phase_discovery path/to/archive.zip
    python -m scripts.v9_phase_discovery path/to/json_directory

Optional post-hoc manual validation:

    python -m scripts.v9_phase_discovery path/to/input.json --marks path/to/manual_marks.json

The command writes:

    v9_output/phase_discovery_v9.json

## Offline spatial visualization

Create a self-contained browser visualization with a fixed N/S/E/W
intersection, reconstructed signal heads, turn-arrow sections, and only the
vehicle detections present in the input JSON:

    python -m scripts.v9_spatial_visualizer path/to/input.json --output v9_spatial.html

Open the generated HTML in a modern Chrome/Edge browser. The HTML contains the
compressed trajectory detections and does not require the Python server after
generation.

The physical signal-head mapping used by the visualizer is:

    N head: N->S main, N->E / N->W arrows
    S head: S->N main, S->E / S->W arrows
    E head: E->W main, E->N / E->S arrows
    W head: W->E main, W->N / W->S arrows

V9 discovery itself remains direction-agnostic; this mapping is a visualization
interpretation layer for the canonical four-approach intersection.

## API

    GET  /api/v1/v9/info
    POST /api/v1/v9/analyze
    POST /api/v1/v9/realtime

Run the application:

    python -m uvicorn app.main:app --reload

The existing visualization and legacy production endpoints remain available.

## Realtime concept

Offline V9 analysis produces an intersection-specific baseline:

    period
    anonymous phase order
    phase duration targets
    stream activity by phase

OnlinePhaseTracker then consumes only events that have already arrived. It
estimates the current anonymous phase and a short-term schedule shift.

A positive sustained shift is reported as a temporary phase extension/delay.
A negative shift is reported as a temporary advance. The cause is intentionally
not inferred.

## Synthetic validation

The V9 regression suite covers:

- 2-, 3- and 4-phase unequal cycles;
- missing events and a blocked stream;
- timestamp jitter;
- arbitrary stream names;
- repository-normalized trajectory fields;
- causal online tracking.

Run:

    python -m pytest -q tests/v9

The broader synthetic benchmark is:

    python -m scripts.v9_synthetic_benchmark

It reports phase-count accuracy and boundary metrics for diverse generated
scenarios. It is a research benchmark, not controller ground truth.

## Existing repository

The repository already contains a larger legacy/production stack for batch
archive streaming, reconstruction, signal-state inference, realtime
synchronization, anomaly handling and browser visualization. V9 is isolated
from the explicit intersection-topology assumptions in that stack so the
discovery algorithm can be tuned independently.

See docs/v9_integration.md for the V9 architecture and validation plan.

Large real traffic archives are kept outside the repository.