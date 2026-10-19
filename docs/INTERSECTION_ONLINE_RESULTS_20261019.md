# Causal online integration / Онлайн на сохранённой модели

Implemented19.10 after the user's explicit instruction to publish checked work
to main. Earlier offline milestone:3134d6b. Full physical-accuracy acceptance is
still open. Paused2D.1 remains FAIL/default-off; it was not resumed.

## Usage / Использование

`START_WEB.cmd` → `/visualization` → analyze an intersection → **Онлайн**.
The page shows the packet endpoint. Select JSONL to replay a test stream, one
packet per line; choose a speed. The same schematic renders live vehicles and
estimated heads. A date/time request shows the original issued response at or
before that instant. **Прямой эфир** resumes current data. Reload restores the
stream. Unknown intervals and gaps remain explicit; old history is not rewritten.

Локальное демо: `evidence/intersection_online_20261019/browser_v7/real_packets.jsonl`.
Файл содержит реальные детекции и не публикуется в Git; сохранён манифест источника.
Готовая модель с обученными возрастами старта:
http://127.0.0.1:8017/visualization?project=1eada5fee84648b389dd6bfded3ad153

| Method | Path relative to `/api/v1/intersections/{model_id}` | Purpose |
|---|---|---|
| POST | `/online` | Create a stream from the saved offline model |
| POST | `/online/{stream_id}/packets` | Submit a current packet |
| GET | `/online/{stream_id}` | Latest original response |
| GET | `/online/{stream_id}/history?after=-1&limit=1000` | Paginated issuance history |
| GET | `/online/{stream_id}/at?timestamp_ms=...` | Original response at/before a time |
| GET | `/online/{stream_id}/viewer` | Shared spatial renderer |

Example packet (current observations only):

```json
{"sequence":0,"timestamp_ms":1760000000000,"vehicles":[{"id":"42","zone_in":"N","detections":[{"millis":1760000000000,"centroid_x":0.4,"centroid_y":0.8,"zone":"N","speed":0,"lat":55.16,"lng":61.39}]}]}
```

All detections must have millis≤packet time. IDs/origins remain stable.
Future `zone_out` is forbidden. Empty vehicles is a heartbeat, not red evidence.
Optional lat/lng enable motion inference when vendor speed is unreliable.
The saved reference camera projection is assumed for live centroid coordinates;
automatic matching of multiple camera coordinate systems is not certified.

## Model and persistence

The phase/age filter uses exclusively offline K, head hypotheses, movement
probabilities, observed transitions and duration distributions. It adapts current
phase age and selects among known regimes. Offline fitted restart-age histograms
provide timing information without video, calibrated lamp labels or absolute old
recording clocks. Geographic/raw motion is processed from prefixes only. Multiple
stop/restart episodes are supported; an early queue creep does not suppress the
later departure. Confidence is an uncalibrated model posterior.

Accepted packets/responses are committed to SQLite atomically. A duplicate
sequence with identical content returns its original response; conflicting or
out-of-order input is rejected. Recovery replays the journal against the frozen
model fingerprint and engine version. Changed versions require a new stream;
old history is retained. Cache memory is bounded; histories are paginated.
Packet body budget16MiB; up to2000 retained tracks and128 points per track.

## Verification and measured limits

- `browser_v7/receipt.json`: actual panel,61 real per-second packets, same car/head
  renderer, history seek, live resume, reload, archive/live switch, mobile width390;
  no JavaScript errors. Video/profile/future trajectory metadata absent.
- Prefix/future rejection, unchanged historical clock, duplicate/conflict handling,
  journal restoration, link gaps,1Hz motion, stale speed and repeated restarts are
  covered by tests. Full run receipts: `checks/full_pytest_v6*`.
  Final full run: **1462 PASS**,5 existing warnings,261.15s. Compilation,
  application launch check, end-to-end smoke and staged whitespace checks PASS.
- `diagnostic_v2/`: two disjoint-demand synthetic streams,1801 packets each,
  two offline-learned duration regimes and a duration change. Initial color
  accuracy including UNKNOWN:83.16%/85.81% after180s synchronization.
- `geographic_comparison/`: final development replay reaches89.11%/87.63%,
  known coverage98.64%/94.54%, conditional known accuracy90.34%/92.69%.
  These are two revealed development cases, not universal or independent accuracy.
- `real_clock_geographic/`: already-revealed visible N-main window2100–2400s,
 120s causal warmup; GREEN3/3 within2s, mean matched error0.92s. Four predicted
 green onsets for3 reference onsets (precision75%). YELLOW/RED each2/3 within2s;
 at5s all3 match, with extra onsets. Same-recording offline model, conditional
 video/JSON clock; **not independent physical validation**. Video/clock corrections
 are evaluator-only. The first raw-speed-only replay lagged about9s; retained.
- `projection_regression/`:96 already-revealed frozen numerical fits re-projected
 without refit. Working K:52→54/72 and15→18/24. Main-head error6.79→5.99% and
9.18→7.47%; no regressed cases. Latent K remains68/72 and24/24; it is a different
measure from working physical configurations. Repair is limited to an inherited
empty phase with a selective reciprocal turn pair and unsupported inherited greens.

Earlier failed QA and test runs are retained. They found a srcdoc origin error in
history messaging, a test harness date-format error, a Git LFS pointer where small
JSON was expected, and checkout newline changes to sealed sources. Small plans are
now ordinary JSON, CI fetches the large LFS fixture, and sealed source bytes are
protected. A concurrent-load legacy latency failure is retained; the threshold
was not weakened. The final suite runs without parallel benchmark load.

## Remaining acceptance / Что остаётся

Universal working K/hardware and adaptive regime accuracy remain unaccepted.
Need new separated real sessions, reliable multi-camera identity/geometry, rare
flow/permissive turns, unknown regimes, long extensions, false-onset reduction,
calibrated uncertainty and longer failure/load testing. The system cannot infer
an emergency/motorcade cause from indistinguishable traffic evidence. Empty
approaches and unobserved arrows can remain ambiguous. Old unfinished offline
jobs still do not auto-resume. This delivery adds the functional online workflow;
it does not prove the user's maximum-accuracy objective fully achieved.
