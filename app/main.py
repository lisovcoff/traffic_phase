from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.intersection_panel import PAGE
from app.core.upload_limits import UploadLimitMiddleware
from app.api.intersection_projects import router as intersection_projects_router
from app.api.intersection_online import router as intersection_online_router

app = FastAPI(
    title="Traffic Phase Estimator",
    version="0.14.0",
    description="Estimate recurring traffic-light phase structure from vehicle trajectories.",
)

app.include_router(intersection_projects_router)
app.include_router(intersection_online_router)
app.add_middleware(UploadLimitMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "traffic-phase",
        "version": "0.14.0",
        "visualization": "/visualization",
    }


@app.get("/visualization", response_class=HTMLResponse)
def visualization() -> str:
    return PAGE
