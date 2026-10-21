# Traffic Phase guide

**English** · [Русский](GUIDE.ru.md)

The project contains the Python application, source, tests and compact
validation results. It is a working research prototype. Physical signal
accuracy on all six archives is not independently established. New offline
models with queue references use the integrated v8 estimator. Older models
without that geometry and existing v7 journals retain their original engine.

## Start

Use Python 3.12. On Windows, run `INSTALL.cmd` once, then `START_WEB.cmd`.
Open **http://127.0.0.1:8017/visualization**. Stop an earlier server before
starting another on the same port. `START_WEB.cmd --check` checks the environment.
The newly installed `.venv` takes precedence over an older local runtime.

1. Select an original trajectory JSON or ZIP for one intersection and click
   **Анализировать**. Wait for READY/PARTIAL; inspect any failed source entries.
2. Choose a recording. Check cars, estimated heads/sections, play/pause, speed
   and timeline/time selection. Approach/K/section hypotheses are inferred.
3. Switch to **Онлайн**. Select a chronological per-second JSONL in the online
   input, or POST current observations to the endpoint displayed in the panel.
   See the [packet contract](docs/API.md). A manifest/report JSON is not a feed.
4. Seek in accepted history, return to live output, and reopen the page to
   restore the saved model/stream. A finite replay stops at its final packet.

Saved models, sessions, players and journals live in `logs/intersection_projects/`.
They are local assets, excluded from the source ZIP. Keep that folder when
moving an existing analysis. Downloading only model JSON is not a full project
export. On a clean computer, upload the original input to build a new project.

## Verify

Convert a second recording/archive to an online replay without manual packet
editing (use new output paths each time):

```sh
python -m scripts.archive_online_packets intersection.zip --spool .web_runtime/feed.sqlite3 --output .web_runtime/real_packets.jsonl
```

Select the resulting JSONL in the online control. The SQLite spool is retained
locally; neither conversion nor replay changes the source archive.

```sh
python -m pytest -q
python -m scripts.verify_delivery --project MODEL_ID --packets real_packets.jsonl --output new_check.json
python -m scripts.build_delivery --verify traffic_phase_source.zip
```

The HTTP check requires a running server and a completed model. It creates a
separate saved QA stream and checks offline/online player responses, packet
acceptance, duplicate/conflict/future rejection and exact historical seeking.
It does not measure lamp accuracy or replace visual review.

## What the measurements support

The [validation index](results/README.md) separates physical-head labels,
synthetic controls, timing errors and functional checks. The latest
[delivery check](results/delivery_readiness.json) records this delivery's scope.
Five known experimental SUMO controls exceed 95%; that is not the production
application's accuracy on six real archives. The visible-N score is limited
to known GREEN/YELLOW intervals with a conditional clock mapping.

The latest [v8 report](results/causal_v8.md) supersedes those experimental
measurements: eight fresh-at-freeze controls reach 93.51% versus 89.57%, and the
known real GREEN onset delay falls from 3.42s to 1.42s. Strict acceptance still
fails: one period-change false-GREEN count and T-junction RED_YELLOW regress.
Enthusiasts JSON/video association
and full all-head reference histories remain unresolved. Empty demand,
obstructions and permissive turns can make colors/sections ambiguous.
The [current status](docs/PROJECT_STATUS.md) is the acceptance record; tests and
a verified ZIP do not establish that every inferred signal is correct.

To update a saved model without refitting or overwriting its streams, create a
new folder from its own original offline input:

```sh
python -m scripts.enrich_intersection_model logs/intersection_projects/OLD_ID --output logs/intersection_projects/NEW_32_HEX_ID
```

Alternatively, analyze the original archive again. Queue geometry is now learned
automatically. No online recording, video, lamp labels or manually supplied plan
are needed. At stream startup, `?` means insufficient movement evidence; allow
time to synchronize. Empty traffic alone cannot identify a physical color.
