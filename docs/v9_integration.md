# V9 integration

V9 is the repository's anonymous, direction-agnostic phase-discovery path.

## Discovery contract

The discovery model receives trajectory JSON records and infers:

- traffic period;
- anonymous movement streams;
- phase count;
- cyclic phase order;
- phase duration targets;
- per-stream activity by anonymous phase;
- a stable periodic baseline;
- temporary timing deviations.

Manual marks are optional post-hoc evaluation only. They are never passed into
phase discovery.

API:

    GET  /api/v1/v9/info
    POST /api/v1/v9/analyze
    POST /api/v1/v9/realtime

The analyzer accepts a JSON file or a ZIP archive of JSON trajectory members.
It reuses the repository's streaming trajectory loader before running V9.

CLI:

    python -m scripts.v9_phase_discovery path/to/archive.zip
    python -m scripts.v9_phase_discovery path/to/directory --marks path/to/marks.json

## Architecture

    JSON / ZIP
        |
        v
    repository preprocessing / streaming loader
        |
        v
    V9 event views
        |-- input-zone entry
        |-- dwell/restart evidence
        |-- kinematic release candidate
        |
        v
    hybrid period inference
        |
        v
    anonymous stream occupancy
        |
        v
    cyclic HSMM
        |
        v
    periodic baseline
        |
        +-- phase timeline
        |
        +-- temporary timing deviations
        |
        +-- causal OnlinePhaseTracker

The V9 discovery path does not use IntersectionConfig or the default NS/EW
families as phase labels. The older production stack remains available for
compatibility and regression tests.

## Realtime contract

Offline analysis produces a model containing a period, anonymous phases, stream
activity and a recurring baseline. OnlinePhaseTracker consumes only arrived
timestamped stream events and estimates short-term phase position plus schedule
shift relative to the baseline.

A positive sustained schedule shift is reported as a temporary phase extension
or delay. A negative shift is reported as a temporary advance. No cause is
inferred.

The historical baseline is not rewritten by one unusual cycle.

## Synthetic validation

The V9 test suite covers unequal 2-, 3- and 4-phase cycles, missing traffic
events, a blocked stream, timestamp jitter, arbitrary stream names,
repository-normalized records and the causal online tracker.

The next expansion should cover:

- 5+ phases and very short phases;
- 10-50% missing detections;
- burst noise and duplicate events;
- variable traffic volume;
- out-of-order archive members;
- partial archive boundaries;
- temporary phase extension and shortening;
- gradual period drift;
- multiple streams active during one phase;
- multiple anonymous regimes.

Report phase-count accuracy, period error, boundary MAE and anomaly-detection
performance separately. Do not reduce all of them to one headline number.

## Integration status

The v9-integration branch is additive. Existing legacy and production modules
are not removed. Large source archives remain outside the repository.

V9 lives under app/core/v9/ so the discovery algorithm can be tuned without
coupling phase discovery to the existing intersection topology configuration.
