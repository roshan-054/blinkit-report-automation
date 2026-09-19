# Blinkit Report Automation

Blinkit Seller Hub report downloader with Google Sheets synchronization.

## Current scope
- Use an already authenticated Blinkit browser session; no automated OTP/login.
- Download the latest available report for each eligible product.
- Save reports by month/date.
- Prevent duplicate downloads.
- Retry timed-out downloads once.
- Upload downloaded report data to Google Sheets from a dedicated action.
- Match full Blinkit product names to short product-tab names.
- Create a missing product tab when required.
- Incrementally append only new report rows.
- Never write to the protected main sheet.

## Google Sheet
Spreadsheet ID:
`1SMMFfqWqWalOys5swqpxk_jIz_l4-kJPU_9V9Ix9OKQ`

Protected main sheet ID:
`695987561`

## Local browser
Start Chrome with remote debugging and an isolated persistent profile:

```bat
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\BlinkitAutomationChrome"
```

Log into Blinkit manually, then run the application.

## Environment
Copy `.env.example` to `.env` and configure Google OAuth credentials. Never commit client secrets or OAuth tokens.
