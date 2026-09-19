from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
import os

from sheets import GoogleSheetsSync

load_dotenv()

app = FastAPI(title="Blinkit Report Automation", version="0.1.0")
sync = GoogleSheetsSync(
    spreadsheet_id=os.getenv("GOOGLE_SPREADSHEET_ID", "1SMMFfqWqWalOys5swqpxk_jIz_l4-kJPU_9V9Ix9OKQ"),
    protected_sheet_id=int(os.getenv("PROTECTED_MAIN_SHEET_ID", "695987561")),
)

@app.get("/")
def root():
    return {
        "service": "Blinkit Report Automation",
        "status": "ok",
        "google_sheets": sync.status(),
    }

@app.get("/auth/google")
def google_auth():
    url = sync.authorization_url()
    if not url:
        raise HTTPException(500, "Google OAuth is not configured yet.")
    return RedirectResponse(url)

@app.get("/auth/google/callback")
def google_callback(code: str):
    sync.exchange_code(code)
    return {"status": "authorized", "message": "Google Sheets authorization completed."}

@app.get("/sheets/status")
def sheets_status():
    return sync.status()

@app.post("/sheets/upload")
def upload_reports():
    result = sync.sync_report_directory()
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result
