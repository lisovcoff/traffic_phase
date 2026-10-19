# Traffic Phase

**English** ? [???????](README.ru.md)

Infer traffic-signal phases from vehicle trajectories when signals are not directly
visible. Upload one intersection's JSON or ZIP and inspect vehicles and estimated
signals in an interactive player. Video and manual labels are evaluation material,
never production inputs.

**Status:** whole-archive offline analysis is available. Online on the saved model
and acceptance of changing cycles/regimes are in progress. Signal hardware and
colors remain estimates; trajectories can leave them ambiguous.

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

The model stores observed approaches, candidate head configurations, working phase
count K, recurring signature groups, duration statistics and provenance. Three- and
four-approach schematic views are supported. Sources retain separate clocks and
track namespaces; gaps are not joined into an invented history.

Results persist in `logs/intersection_projects/<model_id>/`. Reopening a completed
model does not fit it again. Model download is structural, not yet a portable bundle
of the original upload and players; retain the local project folder for playback.
Interrupted unfinished jobs do not yet resume automatically. Raw datasets, virtual
environments and runtime logs are excluded from Git.

## Validation and limits

The measured offline component processed219 real sources. K matched68/72 synthetic
development cases and24/24 reserved cases; phase-state error was4.01% and2.85%.
A fresh visible-head video block matched8/9 switches within2s, subject to documented
clock assumptions. These are conditional results, not universal physical accuracy.

The product workflow was checked on2 complete real archives/9 sessions, all9 saved
players, desktop/mobile Edge, and8 T-intersection structural scenarios. Full suite:
1449 tests PASS. [Workflow evidence](docs/INTERSECTION_PROJECT_RESULTS_20261019.md),
[accuracy evidence](docs/ACCURACY_RECOVERY_RESULTS_20261019.md).

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

[Documentation](docs/README.md) ? [Roadmap](ROADMAP.md) ? [Status](docs/PROJECT_STATUS.md).
The [previous README](docs/history/README_PRE_CONSOLIDATION_20261019.md) is archived;
its dated findings do not override current instructions. Research evidence is
retained, including rejected experiments and their limitations.

## Developer checks

```sh
python -m compileall -q app scripts tests
python -m pytest -q
python -m scripts.e2e_smoke
```

CI also checks a Git LFS Lenina fixture; fetch LFS files for that regression.
Legacy annotation and explicit-profile tools remain separate evaluation utilities.
