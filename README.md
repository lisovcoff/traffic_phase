# traffic_phase

Backend prototype for estimating traffic-light phase structure from vehicle trajectories when the signal itself is not directly visible.

## Current MVP

The current baseline:

- keeps trajectories with `category_name == "car"`;
- uses `millis` as the time axis;
- groups trajectories by `zone_in -> zone_out` movement;
- extracts delayed departures from `stay_duration_millis`;
- estimates a dominant traffic cycle with autocorrelation;
- folds movement activity into the estimated cycle;
- detects candidate phase-transition points;
- exposes the analysis through FastAPI.

The repository is an inference baseline. It is not a validated traffic-light classifier yet: labelled signal-phase ground truth would be required to report classification accuracy.

## Project structure

```text
app/
  api/       HTTP routes
  core/      trajectory analysis logic
  schemas/   API/data models
  main.py    FastAPI application
scripts/     local utility scripts
tests/       automated tests
```

## Run locally

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
# .venv\\Scripts\\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Swagger UI: `http://127.0.0.1:8000/docs`

## Docker

```bash
docker build -t traffic-phase .
docker run --rm -p 8000:8000 traffic-phase
```

## Tests

```bash
pytest -q
```

## Input data

The analyzer follows the supplied trajectory format: vehicle id, `millis`, `zone_in`, `zone_out`, category, detections, and optional motion/waiting parameters. The project currently uses the supplied intersection trajectory archives as development data.
