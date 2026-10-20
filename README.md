# Traffic Phase

**English** · [Русский](README.ru.md)

Infer traffic-light phases from vehicle trajectories when the lights are not
directly visible. A Python/FastAPI application analyzes an intersection's JSON
or ZIP recordings, learns recurring movement structure, and displays estimated
signals and vehicles in an interactive offline/online player.

**Status:** working research prototype. Automatic ingestion and causal online
replay are implemented; universal physical-signal accuracy is not established.
Video and manual lamp labels are evaluation-only inputs, never inference inputs.

## Features

- One panel for whole-archive analysis, saved models and online replay.
- Automatic observed approaches (3/4), candidate phase count K, movement groups
  and section hypotheses, without a user-provided intersection plan.
- Offline regime/duration catalogue and causal per-second online estimates
  against the learned structure.
- Vehicle animation, play/pause, speed, timeline and precise time selection.
- Persistent models, packet history, duplicate handling and online restart recovery.

Physical hardware and colors remain estimates. Empty approaches, permissive
turns and obstructed traffic can be ambiguous. Persistent new timings and unusual
extensions remain uncertain. Fresh models with learned queue geometry use v8:
joint color/age hypotheses and competing duration programs. Old models and
existing v7 journals remain compatible. Strict physical acceptance is still open.

## Quick start

For submission, migration and a repeatable functional check, see the
[delivery guide](DELIVERY.md) ([Русский](DELIVERY.ru.md)).

Python **3.12** is tested. On Windows, from the repository root:

```bat
INSTALL.cmd
START_WEB.cmd
```

Open **http://127.0.0.1:8017/visualization**. `START_WEB.cmd --check` checks imports.
Stop the previous server before restarting after an update.

On other platforms:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-tested-py312.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8017
```

## Use

1. Upload an original trajectory **JSON or ZIP for one intersection** and click
   **Analyze**. Supported members/sessions are processed automatically.
2. Open a recording and explore the vehicles and estimated signals with the player.
3. To replay current observations, open **Online** on the completed model and
   select a **JSONL** stream, or send packets to the displayed endpoint.

`feed_manifest.json` and result reports are not trajectory inputs. Upload JSONL
in the online replay control. End-of-file completes a finite replay.

Local uploads/models/players persist under `logs/intersection_projects/`.
Keep that folder for playback: model JSON download is not a complete media bundle.
See [input and API guide](docs/API.md); interactive API documentation is at `/docs`.

## Validation

The latest [v8 evaluation](results/causal_v8.md) scores **20,582/22,010 = 93.51%**
on eight separately seeded SUMO controls, versus v7's 89.57%. All eight improve
in total accuracy; the strict no-regression gate **fails** on one false-GREEN
comparison and T-junction RED_YELLOW recall. A known real N GREEN/YELLOW window
scores **148/153 = 96.73%**, and its +12s counterfactual scores 153/165 = 92.73%.
These are different denominators and do not establish universal 95% accuracy.

The real corpus includes six archives and three loose JSONs (219 sources).
On 24 reserved synthetic offline cases, K matched 24/24; this is simulation,
not video-confirmed hardware accuracy. Production online color accuracy was
86.50% on 12 synthetic streams. One narrow known N-head GREEN/YELLOW window
scored 96.08%, falling to 89.09% after a copied input's green was extended.
Those are historical v7 measurements, retained for comparison.

**95% across the six real archives is not proven.** Video coverage, clock
limitations, rejected candidates and exact denominators are documented in
[results](results/README.md). No numeric theoretical ceiling is claimed.

## Development

```sh
python -m compileall -q app scripts tests
python -m pytest -q
python -m scripts.e2e_smoke
```

The large regression fixture uses Git LFS; run `git lfs pull` if needed.
Saved private-run audits skip in a clean clone; algorithm/API tests do not
require local research artifacts. See [architecture](docs/ARCHITECTURE.md).
Clean-export verification: **1,485 passed, 34 local-evidence checks skipped**;
all 34 pass separately with the retained local runs.
[Verification receipt](results/repository_verification.json).

| Path | Purpose |
|---|---|
| `app/` | Python inference, API and browser UI generation |
| `scripts/` | CLI, generators and reproducible evaluation tools |
| `tests/`, `.github/` | Tests and CI |
| `config/` | Resources required by explicit legacy diagnostic endpoints |
| `docs/` | Architecture, input contract and current status |
| `results/` | Compact validation results and limitations |

Raw data, generated HTML players/reports, frames and research dumps are ignored
by Git and remain local. The browser interface does not change the Python
implementation language. [Current delivery status](docs/PROJECT_STATUS.md).
