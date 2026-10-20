# Release audit — 21 October 2026

Version 0.13.0 is ready for local demonstration and code submission within the
published measurement scope. Installation and navigation issues found in the
audit are corrected. No new physical-signal accuracy result is claimed.

## Coverage

All 553 Python files were parsed and checked for undefined names and invalid
local bindings. Manual review focused on uploads/parsing, the selected estimator,
transition semantics, online validation/recovery, rendering, installation and
measurement provenance. Historical runners were included in static checks;
their private recordings remain outside Git.

| Check | Result |
|---|---|
| Python parsing and Ruff undefined-name checks | No findings |
| Dependencies, pip-audit | No known advisories; no skipped packages |
| Installed dependency compatibility, pip check | Passed |
| Heuristic credential-pattern scan | No matches |
| Full local test run | 1,578 passed, 4 skipped |
| Subsequent targeted checks, including statistics consistency | 50 passed |
| End-to-end smoke | Passed |
| Actual Edge/HTTP player | 120 real packets, 88 recordings, seek/resume/reload and mobile width passed |
| New upload and bookmark restoration | Passed in the actual browser |

The full run was collected before the last statistics-consistency test was added;
that test passed in the targeted run. Five existing warnings remain: TestClient
deprecation and empty-column numerical warnings in four phase-discovery tests.
Docker configuration was reviewed; a container and macOS runtime were not executed.

Bandit has no high-severity findings after marking Git-object SHA1 as non-security
hashing. Its medium findings were reviewed: private application-owned pickle
stores, source-controlled experiment code, loopback QA calls and SUMO-generated
XML. Uploaded inputs cannot supply Python code or pickle checkpoints. The checked
deployment is local; public multi-user hosting is outside this acceptance.

## Short colors

The decoder uses uncalibrated timing priors for yellow and red + yellow. At
one-second resolution, a boundary shift occupies a large fraction of a two- or
three-second state. Vehicle movement also follows the light with an unknown
reaction delay. These timings are estimates, not lamp observations.

Aggregate SUMO recall is **22.64% for yellow** and **56.51% for red + yellow**.
Both weaknesses are visible in the READMEs and chart. The benchmark's strict
no-regression gate remains failed; its result has not been relabelled.

The safe change is presentation: both short states now carry an explicit
timing-estimate annotation. The tooltip shows existing model support without
calling it a calibrated color probability. No color, confidence, duration law,
hypothesis weight or issued journal response was adjusted.

All 131 core/experimental modules have the same abstract syntax trees as baseline
`0568b95`; the only source edit there splits a semicolon-separated assignment.
Actual browser checks confirm unchanged head payloads, rejection of stale live
packets and working historical seek. This addresses false precision in the UI;
it **does not eliminate** the short-color accuracy error. Further timing changes
need their own independent evaluation.

## Corrections

- New analysis replaces stale project/stream parameters in the URL. Reloading
  an old bookmark after a new upload restores the newly selected model.
- Offline viewer caches use a new filename version; old cached files are retained.
- The tested certifi pin is now 2026.10.19; installers upgrade pip to at least
  26.2. Local checked pip is 26.2.2. These address the
  [certifi advisory](https://github.com/advisories/GHSA-6q48-6c7w-9gw2) and
  [pip path-handling advisory](https://github.com/pypa/advisory-database/blob/main/vulns/pip/PYSEC-2026-3721.yaml).
- CI and container installation use the tested Python 3.12 manifest. CI also
  checks undefined names before tests.

## Statistics

The pandas/Matplotlib reporting script stays under ignored `.web_runtime/`.
Published outputs are the chart, an actual real-packet player screenshot and
[statistics.json](statistics.json). Counts come from [the frozen v8 receipt](causal_v8.json),
whose SHA256 is recorded in the statistics. Tests verify totals, color denominators
and the failed-gate scope. Neither presentation nor this audit is a new holdout.
The visible-N video score remains separate from six-archive all-head accuracy.

[Machine-readable audit](release_audit.json) · [Project status](../docs/PROJECT_STATUS.md)
