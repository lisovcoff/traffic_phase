# Inputs and online usage

Start the application and open `/visualization` for the common offline/online
panel. `/docs` exposes the generated OpenAPI contract and endpoint details.

## Offline

Upload the original trajectory JSON or a ZIP containing recordings of **one**
intersection. All supported sources and sessions are processed automatically.
Do not upload report JSON or `feed_manifest.json`. Individual source failures
remain visible when a model has partial results.

The model and its local playback assets are saved in
`logs/intersection_projects/<model_id>/`. Reopening a finished model does not
retrain it. Keep the project folder: downloading the structural model alone
does not export the source recording and every player asset. Interrupted offline
jobs do not yet resume automatically.

## Online

Open a completed offline model, choose **Online**, and use the POST endpoint
displayed in the panel. Alternatively, select a JSONL replay: one packet per line.
The offline upload box does not accept JSONL replay files.

Each packet contains `sequence`, `timestamp_ms` and `vehicles`. Each vehicle has
`id`, `zone_in` and current `detections`; detections contain `millis`,
`centroid_x`, `centroid_y`, `zone` and optional `speed`, `lat`, `lng`.
Use the exact current schema from `/docs` for an integration.

Only observations available by the packet timestamp are permitted. Future
`zone_out` is forbidden. Empty vehicle arrays are valid heartbeats, not evidence
of a red light. Duplicate identical packets are idempotent; conflicting packet
sequences and future detections are rejected.

The player supports original issuance history, timestamp seeking and returning
to the live view. Packets/responses persist in SQLite and restore after restart.
A JSONL file is finite: after its final packet the player shows completion and
the last observation. More movement requires more packets.
