from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from playwright.sync_api import sync_playwright

BROWSER_DATA_DIR = Path(os.getenv("BROWSER_DATA_DIR", "browser_profile"))
BLINKIT_URL = "https://seller.blinkit.com/"
DEBUG_PORT = int(os.getenv("BROWSER_DEBUG_PORT", "9222"))

_lock = Lock()
_playwright = None
_context = None


def start_persistent_browser():
    """Start one persistent Chromium profile for the cloud worker."""
    global _playwright, _context
    with _lock:
        if _context is not None:
            return _context

        BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        _playwright = sync_playwright().start()
        _context = _playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        return _context


def get_blinkit_page():
    context = start_persistent_browser()
    for page in context.pages:
        if "seller.blinkit.com" in page.url:
            return page
    page = context.new_page()
    page.goto(BLINKIT_URL, wait_until="domcontentloaded")
    return page


def session_status() -> dict:
    try:
        page = get_blinkit_page()
        url = page.url
        title = page.title()
        logged_in = "login" not in url.lower() and "sign in" not in title.lower()
        return {
            "browser": "running",
            "blinkit_url": url,
            "page_title": title,
            "authenticated": logged_in,
            "profile": str(BROWSER_DATA_DIR),
        }
    except Exception as exc:
        return {"browser": "error", "authenticated": False, "error": str(exc)}


def stop_browser():
    global _playwright, _context
    with _lock:
        if _context is not None:
            _context.close()
            _context = None
        if _playwright is not None:
            _playwright.stop()
            _playwright = None
