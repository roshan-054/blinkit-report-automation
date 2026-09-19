from fastapi import FastAPI,HTTPException
from fastapi.responses import RedirectResponse,FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
from fastapi import BackgroundTasks
from threading import Lock
from sheets import GoogleSheetsSync
from cloud_browser import session_status
load_dotenv()
app=FastAPI(title="Blinkit Report Automation",version="0.2.0")
run_lock = Lock()

sync=GoogleSheetsSync(spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID","1SMMFfqWqWalOys5swqpxk_jIz_l4-kJPU_9V9Ix9OKQ"),protected_sheet_id=int(os.getenv("PROTECTED_MAIN_SHEET_ID","695987561")))
app.mount("/frontend",StaticFiles(directory="frontend"),name="frontend")
@app.get("/")
def root(): return FileResponse("frontend/index.html")
@app.get("/health")
def health(): return {"status":"ok","google_sheets":sync.status()}
@app.get("/auth/google")
def google_auth():
    try:return RedirectResponse(sync.authorization_url())
    except Exception as e:raise HTTPException(500,str(e))
@app.get("/auth/google/callback")
def google_callback(code:str):
    try:sync.exchange_code(code);return {"status":"authorized","message":"Google Sheets authorization completed."}
    except Exception as e:raise HTTPException(400,str(e))
@app.get("/sheets/status")
def sheets_status():return sync.status()
@app.post("/sheets/upload")
def upload_reports(background_tasks: BackgroundTasks):
    background_tasks.add_task(sync.sync_report_directory)
    return {"status": "queued", "message": "Google Sheets sync job queued."}

@app.get("/jobs")
def jobs():
    return {"status": "background_tasks_enabled"}
@app.post("/blinkit/download")
def download_reports(background_tasks: BackgroundTasks):
    from blinkit_automation import run
    if not run_lock.acquire(blocking=False):
        raise HTTPException(409, "A Blinkit report job is already running.")
    run_lock.release()
    background_tasks.add_task(_run_download)
    return {"status": "queued", "message": "Blinkit report job queued."}


def _run_download():
    from blinkit_automation import run
    if not run_lock.acquire(blocking=False):
        return
    try:
        run()
    finally:
        run_lock.release()

@app.get("/blinkit/session")
def blinkit_session():
    return session_status()
