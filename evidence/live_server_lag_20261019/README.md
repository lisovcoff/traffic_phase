# Running-server online replay inspection, 2026-10-19

The reported online stall was checked in isolated headless Edge against the
actual HTTP server, without TestClient routing. The original running process
served the older panel. Its61-packet replay completed with no JavaScript errors;
individual POSTs took up to956ms. No indefinite browser stall was reproduced.

Two observable UI/timing defects were fixed:

- Polling overwrote the EOF message, making a finished finite feed look live
  while the last frame stayed still. A separate status now reports waiting,
  processing, completion, empty input, interruption and errors.
- Replay waited a full packet interval after each request completed, accumulating
  processing delays. The clock now schedules against deadlines, accounts for
  time already spent, and reanchors when speed changes. Sequential ingestion and
  backpressure remain; it does not promise speed beyond server throughput.

Online JSON requests now have a30s timeout and retain accepted packets on failure.
The inference engine, phase fit, journal and accuracy claims are unchanged.

Validation:36 affected pytest tests PASS; Node syntax and diff checks PASS.
The clock regression includes variable processing delays, lag and speed changes.
`fixed_8018/receipt.json` records61 actual packets in15.69s at maximum speed and
an actual10s prefix in11.69s at x1 including stream/view preparation. Completion
survives polling. History seek, return live, reload and mobile width checks PASS.
`fixed_8017/` repeats these checks on the ordinary user-facing port.

Reproduce with the local model and packets retained in this workspace:

```sh
python -m scripts.qa_running_online --base-url http://127.0.0.1:8017 --out evidence/online_check_new
```

Raw replay inputs stay local. Screenshots and HTTP timing receipts contain
derived output only. The initial inspection is in `initial/`.
