# traffic_phase

Backend prototype for estimating traffic-light phase structure from vehicle trajectories when the signal itself is not directly visible.

## Current MVP

The current baseline:

- keeps trajectories with category_name == "car";
- uses millis as the time axis;
- groups trajectories by zone_in -> zone_out movement;
- extracts delayed departures from stay_duration_millis;
- estimates a dominant traffic cycle with autocorrelation;
- folds movement activity into the estimated cycle;
- detects candidate phase-transition points;
- reconstructs a two-group signal model (N/S versus E/W);
- models GREEN/YELLOW/RED/RED+YELLOW/UNKNOWN states for playback;
- exposes the analysis through FastAPI.

The repository is an inference baseline. It is not a validated traffic-light classifier yet: labelled signal-phase ground truth would be required to report classification accuracy.

## Target architecture

The planned evolution is deliberately incremental:

~~~text
trajectory JSON
    |
    v
trajectory normalization
    |
    v
detections / geometry
    |
    v
traffic events
(APPROACH / STOP / RELEASE / CROSSING)
    |
    +--------------------+
    |                    |
    v                    v
event-based flow      event evidence
    |                    |
    v                    v
cycle estimation --> phase discovery
                         |
                         v
                  signal state
                         |
                         v
                  realtime inference
                         |
                         v
                  anomaly handling
                         |
                         v
                    validation
~~~

### Stage 1 — audit and architecture

The current code already contains the main MVP layers, but trajectory loading is duplicated between the legacy app/core/analyzer.py path and the newer preprocessing/reconstruction path. The first architectural goal is therefore to establish stable boundaries without removing the working baseline.

### Stage 2 — detections and geometry

The source trajectory format can contain detections[] with millis, lat, and lng. The current Trajectory model does not retain these samples, so they are currently discarded during normalization. Geometry must be introduced behind an explicit intersection/stop-line configuration rather than inferred from arbitrary coordinates.

### Stage 3 — traffic events

Convert trajectories into timestamped events such as APPROACH, STOP, RELEASE, and CROSSING. These events become the preferred phase evidence because a continuing trajectory should not be mistaken for a new signal transition.

### Stage 4 — event-based cycle estimation

Build a time-series signal from traffic events and estimate the dominant cycle using autocorrelation. Keep the existing trajectory-based estimator available for regression comparison while validating the event-based estimator on reference and abnormal archives.

### Stage 5 — event-based phase discovery

Fold events by t mod cycle, aggregate evidence across cycles, and infer the mutually exclusive N/S and E/W phase intervals. Keep the model extensible for additional phase groups.

### Stage 6 — signal-state reconstruction

Convert phase position and event evidence into GREEN, YELLOW, RED, RED+YELLOW, or UNKNOWN. Prefer a small probabilistic/state-transition model over introducing HMM/EKF unless validation shows a measurable benefit.

### Stage 7 — realtime inference

Add a stateful rolling inference engine that accepts new events incrementally and produces the current phase, per-approach state, confidence, cycle position, and evidence summary. Batch and realtime results must be regression-tested against each other.

### Stage 8 — anomaly handling

Use normal reference archives as a baseline for identifying flow anomalies such as collisions, lane closures, congestion, missing releases, and unexpected conflicting movement. An anomaly must reduce confidence or produce UNKNOWN rather than automatically being interpreted as a red light.

### Stage 9 — validation

Separate structural/traffic-consistency metrics from true signal classification accuracy. Without labelled controller states, the system must not claim signal-light accuracy. Validation should cover cycle stability, phase coverage/overlap, event support, contradiction rate, state continuity, realtime/batch agreement, and anomaly behaviour.

## Important data limitation

The supplied trajectory format includes both aggregate trajectory fields and optional detailed detections. The current MVP uses aggregate fields such as millis, zone_in, zone_out, speed, stay_duration_millis, move_duration_millis, and distance. Detailed detections (millis, lat, lng) are not yet part of the normalized model.

This means the current phase model is based on temporal traffic-flow evidence rather than explicit stop-line crossing geometry. That is the main technical gap to close before treating the reconstruction as a stronger indirect signal-phase inference system.

## Project structure

~~~text
app/
  api/       HTTP routes
  core/      trajectory analysis logic
  schemas/   API/data models
  main.py    FastAPI application
scripts/     local utility scripts
tests/       automated tests
~~~

## Run locally

~~~bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
# .venv\\Scripts\\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --reload
~~~

Swagger UI: http://127.0.0.1:8000/docs

## Docker

~~~bash
docker build -t traffic-phase .
docker run --rm -p 8000:8000 traffic-phase
~~~

## Tests

~~~bash
pytest -q
~~~

## Input data

The analyzer follows the supplied trajectory format: vehicle id, millis, zone_in, zone_out, category, detections, and optional motion/waiting parameters. The project currently uses the supplied intersection trajectory archives as development data.
