from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN_DIR = Path("tokens")
TOKEN_FILE = TOKEN_DIR / "google_sheets_token.json"
CLIENT_SECRET_FILE = Path("credentials.json")


def norm(value: Any) -> str:
    value = "" if value is None else str(value)
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def product_match_score(full_name: str, tab_name: str) -> float:
    a, b = norm(full_name), norm(tab_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if b in a or a in b:
        return 0.9
    at, bt = set(a.split()), set(b.split())
    if not bt:
        return 0.0
    return len(at & bt) / len(bt)


def file_product_name(path: Path) -> str:
    # Downloader filenames are the full Blinkit product name with the report extension.
    return path.stem.strip()


def read_report(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported report type: {suffix}")


def row_key(row: pd.Series, columns: list[str]) -> str:
    raw = "||".join("" if pd.isna(row[c]) else str(row[c]).strip() for c in columns)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class GoogleSheetsSync:
    def __init__(self, spreadsheet_id: str, protected_sheet_id: int):
        self.spreadsheet_id = spreadsheet_id
        self.protected_sheet_id = protected_sheet_id

    def status(self) -> dict:
        return {
            "configured": CLIENT_SECRET_FILE.exists(),
            "authorized": TOKEN_FILE.exists(),
            "spreadsheet_id": self.spreadsheet_id,
            "protected_sheet_id": self.protected_sheet_id,
        }

    def _flow(self) -> Flow:
        if not CLIENT_SECRET_FILE.exists():
            raise RuntimeError("credentials.json is missing.")
        flow = Flow.from_client_secrets_file(str(CLIENT_SECRET_FILE), scopes=SCOPES)
        flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/auth/google/callback")
        return flow

    def authorization_url(self) -> str | None:
        flow = self._flow()
        url, _ = flow.authorization_url(access_type="offline", prompt="consent")
        return url

    def exchange_code(self, code: str) -> None:
        flow = self._flow()
        flow.fetch_token(code=code)
        TOKEN_DIR.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")

    def _service(self):
        if not TOKEN_FILE.exists():
            raise RuntimeError("Google Sheets is not authorized. Open /auth/google first.")
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if not creds.valid:
            raise RuntimeError("Google authorization has expired or is invalid.")
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _metadata(self) -> list[dict]:
        service = self._service()
        data = service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            fields="sheets(properties(sheetId,title,index))",
        ).execute()
        return [s["properties"] for s in data.get("sheets", [])]

    def _match_tabs(self, product_name: str, sheets: list[dict]) -> tuple[dict | None, list[tuple[str, float]]]:
        candidates = []
        for s in sheets:
            if int(s["sheetId"]) == self.protected_sheet_id:
                continue
            score = product_match_score(product_name, s["title"])
            if score > 0:
                candidates.append((s["title"], score))
        candidates.sort(key=lambda x: x[1], reverse=True)
        if not candidates:
            return None, []
        # Do not silently write to an ambiguous tab.
        if len(candidates) > 1 and candidates[0][1] == candidates[1][1] and candidates[0][1] < 1.0:
            return None, candidates
        if candidates[0][1] >= 0.65:
            title = candidates[0][0]
            return next(s for s in sheets if s["title"] == title), candidates
        return None, candidates

    def _create_sheet(self, title: str) -> dict:
        service = self._service()
        body = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
        result = service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()
        return result["replies"][0]["addSheet"]["properties"]

    def _values(self, title: str) -> list[list[Any]]:
        service = self._service()
        result = service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{title.replace(chr(39), chr(39)*2)}'",
        ).execute()
        return result.get("values", [])

    def _append(self, title: str, rows: list[list[Any]]) -> None:
        service = self._service()
        service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{title.replace(chr(39), chr(39)*2)}'",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

    def sync_dataframe(self, product_name: str, df: pd.DataFrame) -> dict:
        if df.empty:
            return {"product": product_name, "status": "EMPTY", "added": 0}

        sheets = self._metadata()
        target, candidates = self._match_tabs(product_name, sheets)

        if target is None:
            target = self._create_sheet(product_name[:100])
            existing = []
            created = True
        else:
            existing = self._values(target["title"])
            created = False

        headers = [str(c) for c in df.columns]
        data = df.fillna("").astype(str).values.tolist()

        if created or not existing:
            self._append(target["title"], [headers] + data)
            return {"product": product_name, "tab": target["title"], "status": "CREATED", "added": len(data)}

        existing_headers = [str(x) for x in existing[0]]
        if existing_headers != headers:
            # Preserve the product tab's existing schema. Only append when the report schema matches.
            return {
                "product": product_name,
                "tab": target["title"],
                "status": "SCHEMA_MISMATCH",
                "added": 0,
                "existing_headers": existing_headers,
                "report_headers": headers,
            }

        existing_data = existing[1:]
        existing_keys = set()
        for row in existing_data:
            padded = row + [""] * (len(headers) - len(row))
            existing_keys.add(row_key(pd.Series(dict(zip(headers, padded))), headers))

        new_rows = []
        for row in data:
            series = pd.Series(dict(zip(headers, row)))
            key = row_key(series, headers)
            if key not in existing_keys:
                existing_keys.add(key)
                new_rows.append(row)

        if new_rows:
            self._append(target["title"], new_rows)

        return {
            "product": product_name,
            "tab": target["title"],
            "status": "UPDATED",
            "added": len(new_rows),
            "skipped_duplicates": len(data) - len(new_rows),
            "candidates": candidates,
        }

    def sync_report_directory(self) -> dict:
        root = Path(os.getenv("REPORT_ROOT", "Blinkit_Reports"))
        files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".xlsx", ".xls", ".csv"}]
        if not files:
            return {"error": f"No report files found under {root}"}

        results = []
        for path in sorted(files):
            try:
                df = read_report(path)
                results.append(self.sync_dataframe(file_product_name(path), df))
            except Exception as exc:
                results.append({"file": str(path), "status": "ERROR", "error": str(exc)})

        return {"status": "completed", "files": len(files), "results": results}
