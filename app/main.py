"""API HTTP del worker (brief §7): /health y /analyze (auth + BackgroundTasks)."""
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.pipeline.runner import process_job

app = FastAPI(title="Design Analyst Worker")


class AnalyzeRequest(BaseModel):
    job_id: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", status_code=202)
def analyze(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    x_worker_secret: str | None = Header(default=None),
) -> dict:
    settings = get_settings()
    if x_worker_secret != settings.worker_secret:
        raise HTTPException(status_code=401, detail="secreto inválido")
    background_tasks.add_task(process_job, req.job_id, settings)
    return {"accepted": True, "job_id": req.job_id}
