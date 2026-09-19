"""
Blinkit Seller Hub report automation.

This module intentionally does not automate login or OTP.
It attaches to an already authenticated Chrome session over CDP.
The report-download workflow is kept separate from Google Sheets sync.
"""

from pathlib import Path
import json
import os
import re
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from dotenv import load_dotenv

load_dotenv()

CHROME_DEBUG_URL = os.getenv("CHROME_DEBUG_URL", "http://127.0.0.1:9222")
REPORT_ROOT = Path(os.getenv("REPORT_ROOT", "Blinkit_Reports"))
EXCLUDED_ITEM_IDS = {"10264460", "10244858", "10261799"}
DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1000
PRODUCT_COOLDOWN_SECONDS = 5


def extract_product_name(row) -> str:
    """Extract the actual product name from a Product Expansion row."""
    candidates = []
    selectors = [
        "a",
        "button",
        "[title]",
        "[data-testid]",
    ]
    for selector in selectors:
        try:
            for el in row.locator(selector).all():
                try:
                    text = el.inner_text().strip()
                    title = (el.get_attribute("title") or "").strip()
                    for value in (text, title):
                        if value and len(value) >= 4:
                            candidates.append(value)
                except Exception:
                    pass
        except Exception:
            pass

    blocked = {
        "item id", "performance", "reports", "view", "details",
        "active", "inactive", "enabled", "disabled"
    }
    cleaned = []
    for value in candidates:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized.lower() in blocked:
            continue
        if re.search(r"Item ID\s*:", normalized, re.I):
            continue
        if normalized not in cleaned:
            cleaned.append(normalized)

    # Prefer the longest plausible product label; row text is only a fallback.
    if cleaned:
        return max(cleaned, key=len)

    text = re.sub(r"\s+", " ", row.inner_text()).strip()
    text = re.sub(r"Item ID\s*:\s*\d+", "", text, flags=re.I)
    return text.strip()


def clean_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name).strip().rstrip(".")


def report_folder(now: datetime | None = None) -> Path:
    now = now or datetime.now()
    return REPORT_ROOT / now.strftime("%B %Y") / now.strftime("%d-%b-%Y")


def log_path(folder: Path) -> Path:
    return folder / "download_log.json"


def load_log(folder: Path) -> dict:
    path = log_path(folder)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_log(folder: Path, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "download_log.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(log_path(folder))


def ensure_product_expansion(page) -> None:
    if "product-expansion" in page.url.lower():
        return
    page.goto("https://seller.blinkit.com/performance/product-expansion", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)


def get_product_rows(page) -> list[dict]:
    rows = []
    for item in page.get_by_text("Item ID:", exact=False).all():
        try:
            text = item.inner_text()
            m = re.search(r"Item ID:\s*(\d+)", text)
            if not m:
                continue
            item_id = m.group(1)
            row = item.locator("xpath=ancestor::*[.//input[@type='checkbox']][1]")
            product_name = extract_product_name(row)
            rows.append({"item_id": item_id, "product_name": product_name, "row": row})
        except Exception:
            continue

    dedup = {}
    for r in rows:
        dedup[r["item_id"]] = r
    return list(dedup.values())


def find_product_row(page, item_id: str):
    for item in page.get_by_text("Item ID:", exact=False).all():
        try:
            text = item.inner_text()
            if item_id not in text:
                continue
            return item.locator("xpath=ancestor::*[.//input[@type='checkbox']][1]")
        except Exception:
            continue
    return None


def open_product_by_item_id(page, item_id: str) -> bool:
    ensure_product_expansion(page)
    row = find_product_row(page, item_id)
    if row is None:
        return False
    row.click()
    page.wait_for_timeout(2000)
    return True


def find_latest_report(page):
    pattern = re.compile(r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})")
    candidates = []
    for text in page.locator("body").inner_text().splitlines():
        m = pattern.search(text)
        if not m:
            continue
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                start = datetime.strptime(m.group(1), fmt)
                end = datetime.strptime(m.group(2), fmt)
                candidates.append((end, start, m.group(0)))
                break
            except ValueError:
                pass
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def already_downloaded(folder: Path, item_id: str, product_name: str, report_period: str) -> bool:
    log = load_log(folder)
    key = f"{item_id}||{report_period}"
    if key in log:
        return True
    stem = clean_filename(product_name)
    return any(p.is_file() and p.stem == stem for p in folder.iterdir()) if folder.exists() else False


def download_latest_report(page, item_id: str, product_name: str) -> dict:
    report_period = find_latest_report(page)
    if not report_period:
        return {"status": "NO_REPORT", "item_id": item_id, "product_name": product_name}

    folder = report_folder()
    folder.mkdir(parents=True, exist_ok=True)

    if already_downloaded(folder, item_id, product_name, report_period):
        return {"status": "SKIPPED", "item_id": item_id, "product_name": product_name, "report_period": report_period}

    # The exact Reports button/row locator can vary with Seller Hub markup.
    reports_button = page.get_by_text("Reports", exact=True).first
    reports_button.click()
    page.wait_for_timeout(1000)

    with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
        latest = page.get_by_text(report_period, exact=False).first
        latest.click()

    download = download_info.value
    download.path()  # ensure the browser-side download has completed
    source_name = download.suggested_filename
    ext = Path(source_name).suffix or ".xlsx"
    target = folder / f"{clean_filename(product_name)}{ext}"
    download.save_as(str(target))

    log = load_log(folder)
    log[f"{item_id}||{report_period}"] = {
        "item_id": item_id,
        "product_name": product_name,
        "report_period": report_period,
        "file_name": target.name,
        "file_path": str(target),
        "downloaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_log(folder, log)

    return {
        "status": "DOWNLOADED",
        "item_id": item_id,
        "product_name": product_name,
        "report_period": report_period,
        "file_path": str(target),
    }


def run():
    with sync_playwright() as p:
        if os.getenv("BROWSER_MODE", "cdp").lower() == "persistent":
            from cloud_browser import get_blinkit_page
            page = get_blinkit_page()
        else:
            browser = p.chromium.connect_over_cdp(CHROME_DEBUG_URL)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = next((pg for pg in context.pages if "seller.blinkit.com" in pg.url), context.pages[0])

        ensure_product_expansion(page)
        rows = [r for r in get_product_rows(page) if r["item_id"] not in EXCLUDED_ITEM_IDS]
        retry_queue = []
        results = []

        for r in rows:
            if not open_product_by_item_id(page, r["item_id"]):
                results.append({**r, "status": "ERROR", "error": "Product row not found"})
                continue
            try:
                result = download_latest_report(page, r["item_id"], r["product_name"])
                results.append(result)
                if result.get("status") == "TIMEOUT":
                    retry_queue.append(r)
            except PlaywrightTimeoutError:
                retry_queue.append(r)
                results.append({**r, "status": "TIMEOUT"})
            finally:
                page.wait_for_timeout(PRODUCT_COOLDOWN_SECONDS * 1000)

        for r in retry_queue:
            ensure_product_expansion(page)
            if not open_product_by_item_id(page, r["item_id"]):
                results.append({**r, "status": "RETRY_ERROR", "error": "Product row not found"})
                continue
            try:
                results.append(download_latest_report(page, r["item_id"], r["product_name"]))
            except PlaywrightTimeoutError:
                results.append({**r, "status": "FAILED_AFTER_RETRY"})
            finally:
                page.wait_for_timeout(PRODUCT_COOLDOWN_SECONDS * 1000)

        return results


if __name__ == "__main__":
    for item in run():
        print(item)
