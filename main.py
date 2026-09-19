from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from threading import Lock, Thread
from datetime import datetime, timezone
import os
import uuid

from sheets import GoogleSheetsSync
from cloud_browser import session_status

load_dotenv()

app = FastAPI(title="Blinkit Report Automation", version="1.0.0")
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

sync = GoogleSheetsSync(
    spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID", "1SMMFfqWqWalOys5swqpxk_jIz_l4-kJPU_9V9Ix9OKQ"),
    protected_sheet_id=int(os.getenv("PROTECTED_MAIN_SHEET_ID", "695987561")),
)

job_lock = Lock()
jobs: dict[str, dict] = {}


def create_job(kind: str) -> str:
    job_id = uuid.uuid4().hex
    jobs[job_id] = {
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "message": "Queued",
        "started_at": None,
        "finished_at": None,
        "results": [],
        "error": None,
    }
    return job_id


def finish_job(job_id: str, status: str, message: str, results=None, error=None):
    job = jobs[job_id]
    job["status"] = status
    job["message"] = message
    job["finished_at"] = datetime.now(timezone.utc).isoformat()
    if results is not None:
        job["results"] = results
    if error:
        job["error"] = error


def download_worker(job_id: str):
    from blinkit_automation import run
    if not job_lock.acquire(blocking=False):
        finish_job(job_id, "failed", "Another automation job is already running.", error="JOB_BUSY")
        return
    jobs[job_id]["status"] = "running"
    jobs[job_id]["message"] = "Downloading Blinkit reports..."
    jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        results = run()
        finish_job(job_id, "completed", "Blinkit report download completed.", results)
    except Exception as exc:
        finish_job(job_id, "failed", "Blinkit report download failed.", error=str(exc))
    finally:
        job_lock.release()


def sheets_worker(job_id: str):
    if not job_lock.acquire(blocking=False):
        finish_job(job_id, "failed", "Another automation job is already running.", error="JOB_BUSY")
        return
    jobs[job_id]["status"] = "running"
    jobs[job_id]["message"] = "Syncing reports to Google Sheets and Drive..."
    jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        result = sync.sync_report_directory()
        finish_job(job_id, "completed", "Google Sheets and Drive sync completed.", result.get("results", []))
    except Exception as exc:
        finish_job(job_id, "failed", "Google Sheets sync failed.", error=str(exc))
    finally:
        job_lock.release()


@app.get("/")
def root():
    return FileResponse("frontend/index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "google": sync.status(),
        "blinkit_browser": session_status(),
        "active_jobs": sum(j["status"] == "running" for j in jobs.values()),
    }


@app.get("/auth/google")
def google_auth():
    try:
        return RedirectResponse(sync.authorization_url())
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/auth/google/callback")
def google_callback(code: str):
    try:
        sync.exchange_code(code)
        return RedirectResponse("/")
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.get("/sheets/status")
def sheets_status():
    return sync.status()


@app.post("/blinkit/download")
def download_reports():
    job_id = create_job("blinkit_download")
    Thread(target=download_worker, args=(job_id,), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@app.post("/sheets/upload")
def upload_reports():
    job_id = create_job("sheets_sync")
    Thread(target=sheets_worker, args=(job_id,), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/blinkit/session")
def blinkit_session():
    return session_status()
