from fastapi import FastAPI

from app.api.routes import router as phase_router

app = FastAPI(
    title="Traffic Phase Estimator",
    version="0.2.0",
    description="Estimate recurring traffic-light phase structure from vehicle trajectories.",
)

app.include_router(phase_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "traffic-phase", "version": "0.2.0"}
