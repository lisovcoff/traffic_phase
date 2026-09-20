# traffic_phase

Indirect traffic-signal phase inference from vehicle trajectories when the physical traffic signal is not directly visible.

> **Important:** this project does not observe a traffic-light controller. `GREEN`, `YELLOW`, `RED`, `RED_YELLOW`, and `UNKNOWN` are model states inferred from vehicle-trajectory evidence. The supplied trajectory archives do not contain labeled controller states, so the project does not claim traffic-light classification accuracy.

## 1. Task and scope

The implementation covers the supplied task: infer and visualize the current traffic-light phase for a four-approach intersection (N/S/E/W) from indirect traffic-flow information.

The production pipeline is event-based. It normalizes car trajectories, validates detections, extracts traffic events, estimates the recurring cycle, discovers recurring phase intervals, reconstructs per-approach signal states, exposes the same model through the realtime API and browser playback, and reduces confidence when the traffic pattern is anomalous or insufficient for a reliable inference.

The system infers traffic-light phase structure; it does not send commands to a physical controller and does not measure lamp state directly.

## 2. Input data

A trajectory JSON file is a list of vehicle objects. The production loader uses:

- `id`
- `millis`
- `zone_in`, `zone_out`
- `category_name`
- optional motion fields such as `speed`, `stay_duration_millis`, `move_duration_millis`, `distance`
- optional `detections[]` containing `millis`, `lat`, `lng`

Only `category_name == "car"` enters the production pipeline. Approaches are expected as `N`, `S`, `E`, `W`; exit zones may retain the source `_` prefix.

`millis` is the primary time axis. Detection timestamps are validated and sorted. Invalid detection coordinates or timestamps are ignored for geometry and contribute to trajectory-quality degradation.

## 3. Final architecture

```text
trajectory JSON
      |
      v
preprocessing / normalization
      |
      v
detections + geometry
      |
      v
trajectory events
(APPROACH / STOP / RELEASE / CROSSING)
      |
      +-------------------------+
      |                         |
      v                         v
event flow signal          phase evidence
      |                         |
      v                         v
cycle estimation -------> phase discovery
                                |
                                v
                         signal state model
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
      realtime inference                    browser playback
             |
             v
      anomaly-aware confidence
             |
             v
         validation
```

`app/core/reconstruction.py` is the authoritative batch orchestration layer shared by API analysis and visualization. Validation reuses the same event extraction logic. Legacy modules such as `analyzer.py` and `phase_discovery.py` remain only for historical comparison/regression scripts and tests; they are not the production playback path.

## 4. Algorithm

### 4.1 Detection geometry

Valid consecutive detections are evaluated with the Haversine distance:

`d = 2 R asin(sqrt(sin²(Δφ/2) + cos(φ1) cos(φ2) sin²(Δλ/2)))`

with `R = 6,371,000 m`. Segment speed is distance divided by elapsed time. A robust median smoother is applied before sustained STOP and RELEASE detection.

### 4.2 Event extraction

- `APPROACH`: first valid detection.
- `STOP`: speed remains below the configured stop threshold for a sustained interval.
- `RELEASE`: after STOP, speed rises above the release threshold for a sustained interval.
- `CROSSING`: uses an optional configured stop-line provider; otherwise the final valid detection is used as the fallback crossing timestamp.

`STOP` and `APPROACH` are never treated as direct RED evidence. RELEASE/CROSSING are the positive traffic evidence used for phase inference.

### 4.3 Cycle estimation

RELEASE contributes weight `1.0`; CROSSING contributes `0.5`. N/S traffic is positive, E/W traffic negative, creating a signed directional flow signal. The existing autocorrelation-based cycle estimator scores candidate periods and returns period, confidence, candidate periods, stability and repetition metadata.

### 4.4 Phase discovery

RELEASE/CROSSING evidence is folded by `t mod cycle`, aggregated across absolute cycles and optimized into recurring mutually exclusive intervals. Before schedule optimization, each phase group's temporal profile is normalized independently so absolute traffic volume in one direction does not by itself make that phase appear longer. The default intersection model has two groups: NS and EW.

The phase model also stores the raw timestamp origin of the event timeline. This origin is propagated to playback, validation and realtime inference so absolute `millis` values are not silently mixed with normalized seconds.

### 4.5 Signal-state reconstruction

The phase model provides the structural prior. Recent RELEASE/CROSSING activity contributes traffic-evidence confidence.

Possible model states:

- `GREEN`
- `YELLOW`
- `RED`
- `RED_YELLOW`
- `UNKNOWN`

Yellow and RED_YELLOW are modeled transition windows around inferred phase boundaries; the default duration is 2 seconds and is not presented as an observed controller value.

No recent movement is not automatically interpreted as RED.

### 4.6 Anomaly handling

Normal reference scenarios form a robust `TrafficBaselineProfile` using median/MAD statistics. The anomaly layer evaluates flow deviation, movement imbalance, unusual stopping, missing expected release, unexpected conflicting release flow and data sufficiency.

An anomaly may reduce confidence or return `UNKNOWN`. It must not manufacture a GREEN-to-RED switch simply because traffic became silent.

Reference profiles are built per reference dataset after timestamp rebasing and then aggregated; raw absolute timestamps from different archives are never pooled into one artificial timeline.

## 5. Local installation

PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m compileall -q app scripts tests
python -m pytest -q
```

Run the server:

```powershell
uvicorn app.main:app --reload
```

Open:

- `http://127.0.0.1:8000/health` — health check
- `http://127.0.0.1:8000/docs` — Swagger UI
- `http://127.0.0.1:8000/visualization` — browser playback

## 6. API

### Batch analysis

`POST /api/v1/phase/analyze` accepts one trajectory JSON file.

The response includes the unified event-based cycle and phase model, source statistics, timestamp origin, `ground_truth: "UNAVAILABLE"`, and explicit limitations.

### Realtime event inference

`POST /api/v1/realtime/infer` accepts one `TrajectoryEvent` at a time.

The stream is stateful and idempotent. Duplicate event IDs are safe. Reusing an existing event ID with different event data returns HTTP 409.

A phase payload contains `cycle_seconds`, `bin_seconds`, phases and `origin_timestamp_ms`. When the origin is present in the phase model, the realtime engine can derive it without the client duplicating timestamp alignment logic.

### Realtime trajectory inference

`POST /api/v1/realtime/trajectory` accepts a raw trajectory object. It uses the same production trajectory-to-event extraction path as batch processing and can receive the same anomaly baseline profile.

`DELETE /api/v1/realtime/streams/{stream_id}` resets state for a stream.

## 7. Frontend / visualization manual check

Start the server and open `/visualization`.

1. Extract one JSON member from a ZIP archive. The browser endpoint accepts JSON, not ZIP.
2. Choose the JSON file and press **Load JSON**.
3. Confirm that the page shows the fixed 0.5-second playback timeline anchored to the raw `millis` origin.
4. Check that the cycle estimate, phase map and four approach signal panels appear.
5. Press **Play** and **Pause**.
6. Move the timeline slider through at least one phase boundary.
7. Confirm that `UNKNOWN` is displayed distinctly and that the UI states that ground truth is unavailable.
8. Copy or download `review.log`.

The cars shown on the intersection are illustrative. They are seeded from inferred traffic evidence and are not a replay of individual detections.

### What to look for manually

On a normal reference scenario, the two active opposing approaches should remain paired and the phase should change as a recurring schedule rather than jittering every frame.

At a boundary, the two sides should exchange state in a consistent way, with the configured transition window appearing around the inferred boundary.

When recent event evidence disappears, the UI must not interpret that silence as direct proof that the physical lamp is RED.

On an anomaly scenario, lower confidence or `UNKNOWN` is expected to be a possible result; an anomaly should not automatically reverse a state solely because traffic flow dropped.

## 8. Realtime smoke test

First obtain a phase model from `/api/v1/phase/analyze`. Then send a request such as:

```json
{
  "stream_id": "manual-smoke",
  "event_id": "evt-1",
  "phase_model": {
    "cycle_seconds": 100,
    "bin_seconds": 2,
    "origin_timestamp_ms": 1000000,
    "phases": [
      {
        "phase_id": 1,
        "phase_start": 0,
        "phase_end": 40,
        "active_approaches": ["N", "S"],
        "confidence": 0.9,
        "supporting_event_count": 10,
        "contradictory_event_count": 1,
        "members": ["N", "S"]
      },
      {
        "phase_id": 2,
        "phase_start": 40,
        "phase_end": 100,
        "active_approaches": ["E", "W"],
        "confidence": 0.9,
        "supporting_event_count": 10,
        "contradictory_event_count": 1,
        "members": ["E", "W"]
      }
    ]
  },
  "event": {
    "event_type": "RELEASE",
    "timestamp_ms": 1010000,
    "approach": "N",
    "movement": "N->_S",
    "confidence": 1.0,
    "quality": "HIGH"
  }
}
```

Repeat the same `event_id`. The second result must set `duplicate=true`, and the rolling event count must not increase.

Reuse the same `event_id` with a different timestamp or approach. The API must return HTTP 409.

Send an out-of-order event and verify that the stream timestamp does not move backwards.

## 9. Full validation with all source archives

The repository provides `validation/manifest.local.example.json`. It maps the eight task scenarios to a local `data/` directory.

Expected layout:

```text
traffic_phase/
  data/
    Ленина-Энтузиастов 10.02.25-17.02.25.zip
    Ленина-Энтузиастов 05.10.24.zip
    Чичерина-40 Лет Победы 12.04.24.zip
    Чичерина-40 Лет Победы 19.04.24.zip
    Ленина-Энгельса 05.02.25-07.02.25.zip
    Ленина-Энгельса 18.02.25.zip
    Ленина-Свердловский 11.02.25-19.02.25.zip
    Ленина-Свердловский 27.02.25.zip
```

Copy the example:

```powershell
Copy-Item validation\manifest.local.example.json validation\manifest.local.json
```

Run the unified pipeline:

```powershell
python scripts/validate.py `
  --manifest validation/manifest.local.json `
  --output-dir validation_output
```

### Quick validation

Use the same local manifest and select only the compact smoke set while
iterating locally. This avoids maintaining a second local manifest with
duplicated machine-specific archive paths:

```powershell
python scripts/validate.py `
  --manifest validation/manifest.local.json `
  --dataset reference_chicherina `
  --dataset accident_lenina_sverdlovsky `
  --dataset lane_closure_chicherina `
  --sample-seconds 10 `
  --output-dir validation_quick
```

`--dataset` can be repeated for any names in the manifest. `--sample-seconds
10` reduces only the density of signal-state samples; use the default `1` and
the full manifest before release when comparing detailed signal metrics.

The quick set excludes the large multi-day reference archives and missing
Lenina-Engelsa archives. It is a smoke check, not a replacement for full
validation. To verify a change specifically against the Lenina-Sverdlovsky
reference archive, select `reference_lenina_sverdlovsky`; it remains a large
archive and is intentionally part of full validation.

The command produces:

- `validation_output/validation_report.json` — machine-readable report;
- `validation_output/validation_report.md` — human-readable report.

The command exits with code 1 when a dataset has an ingestion, cycle, phase, signal or realtime validation error. A broken dataset is therefore not silently presented as a successful validation run.

### Metrics

Cycle metrics:

- period
- confidence
- stability
- repetitions
- candidate count
- reference period
- reference error

Phase metrics:

- coverage
- overlap
- cycle consistency
- supporting event count and ratio
- contradictory event count and ratio

Signal metrics:

- state continuity
- transition consistency
- mean state confidence
- `UNKNOWN` rate
- anomaly mean/max score
- anomaly condition counts
- false GREEN/RED switch rate

Realtime metrics:

- mean latency
- p95 latency
- peak `tracemalloc` memory
- maximum rolling buffer size
- batch/realtime agreement

These are consistency, behaviour and runtime metrics. They are not traffic-light classification accuracy.

### Reference comparison

The pooled reference period is the median of all successfully processed datasets marked `reference`.

For non-reference scenarios, `reference_error_seconds` is the absolute difference from that pooled period.

When at least two reference datasets exist, each reference dataset also receives a leave-one-out reference error so it is not evaluated against itself.

No archive gets a custom threshold. The same code, configuration and manifest are used across all scenarios.

## 10. How I will verify your manual archive run

When you send the generated `validation_report.md`, `validation_report.json` and selected `review.log` files, the verification is reproducible.

I will check:

1. every manifest dataset is present in the report;
2. failed datasets are explicit errors, not silently omitted;
3. reference period/error values use the common reference pool and leave-one-out logic where applicable;
4. phase coverage and overlap agree with the phase model;
5. event support/contradiction counts are internally consistent;
6. anomaly scenarios lower confidence or produce `UNKNOWN` when evidence becomes unreliable instead of inventing RED from silence;
7. batch and realtime outputs agree on the same event stream;
8. latency and rolling-buffer measurements remain finite and bounded;
9. `review.log` around phase boundaries does not show implausible state jitter;
10. `git diff`, `git status`, CI results and README descriptions match the actual implementation.

The strongest conclusion available from the supplied archives is that the inference pipeline behaves consistently with recurring traffic-flow structure and remains internally coherent under reference and abnormal scenarios.

A true accuracy claim requires ground-truth controller states or equivalent labeled signal-phase observations.

## 11. Known limitations

- The traffic signal is inferred indirectly; no controller state is observed.
- The source archives do not provide labeled GREEN/RED/YELLOW ground truth.
- The default intersection model assumes two opposing groups: NS and EW.
- Without a configured stop-line geometry provider, CROSSING falls back to the last valid detection.
- Detection-based speed quality depends on valid timestamps, GPS coordinates and sampling density.
- Yellow and RED_YELLOW durations are modeled transition windows, not observed controller timings.
- Anomaly scores indicate deviation from a normal traffic baseline; they do not identify the real-world cause of the deviation.
- The browser vehicle sprites are illustrative rather than raw-trajectory replay.
- Large source archives are kept outside the repository and should be validated locally.

## 12. Project structure

```text
app/
  api/
    routes.py
    realtime.py
    visualization.py
  core/
    reconstruction.py
    preprocessing.py
    trajectory_geometry.py
    trajectory_events.py
    event_cycle_estimator.py
    event_phase_discovery.py
    signal_state_estimator.py
    realtime_inference.py
    anomaly_profile.py
    anomaly_inference.py
    validation.py
    playback.py
    review_log.py
scripts/
  validate.py
validation/
  manifest.example.json
  manifest.local.example.json
tests/
```

## 13. Automated checks and CI

Local:

```powershell
python -m compileall -q app scripts tests
python -m pytest -q
```

CI runs the same compile check and pytest on Python 3.12.

## 14. Docker

```powershell
docker build -t traffic-phase .
docker run --rm -p 8000:8000 traffic-phase
```

The container exposes the API and visualization. The source trajectory archives remain outside Git.

## 15. Source archive classification

The local manifest follows the source task classification: the Lenina-Entuziastov 10.02.25–17.02.25, Chicherina 12.04.24, Lenina-Engelsa 05.02.25–07.02.25 and Lenina-Sverdlovsky 11.02.25–19.02.25 sets are reference scenarios; the other supplied scenarios are accident or lane-closure cases.

Keep these archives under `data/` only for local validation. They should not be committed to the repository.
