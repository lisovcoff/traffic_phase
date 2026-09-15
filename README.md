# traffic_phase

Traffic-light phase estimation from vehicle trajectories when the signal is not directly visible.

## MVP 0.2

Current baseline:

- filters trajectories to `car`;
- groups vehicles by `zone_in -> zone_out`;
- extracts delayed departures from `stay_duration_millis`;
- estimates the dominant traffic cycle with autocorrelation;
- folds movement activity into the candidate cycle;
- detects candidate phase-transition points;
- exposes the analysis through a FastAPI endpoint.

Reference analysis on the supplied Lenina–Sverdlovsky dataset found a strong ~100 s periodicity (`autocorrelation=0.765`) across 10,054 car trajectories and candidate transition points around 31 s, 49 s and 77 s within the cycle.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Swagger: `http://127.0.0.1:8000/docs`

## API

`GET /health`

`POST /api/v1/phase/analyze` — upload a trajectory JSON file.

> This is an inference baseline, not a validated ground-truth classifier. Accuracy requires labelled traffic-light phase data.
