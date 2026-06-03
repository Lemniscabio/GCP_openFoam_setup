from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.routes_cases import router as cases_router
from backend.routes_jobs import router as jobs_router

app = FastAPI(title="OpenFOAM Batch")
app.include_router(cases_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")


@app.get("/health")
def health():
    # NB: Cloud Run's edge reserves the exact path /healthz (never reaches the
    # container), so the health route is /health.
    return {"ok": True}


_static = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
