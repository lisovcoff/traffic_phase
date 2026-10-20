# Traffic Phase

**English** · [Русский](README.ru.md)

Infer traffic-signal phases from vehicle trajectories when signals are not directly
visible. Upload one intersection's JSON or ZIP and inspect vehicles and estimated
signals in an interactive player. Video and manual labels are evaluation material,
never production inputs.

**Status:** whole-archive offline and causal online inference are implemented.
Full accuracy acceptance is still in progress. Signal hardware and
colors remain estimates; trajectories can leave them ambiguous.

**Latest acceptance check (October20): 95% is not established.** A copied real
JSON with a12s longer green exposed premature yellow/red:89.09% on labelled
N-green/yellow seconds, versus96.08% in the original narrow window. Six new
paired physical controls scored85.68% across all main-head colors. Production
remains v7; simple workarounds were rejected for yellow errors.
[Comparison, modified inputs, players and next work](docs/INCIDENT_VALIDATION_RESULTS_20261020.md).

**Earlier correction (October20):** comparable mode likelihoods, preserved selective
turn states/sections, and online renderer compatibility. On two previously revealed
N-main video windows, cross-day onsets improved from12/18 to18/18 within5s, with
one extra red onset. Working-K regressions improved54/72→70/72 and18/24→24/24.
All four other archives passed held-member motion replay; their lamp accuracy is
unmeasured. Eight new synthetic controls scored86.44% versus86.57% before, so
universal color-accuracy improvement is **not established**.
[Results, ready local players and limitations](docs/CROSS_DAY_RECOVERY_RESULTS_20261020.md).

## Run

Python **3.12** is the tested version. From the repository root on Windows:

```bat
INSTALL.cmd
START_WEB.cmd
```

Open **http://127.0.0.1:8017/visualization**. Stop an old server with `Ctrl+C` before
restarting it after an update. `START_WEB.cmd --check` verifies imports without
starting a server. In the existing local workspace, the parent launcher forwards
to the same repository in `audit_checkout/`; fresh clones have a normal project root.

Other platforms:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-tested-py312.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8017
```

## Analyze

1. Select trajectory JSON or ZIP recordings of **one intersection**.
2. Click **Analyze**. All supported JSON members and observation sessions are
   processed automatically; individual failures remain visible in partial results.
3. Select a recording. Use play/pause, speed, timeline seeking, or precise date/time
   in Yekaterinburg time (UTC+05:00). No phase count or hardware profile is required.

Upload the original vehicle data, not `feed_manifest.json` or an analysis report.
For online replay, open a completed model first and select `real_packets.jsonl`
in **Test JSONL stream**, not in the offline upload field.

The model stores observed approaches, candidate head configurations, working phase
count K, recurring signature groups, duration statistics and provenance. Three- and
four-approach schematic views are supported. Sources retain separate clocks and
track namespaces; gaps are not joined into an invented history.

Results persist in `logs/intersection_projects/<model_id>/`. Reopening a completed
model does not fit it again. Model download is structural, not yet a portable bundle
of the original upload and players; retain the local project folder for playback.
Interrupted unfinished jobs do not yet resume automatically. Raw datasets, virtual
environments and runtime logs are excluded from Git.

## Online

Click **Online** in the same panel. The displayed POST endpoint accepts a packet
each second; for a demo, select JSONL with one packet per line. Switch between
archive and live view, seek the original online history by time, and resume live.
Accepted packets and original responses persist transactionally in SQLite and
restore after restart. Duplicate packets are idempotent; conflicting sequences
and future detections are rejected. Online never discovers a new K or hardware plan.

A replay file is finite: when it ends, the last packet stays on screen and a
completion message shows the accepted count. New movement requires more packets.
Replay timing accounts for request processing time instead of adding it to each pause.

Packets contain `sequence`, `timestamp_ms`, and `vehicles`. Each vehicle has `id`,
`zone_in`, and current `detections`: `millis`, `centroid_x`, `centroid_y`, `zone`,
and optional `speed`, `lat`, `lng`. Geographic positions help when vendor speed
is unreliable. Future `zone_out` is forbidden. Empty vehicle arrays are valid
heartbeats and do not prove red. [API and measured limits](docs/INTERSECTION_ONLINE_RESULTS_20261019.md).

## Accuracy

The measured offline component processed219 real sources. Latent K matched68/72 synthetic
development cases and24/24 reserved cases; phase-state error was4.01% and2.85%.
A fresh visible-head video block matched8/9 switches within2s, subject to documented
clock assumptions. These are conditional results, not universal physical accuracy.

Working head configurations are a separate measure: current projection matches
54/72 and18/24 already-revealed regression cases. Re-projection lowers main-head
color error from6.79% to5.99% and9.18% to7.47%, with no regressed cases in that
96-case comparison. This is not new independent validation.

Two diagnostic online streams with changed durations reach about89% and88% main
color accuracy including UNKNOWN after180s synchronization. All3 green onsets in
an already-revealed real window fall within2s, with an extra onset and worse
yellow/red timing. Same-recording offline training and conditional clock mapping
limit this evaluation. Model confidence is not calibrated lamp probability.

The product workflow was checked on2 complete real archives/9 sessions, all9 saved
players, desktop/mobile Edge, and8 T-intersection structural scenarios. Full suite:
1449 tests PASS. [Workflow evidence](docs/INTERSECTION_PROJECT_RESULTS_20261019.md),
[accuracy evidence](docs/ACCURACY_RECOVERY_RESULTS_20261019.md).
The integrated online delivery passes1462 tests, the launch/smoke checks and
desktop/mobile browser history/recovery checks; see the online report above.

Changing durations, weekend programs, unusual extensions and live synchronization
still need integrated acceptance. The signature catalogue does not certify controller
programs. An empty approach can remain unseen; a turning vehicle does not prove an
arrow. An extension's cause cannot be identified as an emergency vehicle/motorcade
without distinguishing observations.

## Repository

| Path | Purpose |
|---|---|
| `app/api/`, `app/core/` | Application API and inference |
| `scripts/` | CLI and reproducible validation |
| `tests/`, `.github/` | Tests and CI |
| `docs/` | Status, design, instructions and reports |
| `config/` | Configuration and retained diagnostic schemes |
| `evidence/`, `benchmarks/`, `validation/`, `diagnostics/` | Research evidence; not runtime inputs |
| `logs/` | Local uploads, models and output; ignored by Git |

[Documentation](docs/README.md) | [Roadmap](ROADMAP.md) | [Status](docs/PROJECT_STATUS.md).
The [previous README](docs/history/README_PRE_CONSOLIDATION_20261019.md) is archived;
its dated findings do not override current instructions. Research evidence is
retained, including rejected experiments and their limitations.

## Developer checks

```sh
python -m compileall -q app scripts tests
python -m pytest -q
python -m scripts.e2e_smoke
```

Run `git lfs pull` for the large Lenina fixture. Small JSON plans are ordinary Git files.
Legacy annotation and explicit-profile tools remain separate evaluation utilities.
