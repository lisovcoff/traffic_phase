# Traffic Phase

**English** · [Русский](README.ru.md)

[![Tests](https://github.com/lisovcoff/traffic_phase/actions/workflows/tests.yml/badge.svg)](https://github.com/lisovcoff/traffic_phase/actions/workflows/tests.yml)

Estimate traffic-light phases from vehicle trajectories when the lights are out
of view. Upload a JSON or ZIP for one intersection, then inspect cars and estimated
signals in a shared offline/online player.

The Python application learns observed approaches, phase count and section
hypotheses from the uploaded recording. Video and lamp labels are evaluation
inputs only; they never enter the estimator.

![Player with recorded cars and estimated signals](results/figures/player.png)

## Run

Python 3.12. On Windows:

```bat
INSTALL.cmd
START_WEB.cmd
```

Open **http://127.0.0.1:8017/visualization**, choose the original JSON/ZIP and click
**Анализировать**. Use one intersection per upload. The player supports recording
selection, playback, speed, seeking and exact time selection.

Linux/macOS:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8017
```

For online operation, open a finished model and select **Онлайн**. Send current
packets to the POST endpoint shown in the panel, or replay a per-second JSONL.
An archive can be converted without changing the input:

```sh
python -m scripts.archive_online_packets data/intersection.zip --spool .web_runtime/feed.sqlite3 --output .web_runtime/feed.jsonl
```

Use new output paths each time. A manifest/report JSON is not a trajectory feed.
Models and accepted history live in `logs/intersection_projects/`; keep that
folder when moving an existing analysis. See the [guide](GUIDE.md) for the packet
contract, saved-model updates and checks.

## Method and limits

Offline processing separates recordings and clocks, extracts movement evidence,
discovers recurring configurations and learns queue geometry and durations.
Online operation retains that structure and updates joint color, phase-age and
duration hypotheses from current and past movement. Competing duration programs
handle isolated extensions and recurring period changes. An empty queue does not
prove RED; `?` means insufficient evidence or startup synchronization.

Colors and physical sections are estimates. Short transitions are explicitly
marked as timing estimates. Universal 95% accuracy across the six real archives
is not established.

| Measurement | Result | Scope |
|---|---:|---|
| Exact-second accuracy | **93.51%** | Eight SUMO scenarios; 20,582/22,010 head-seconds |
| GREEN / RED recall | **99.37% / 94.66%** | Same controlled scenarios |
| YELLOW / RED_YELLOW recall | **22.64% / 56.51%** | Short colors remain weak |
| Known real visible-N window | **148/153 = 96.73%** | GREEN/YELLOW only, conditional clock |

False GREEN decreases overall from 920 to 666 head-seconds, but one period-change
case worsens and T-junction RED_YELLOW recall regresses. The strict no-regression
gate remains failed. [Measurements, charts and coverage](results/README.md).

## Code

- `app/api/`: upload, saved models, online packets and the common panel.
- `app/core/`: trajectory processing, offline discovery, geometry and persistence.
- `app/timing/`: causal color/age estimates and duration adaptation.
- `scripts/`: worker, archive conversion, model migration, packaging and validation.
- `tests/`: tests for retained application functionality.
- `results/`: compact measurements and figures; input data and generated runs stay local.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check app scripts tests --select F821,F822,F823
```

This is a local application. Public multi-user hosting and authentication are
outside the checked deployment scope.
