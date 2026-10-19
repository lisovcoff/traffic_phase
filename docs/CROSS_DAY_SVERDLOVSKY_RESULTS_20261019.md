# Неделя офлайн → другой день онлайн / Cross-day transfer

**Data processing passed. Signal accuracy failed acceptance.** The two archives
can be used in the requested chronological order, but current color recovery
cannot be presented as correct. This result supersedes any inference of reliable
cross-day accuracy from earlier same-recording diagnostics.

- Offline:88 JSON, seven weekdays11–14/17–19 February,352,124 trajectory records,
  67,364,832 detections. Every member freshly SHA/CRC verified against sealed
  receipts. No15/16 February weekend;18 February14–16h members missing.
- Sealed motion events and numerical fits were verified by hashes and unchanged
  extraction/solver source. The current production solver rebuilt the project;
  six fresh cold predictions match schedule/clock/period/physical proposal.
  This is not88 fresh cold motion extractions. The default upload still reads raw
  sources; the private prepared-source adapter is explicitly validation-only.
- Offline signature catalogue:8 groups, periods near100/120s. Per-session K:
  K2:20, K3:54, K4:14. These groups are not certified controller programs.
  Only64/88 head hypotheses recover both N/E additional sections supplied by the
  user as evaluation truth. That description was not given to the predictor.
- Online February27: all10,844 per-second packets covering10,843s;11,604 track
  records/2,296,293 detections. ZIP observations were sorted using a disk spool;
  packets contain no future zone_out or detections. Source namespaces remain
  separate. The training model stops on February19 and is unchanged after replay.
- The first674 ordinary durable-store responses match accelerated replay byte
  for byte. Remaining validation journal writes use batches; inference still
  advances one packet at a time. This is not a full-stream HTTP latency benchmark
  or a change to production persistence. SQLite integrity/sequence checks pass.

Visible N-main video, two already revealed windows2100–2400/3300–3600s:

| Color onset | Matched within2s | Predicted onsets | Matched within5s |
|---|---:|---:|---:|
| Green |5/6|14|6/6|
| Yellow |5/6|6|6/6|
| Red |0/6|7|0/6|

Extra onsets include reappearances after UNKNOWN: they remain undesirable display
changes and are not hidden from the counts. Mode `regime_003` (K2) dominates
10,699/10,844 packets. This exposes a structure/mode selection problem; no
source-specific clock shift or threshold tuning was applied to improve the score.
Known main-head coverage near96.1% is not accuracy. Labels were revealed during
prior development; the video/JSON clock remains conditional. Only N-main has
these direct labels. Other heads and the complete week have no equivalent truth.

Actual HTTP/Edge:12 archive views cover all7 days/all8 groups; playback, time
seeking, saved online stream URL, historical seek, live resume, reload and390px
layout pass. No JavaScript errors. Cold archive views took19.6–51.4s; generated
players are cached locally. The first QA attempt raced server startup and failed
with connection refused; the successful rerun is `browser_v2/`.

38 affected tests, JavaScript syntax, compilation and diff checks pass. Source
data, partial cold work and failed attempts are retained. Existing unrelated
untracked code-export text files were not changed. Paused2D.1 remains unchanged.

Local results:

- [Offline model](http://127.0.0.1:8017/visualization?project=507ebe2af2f849189086f200d81f1359)
- [Online history](http://127.0.0.1:8017/visualization?project=507ebe2af2f849189086f200d81f1359&stream=8daf017ed3f64b5d9191286ddfabdb78)
- [Подробный отчёт по дням](../evidence/cross_day_sverdlovsky_20261019/README.ru.md)
- [Complete metrics](../evidence/cross_day_sverdlovsky_20261019/summary.json)

The online link opens the last accepted packet. Choose a date/time to inspect
history. The prepared JSONL is local at
`.web_runtime/cross_day_sverdlovsky_20261019/feb27_packets.jsonl`; the offline
upload field would train a new model if given the February27 ZIP. Use the JSONL
stream field to replay it against the earlier-week model. At x1 it takes3 hours.
