# Blinkit Report Automation

Blinkit Seller Hub report downloader with Google Sheets synchronization.

## Important: GitHub Pages is only a preview

The GitHub Pages URL is **not the working automation server**. Blinkit automation requires a Windows machine with Chrome, Playwright and the already-authenticated Blinkit session.

## Simple Windows setup

### First time only
1. Download the repository ZIP and extract it.
2. Install Python 3.12+ if it is not already installed.
3. Double-click **Setup Blinkit Automation.bat**.
4. Put your Google OAuth credentials.json in the project folder when you are ready to connect Google.

### Normal daily use
Double-click **Start Blinkit Automation.bat**.

It will start a dedicated Chrome profile, open Blinkit Seller Hub, start the local automation server, and open the working dashboard at http://127.0.0.1:8000.

If Blinkit requests authentication, complete it manually. OTP/login is not automated.

Then use **Download Latest Reports** and **Upload Latest Reports to Google Sheets**.

No VS Code or terminal commands are required for normal use.

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
Spreadsheet ID: 1SMMFfqWqWalOys5swqpxk_jIz_l4-kJPU_9V9Ix9OKQ
Protected main sheet ID: 695987561

## Local browser
The launcher uses a separate Chrome profile at %LOCALAPPDATA%\BlinkitAutomationChrome.

## Google Drive archive
When Google authorization includes Drive access, each processed report is archived under Blinkit Reports/<Month YYYY>/<DD-MMM-YYYY>/. Existing files are skipped. Drive archiving errors are reported separately and do not roll back a successful Sheets sync.
