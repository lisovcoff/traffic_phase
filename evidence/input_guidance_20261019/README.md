# Metadata input guidance, 2026-10-19

The reported file `feed_manifest.json` contains source/time/count metadata, not
vehicle trajectories. Uploading it cannot produce an intersection model.

The worker now distinguishes metadata-only uploads with NON_TRAJECTORY_INPUT.
The panel explains how to choose original trajectory JSON/ZIP or replay JSONL;
its fallback also handles previously stored metadata-only failures. Corrupted
JSON retains a distinct source failure. Mixed metadata/trajectory ZIP behavior
and the inference algorithm are unchanged.

Validation:24 affected pytest tests PASS (one existing deprecation warning and
one local pytest-cache permission warning); `node --check panel.js` and
`git diff --check` PASS. `browser_v2/receipt.json` records actual worker and Edge
upload, readable message, retry controls, reload and mobile width checks.

The first ad-hoc browser attempt timed out45s: a disk-backed Playwright file
was forwarded through ASGI routing with an empty file body. The product correctly
rejected that empty input. The reproducible QA uses in-memory file attachment,
asserts217 bytes reached the worker, and passes. No model evaluation was run.

Reproduce browser check:

```sh
python -m scripts.qa_input_guidance --out evidence/input_guidance_new
```

It requires the local Playwright environment used by the other QA scripts.
