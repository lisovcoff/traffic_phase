# traffic_phase

Indirect traffic-signal phase inference from vehicle trajectories when the
physical traffic signal is not directly visible.

> **Important:** the supplied archives do not contain labelled controller
> states. GREEN/RED/YELLOW/RED_YELLOW/UNKNOWN are inferred model states, so
> this project does **not** claim traffic-light classification accuracy.

## Scope

The repository implements two demonstration modes:

1. **Batch archive analysis** — analyze an existing trajectory JSON or ZIP,
   split long time gaps into independent traffic sessions, estimate cycle and
   phase structure, and visualize the reconstructed state.
2. **Realtime simulation** — replay an existing JSON/ZIP causally. Individual
   detections become visible only when their own timestamp is reached, so
   APPROACH/STOP/RELEASE/CROSSING can be confirmed before a trajectory ends.
   The realtime engine warm-starts from a timestamp-independent phase template
   and synchronizes its current cycle offset from arrived RELEASE/CROSSING
   evidence.

The default model is intentionally small: one four-approach intersection with
two opposing groups, NS and EW. There is no ML model and no physical
controller integration.

## Production path

```text
JSON / ZIP
   |
   v
preprocessing + detection geometry
   |
   v
APPROACH / STOP / RELEASE / CROSSING events
   |
   v
30-minute session split
   |
   +--> event-flow cycle estimation
   |
   +--> event-based phase discovery
   |
   v
batch session result + bounded timeline
   |
   +--> timestamp-independent realtime phase template
            |
            v
       circular offset synchronization
            |
            v
       realtime signal-state inference
            |
            v
       archive simulator / UI
```

Authoritative production modules are:

- `app/core/reconstruction.py`
- `app/core/archive_analysis.py`
- `app/core/event_cycle_estimator.py`
- `app/core/event_phase_discovery.py`
- `app/core/signal_state_estimator.py`
- `app/core/realtime_phase_sync.py`
- `app/core/realtime_inference.py`
- `app/core/realtime_simulation.py`

`app/core/analyzer.py` and `app/core/phase_discovery.py` are **legacy
comparison-only** implementations kept for benchmark/regression scripts.
Production API modules must not import them.

## Input semantics

Only records with `category_name == "car"`, `zone_in`, `zone_out`, and
`millis` enter the production loader. When present, `detections[]` provides
`millis`, coordinates, and the optional detection `zone`.

CROSSING evidence is selected in this order:

1. configured stop-line provider;
2. observed exit from the incoming detection zone into the unzoned
   intersection interior, or directly into the configured outgoing zone;
3. final-detection fallback only when named detection-zone information is
   absent, with reduced confidence.

An incomplete trajectory that contains named zones but never observes the
incoming-zone exit does not invent a fallback crossing.

RELEASE has event-flow weight 1.0; CROSSING has weight 0.5. STOP and APPROACH
are not direct evidence that a physical lamp is RED.

## Batch analysis

`POST /api/v1/phase/analyze` accepts either one trajectory `.json` or a
`.zip` containing trajectory JSON members.

ZIP members are decoded sequentially and are not extracted into a working
directory. Large raw detections are not accumulated as one giant in-memory
archive. The response contains `sessions[]`; each session has cycle/phase
results, confidence, counts, status/error information, and a bounded timeline
for the browser.

A gap greater than 30 minutes starts a new session by default. Cycle and phase
models are estimated independently per session.

The batch phase model stores an absolute origin because it describes that
historical session. That origin is **not** reused as the realtime clock.

## Realtime synchronization

A `RealtimePhaseTemplate` contains cycle length and recurring phase
intervals, but no historical absolute timestamp. On a new stream the engine
starts in:

```text
WARMUP
phase_id = null
N/S/E/W = UNKNOWN
```

The synchronizer incrementally scores candidate circular offsets using only
RELEASE/CROSSING events already received. It requires evidence from both phase
groups before declaring `SYNCHRONIZED`. No future event is consulted.

After synchronization the current cycle position is computed from the
realtime timestamp plus the estimated offset. Moving simulated time forward
without a new event advances the inferred phase clock but does not add
synchronization evidence.

## Realtime archive simulator

API:

```text
POST   /api/v1/realtime/simulations/start
POST   /api/v1/realtime/simulations/{id}/step
GET    /api/v1/realtime/simulations/{id}/status
POST   /api/v1/realtime/simulations/{id}/reset
DELETE /api/v1/realtime/simulations/{id}
```

The simulator may know the offline playback ordering, but the realtime engine
only receives detections whose own timestamps have been reached. Partial
trajectory snapshots are idempotent and confirmed events are emitted once.
The simulation registry is bounded and old simulations are evicted when its
capacity is exceeded.

Batch phase discovery can conservatively recover bounded NS/EW transition
gaps from the recurring coarse conflict-family schedule when both families
have strong multi-cycle support. Recovery is not allowed across an internal
same-family boundary (for example N -> N+S) or across a distinct movement
candidate. Batch sessions also expose an operational model quality class:
GOOD, PARTIAL, or INSUFFICIENT. Technically successful but insufficient
models are not offered as realtime warm-start templates.

Uncovered cycle intervals are classified rather than treated as one generic
UNKNOWN bucket. Short gaps between conflicting NS/EW families are reported as
CLEARANCE_CANDIDATE; persistent gaps in an otherwise high-confidence model or
gaps containing recurring movement evidence are UNRESOLVED_STAGE; weakly
observed gaps are UNOBSERVED. The API reports a separate unresolved-UNKNOWN
rate so clearance candidates do not artificially count as unexplained signal
state.

Recurring regimes from different physical sessions are clustered by cycle
length and cyclically aligned N/S/E/W structure. D.8 retains the raw
RELEASE/CROSSING events for each analysis segment, aligns members of a regime
family into one synthetic cycle frame, and reruns EventPhaseDiscovery on the
pooled evidence instead of treating already reconstructed phases as ground
truth. Movement candidates and promoted movement stages are therefore inferred
again from the combined cross-day evidence. The older phase-vote consensus is
kept only as a diagnostic comparison.

Weak segments may use coarse NS/EW raw-event similarity to attach to an
established timing-plan family, while strong segments still have to agree on
fine N/S/E/W stage structure. Ambiguous weak segments are kept separate rather
than contaminating two plausible families. Realtime prefers a GOOD pooled
raw-event family model when at least two members support it.

Short gaps between conflicting families are no longer automatically called
clearance when recurring movement evidence is present. Such gaps are reported
as TRANSITION_AMBIGUOUS and still count toward unresolved UNKNOWN until pooled
cross-day evidence resolves them.

Realtime snapshots expose template-compatibility diagnostics, instantaneous
UNKNOWN reasons, cumulative/post-sync/rolling-60s UNKNOWN rates, and temporary
live-override duration. A stream that uses approaches outside the configured
intersection topology is rejected; a stream with enough evidence from both
families but persistently poor fit to the Batch template is marked
INCOMPATIBLE instead of being presented as synchronized.

## Browser demonstration

Run:

```powershell
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/visualization`.

**Batch**:

1. choose a JSON or ZIP;
2. analyze it;
3. select a session when more than one exists;
4. inspect cycle, confidence, phase model, timeline, slider/playback, and the
   shared NS/EW intersection view.

**Realtime simulation**:

1. first obtain a successful Batch session from a reference archive for the
   same intersection;
2. switch to Realtime simulation;
3. choose a JSON/ZIP source;
4. use Start, Step, Play/Pause, Reset, and x1/x5/x20/MAX;
5. verify that startup is WARMUP/UNKNOWN and that phase/state appears only
   after synchronization evidence is sufficient.

The JavaScript does not infer phase. It displays backend snapshots.

## Tests and fast acceptance smoke

```powershell
python -m compileall -q app scripts tests
python -m pytest -q
python -m scripts.e2e_smoke
```

The smoke uses a tiny synthetic trajectory set and checks the complete
batch-to-realtime path. CI runs these commands and never downloads or opens
the multi-gigabyte validation archives.

Useful comparison scripts remain available:

```powershell
python -m scripts.benchmark_cycle_estimators path\to\sample.json
python -m scripts.benchmark_phase_models path\to\sample.json
python -m scripts.benchmark_signal_states path\to\sample.json
```

The first two intentionally compare legacy and production approaches. They are
diagnostic benchmarks, not alternate production entry points.

## Full six-archive validation

The available local validation manifest contains six archives for three
physical intersections:

- Lenina-Sverdlovsky: reference + accident;
- Lenina-Entuziastov: reference + accident;
- Chicherina-40 Let Pobedy: reference + lane closure.

The unavailable Lenina-Engelsa pair is not required by the current manifest.

Create the local manifest once if needed:

```powershell
Copy-Item validation\manifest.local.example.json validation\manifest.local.json
```

Then run the final validation:

```powershell
python scripts/validate.py `
  --manifest validation/manifest.local.json `
  --output-dir validation_output_final
```

Reference periods and anomaly baselines are scoped by `intersection_id`;
datasets from different physical intersections are not pooled into one
reference baseline.

Outputs:

- `validation_output_final/validation_report.json`
- `validation_output_final/validation_report.md`

Reported cycle, phase, signal, anomaly, and realtime metrics are
consistency/behaviour/runtime measurements. They are not controller-state
accuracy.

## Known limitations

- There is no labelled signal-controller ground truth in the supplied data.
- The default phase structure assumes two opposing groups: NS and EW.
- Sparse or imbalanced traffic can reduce phase confidence or leave the state
  UNKNOWN.
- Yellow and RED_YELLOW are modeled transition windows, not observed lamp
  timings.
- A CROSSING fallback based on the final detection is weak evidence and is
  used only when named detection-zone information is absent.
- Batch ZIP processing assumes members are chronological by trajectory time;
  malformed members are reported separately when possible.
- Realtime synchronization assumes the recurring phase template remains
  applicable to the simulated stream; offset is learned from arrived traffic
  evidence.
- Large source archives stay outside the repository and are validated locally.

## Project layout

```text
app/
  api/
    routes.py
    realtime.py
    realtime_simulation.py
    visualization.py
  core/
    reconstruction.py
    archive_analysis.py
    preprocessing.py
    trajectory_geometry.py
    trajectory_events.py
    event_cycle_estimator.py
    event_phase_discovery.py
    signal_state_estimator.py
    realtime_phase_sync.py
    realtime_inference.py
    realtime_simulation.py
    validation.py
scripts/
  e2e_smoke.py
  validate.py
  benchmark_*.py
validation/
  manifest.local.example.json
tests/
```
