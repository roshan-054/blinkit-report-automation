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
MAPPING_FILE = Path("product_tab_mapping.json")


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
    return len(at & bt) / len(bt) if bt else 0.0


def file_product_name(path: Path) -> str:
    return path.stem.strip()


def read_report(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".csv":
        # utf-8-sig handles the common Excel-export BOM; latin-1 is a safe fallback for legacy exports.
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="latin-1")
    raise ValueError(f"Unsupported report type: {suffix}")


def canonical(value: Any) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value).strip()


def row_key(row: pd.Series, columns: list[str]) -> str:
    raw = "||".join(canonical(row[c]) for c in columns)
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
            "mapping_file": str(MAPPING_FILE),
        }

    def _flow(self) -> Flow:
        if not CLIENT_SECRET_FILE.exists():
            raise RuntimeError("credentials.json is missing.")
        flow = Flow.from_client_secrets_file(str(CLIENT_SECRET_FILE), scopes=SCOPES)
        flow.redirect_uri = os.getenv(
            "GOOGLE_REDIRECT_URI",
            "http://127.0.0.1:8000/auth/google/callback",
        )
        return flow

    def authorization_url(self) -> str:
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
            if creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RuntimeError("Google authorization has expired or is invalid.")
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _metadata(self) -> list[dict]:
        data = self._service().spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            fields="sheets(properties(sheetId,title,index))",
        ).execute()
        return [s["properties"] for s in data.get("sheets", [])]

    def _load_mapping(self) -> dict[str, str]:
        if not MAPPING_FILE.exists():
            return {}
        try:
            return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_mapping(self, mapping: dict[str, str]) -> None:
        MAPPING_FILE.write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _match_tabs(self, product_name: str, sheets: list[dict]) -> tuple[dict | None, list[tuple[str, float]]]:
        mapping = self._load_mapping()
        mapped_title = mapping.get(norm(product_name))
        if mapped_title:
            for sheet in sheets:
                if int(sheet["sheetId"]) != self.protected_sheet_id and sheet["title"] == mapped_title:
                    return sheet, [(mapped_title, 1.0)]

        candidates = []
        for sheet in sheets:
            if int(sheet["sheetId"]) == self.protected_sheet_id:
                continue
            score = product_match_score(product_name, sheet["title"])
            if score > 0:
                candidates.append((sheet["title"], score))
        candidates.sort(key=lambda x: x[1], reverse=True)

        if not candidates:
            return None, []

        if len(candidates) > 1 and candidates[0][1] == candidates[1][1] and candidates[0][1] < 1.0:
            return None, candidates

        if candidates[0][1] >= 0.65:
            title = candidates[0][0]
            return next(s for s in sheets if s["title"] == title), candidates
        return None, candidates

    def _create_sheet(self, title: str) -> dict:
        # Sheets API limits titles to 100 characters.
        title = title[:100].strip() or "Product"
        existing_titles = {s["title"] for s in self._metadata()}
        base, n = title, 2
        while title in existing_titles:
            suffix = f" ({n})"
            title = f"{base[:100-len(suffix)]}{suffix}"
            n += 1
        result = self._service().spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
        return result["replies"][0]["addSheet"]["properties"]

    def _values(self, title: str) -> list[list[Any]]:
        safe = title.replace("'", "''")
        result = self._service().spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{safe}'",
        ).execute()
        return result.get("values", [])

    def _append(self, title: str, rows: list[list[Any]]) -> None:
        if not rows:
            return
        safe = title.replace("'", "''")
        self._service().spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{safe}'",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

    def _batch_append(self, title: str, rows: list[list[Any]], batch_size: int = 1000) -> None:
        for start in range(0, len(rows), batch_size):
            self._append(title, rows[start:start + batch_size])

    def _new_rows(self, headers: list[str], data: list[list[Any]], existing: list[list[Any]]) -> tuple[list[list[Any]], int]:
        existing_keys = set()
        for raw in existing[1:]:
            padded = raw[:len(headers)] + [""] * max(0, len(headers) - len(raw))
            existing_keys.add(row_key(pd.Series(dict(zip(headers, padded))), headers))

        new_rows = []
        duplicate_count = 0
        for raw in data:
            padded = raw[:len(headers)] + [""] * max(0, len(headers) - len(raw))
            key = row_key(pd.Series(dict(zip(headers, padded))), headers)
            if key in existing_keys:
                duplicate_count += 1
                continue
            existing_keys.add(key)
            new_rows.append(raw)
        return new_rows, duplicate_count

    def sync_dataframe(self, product_name: str, df: pd.DataFrame) -> dict:
        if df.empty:
            return {"product": product_name, "status": "EMPTY", "added": 0}

        sheets = self._metadata()
        target, candidates = self._match_tabs(product_name, sheets)

        if target is None:
            if candidates:
                return {
                    "product": product_name,
                    "status": "AMBIGUOUS_TAB",
                    "added": 0,
                    "candidates": candidates,
                }
            target = self._create_sheet(product_name)
            existing = []
            created = True
        else:
            existing = self._values(target["title"])
            created = False

        headers = [str(c) for c in df.columns]
        data = df.fillna("").astype(str).values.tolist()

        if created or not existing:
            self._batch_append(target["title"], [headers] + data)
            mapping = self._load_mapping()
            mapping[norm(product_name)] = target["title"]
            self._save_mapping(mapping)
            return {
                "product": product_name,
                "tab": target["title"],
                "status": "CREATED",
                "added": len(data),
                "skipped_duplicates": 0,
            }

        existing_headers = [str(x) for x in existing[0]]
        if existing_headers != headers:
            return {
                "product": product_name,
                "tab": target["title"],
                "status": "SCHEMA_MISMATCH",
                "added": 0,
                "existing_headers": existing_headers,
                "report_headers": headers,
            }

        date_column = next((h for h in headers if norm(h) == "date"), None)
        last_existing_date = None
        report_min_date = report_max_date = None
        candidate_df = df

        if date_column and len(existing) > 1:
            existing_df = pd.DataFrame(existing[1:], columns=existing_headers)
            parsed_existing = pd.to_datetime(existing_df[date_column], errors="coerce")
            if parsed_existing.notna().any():
                last_existing_date = parsed_existing.max().date()

            parsed_report = pd.to_datetime(df[date_column], errors="coerce")
            if parsed_report.notna().any():
                report_min_date = parsed_report.min().date()
                report_max_date = parsed_report.max().date()
                if last_existing_date is not None:
                    # Include the latest existing date for same-day row-level dedupe.
                    candidate_df = df[(parsed_report.isna()) | (parsed_report.dt.date >= last_existing_date)].copy()

        candidate_data = candidate_df.fillna("").astype(str).values.tolist()
        new_rows, duplicate_count = self._new_rows(headers, candidate_data, existing)
        self._batch_append(target["title"], new_rows)

        mapping = self._load_mapping()
        mapping[norm(product_name)] = target["title"]
        self._save_mapping(mapping)

        return {
            "product": product_name,
            "tab": target["title"],
            "status": "UPDATED",
            "added": len(new_rows),
            "skipped_duplicates": duplicate_count,
            "candidates": candidates,
        }

    def _report_date_from_path(self, path: Path):
        for parent in [path.parent, *path.parents]:
            match = re.fullmatch(r"\d{2}-[A-Za-z]{3}-\d{4}", parent.name)
            if match:
                try:
                    return pd.to_datetime(parent.name, format="%d-%b-%Y")
                except Exception:
                    pass
        return pd.Timestamp(path.stat().st_mtime, unit="s")

    def sync_report_directory(self) -> dict:
        root = Path(os.getenv("REPORT_ROOT", "Blinkit_Reports"))
        all_files = [
            p for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in {".xlsx", ".xls", ".csv"}
        ]
        if not all_files:
            return {"error": f"No report files found under {root}"}

        # Process only the newest archived report for each product.
        latest_by_product = {}
        for path in all_files:
            key = norm(file_product_name(path))
            stamp = self._report_date_from_path(path)
            if key not in latest_by_product or stamp > latest_by_product[key][0]:
                latest_by_product[key] = (stamp, path)

        files = [item[1] for item in sorted(latest_by_product.values(), key=lambda x: x[1].name.lower())]
        results = []
        for path in files:
            try:
                df = read_report(path)
                result = self.sync_dataframe(file_product_name(path), df)
                result["file"] = str(path)
                results.append(result)
            except Exception as exc:
                results.append({"file": str(path), "status": "ERROR", "error": str(exc)})

        return {
            "status": "completed",
            "files": len(files),
            "archived_files_found": len(all_files),
            "results": results,
        }
