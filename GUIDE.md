# Traffic Phase guide

**English** · [Русский](GUIDE.ru.md)

## Offline and saved projects

Run `INSTALL.cmd`, then `START_WEB.cmd` on Windows. Open
http://127.0.0.1:8017/visualization. `START_WEB.cmd --check` checks the installation.

Upload the original trajectory JSON/ZIP of one intersection. Wait for READY or
PARTIAL; inspect source errors for partial results. Choose a recording and time.
Do not upload an analysis report, model JSON or feed manifest as raw input.
Interrupted offline jobs do not currently resume automatically.

Models, source recordings, players and journals live in
`logs/intersection_projects/<model_id>/`. Keep the entire folder when moving
an analysis. Downloading model JSON alone is not a full export.

## Online packets

Open a completed model, choose **Онлайн**, then use the endpoint displayed in
the panel. Alternatively, choose a chronological JSONL: one packet per line.
A finite replay stops at its final packet; continuing needs more observations.

```json
{
  "sequence": 0,
  "timestamp_ms": 1800000000000,
  "vehicles": [{
    "id": "car-1",
    "zone_in": "N",
    "detections": [{
      "millis": 1800000000000,
      "centroid_x": 0.5,
      "centroid_y": 0.2,
      "zone": "N"
    }]
  }]
}
```

Use Unix milliseconds. Only observations available at `timestamp_ms` are allowed;
never include future exit information (`zone_out`). Detections may also include
`speed`, `lat` and `lng`. Supply the same coordinate convention used offline.
The running server's **/docs** contains field types, limits and endpoint schemas.

Identical duplicate packets are idempotent. Conflicting sequences and future
detections are rejected. Empty `vehicles` is a heartbeat, not evidence of RED.
Startup `?` means synchronization or insufficient evidence. History and live
view remain separate; accepted responses survive reload and restart.

The offline structure fixes approaches, K and sections. Online observations
update state and duration hypotheses. They cannot identify the cause of an
unusual interval, such as an emergency vehicle, solely from its duration.

## Updating an older model

Analyze its original offline archive again, or create a separate enriched copy:

```sh
python -m scripts.enrich_intersection_model logs/intersection_projects/OLD_ID --output logs/intersection_projects/NEW_32_HEX_ID
```

Use a new 32-character hexadecimal ID. Old models and journals are preserved;
v7 history retains v7 and new models with learned queue references use v8.

## Checks and source packaging

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m scripts.verify_delivery --project MODEL_ID --packets real_packets.jsonl --output new_check.json
python -m scripts.build_delivery --output new_source.zip
```

The HTTP check needs a running server, a finished model and packets. It creates
a separate QA stream and checks players, duplicate/future validation and seeking.
It does not measure lamp accuracy. Packaging requires a clean committed tree,
includes tracked files and verifies hashes; choose a new output filename.

Optional browser checks use `scripts.qa_intersection_delivery` and Playwright
with installed Edge. Optional independent simulation uses `eclipse-sumo==1.28.0`:

```sh
python -m scripts.validate_causal_v8 --sumo-home PATH_TO_SUMO --output .web_runtime/new_validation --require-acceptance
```

The strict accuracy gate currently fails; `--require-acceptance` exits with 2.
[Results and limitations](results/README.md) are separate from software checks.
