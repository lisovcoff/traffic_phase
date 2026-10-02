from fastapi import FastAPI

from app.api.routes import router as phase_router
from app.api.v9 import router as v9_router
from app.api.visualization import router as visualization_router
from app.api.realtime import router as realtime_router
from app.api.realtime_simulation import router as realtime_simulation_router

app = FastAPI(
    title="Traffic Phase Estimator",
    version="0.12.0",
    description="Estimate recurring traffic-light phase structure from vehicle trajectories.",
)

app.include_router(phase_router)
# V9 is the anonymous, direction-agnostic research path.
app.include_router(v9_router)
app.include_router(visualization_router)
app.include_router(realtime_router)
app.include_router(realtime_simulation_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "traffic-phase",
        "version": "0.12.0",
        "visualization": "/visualization",
        "v9": "/api/v1/v9/info",
    }
