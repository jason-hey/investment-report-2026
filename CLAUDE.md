# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Automated daily investment report pipeline:
1. GitHub Actions triggers `scripts/generate_report.py` on weekdays at 08:00 Taiwan time (UTC 00:00)
2. The script calls Claude API (`claude-sonnet-4-6`) with `web_search` tool to fetch live market data and generate a full self-contained HTML page
3. The generated `index.html` is committed and pushed, which auto-deploys via GitHub Pages
4. Telegram, LINE, and/or Email notifications are sent to configured recipients

The live report URL is always: `https://jason-hey.github.io/investment-report-2026/`

## Running the Report Generator Locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# Run for today
python scripts/generate_report.py

# Run for a specific date
DATE_OVERRIDE=2026-06-16 python scripts/generate_report.py
```

Output: overwrites `index.html`; backs up the newly generated version to `Backup/YYYY-MM-DD.html`. (The old `archive/` mechanism was removed 2026-07-03 — it backed up the *previous* day's report but labeled it with *today's* date, duplicating `Backup/` under a mislabeled filename.)

## Architecture

### `scripts/generate_report.py`
Core script. Skips generation if today's report already exists in `Backup/`, or if the previous US (XNYS) or Taiwan (XTAI) trading day was a market holiday — on a Taiwan-only holiday it instead injects a note into the prompt telling the model to label Taiwan-market figures as "most recent trading day" data rather than today's. Builds a large prompt with today's date and a fixed portfolio (`台積電/鴻海/聯發科/SMH/NVDA/AVGO/ORCL/LLY/0050/IAUM`), then calls Claude in a **streaming loop** to handle `pause_turn` stop reasons (required when the model needs multiple web search iterations before producing final output). Iterates up to 5 times. Extracts HTML from the final `end_turn` response via regex on ` ```html ``` ` fences, then validates it (minimum length, closing `</html>`, presence of `<table`/`<canvas`/`<script`) before writing — an invalid report raises instead of publishing a truncated page.

### `scripts/send_email.py`
Standalone email notifier. Reads `NOTIFY_EMAIL` (comma-separated), sends via Gmail SMTP SSL. Called by the workflow only if `GMAIL_USER` and `GMAIL_APP_PASSWORD` secrets are set.

### `.github/workflows/daily-update.yml`
Single job: checkout → install deps from `requirements.txt` → generate → git push → Telegram curl → LINE curl → email Python → failure alert. Telegram/LINE are sent inline via `curl`; email via `send_email.py`. All notification steps are no-ops if their secrets are absent. A final `if: failure()` step alerts via Telegram/LINE if any prior step fails.

## Required GitHub Secrets

| Secret | Required |
|---|---|
| `ANTHROPIC_API_KEY` | Yes |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Optional (both needed) |
| `LINE_CHANNEL_ACCESS_TOKEN` + (`LINE_USER_ID` and/or `LINE_GROUP_ID`) | Optional — `LINE_GROUP_ID` supports multiple groups, comma-separated |
| `GMAIL_USER` + `GMAIL_APP_PASSWORD` + `NOTIFY_EMAIL` | Optional (all three needed) |

## Manual Trigger

`Actions → Daily Investment Report → Run workflow` — accepts optional `date_override` (format `YYYY-MM-DD`).

## HTML Report Structure

The generated `index.html` is entirely self-contained (all CSS/JS inline). Key sections defined in the prompt: ticker marquee, hero banner, 5 warning indicators (VIX/HY spread/10Y yield/AI leaders/Taiwan leverage), KPI dashboard, Chart.js charts, earnings calendar with filter buttons, news tabs, risk matrix, theme cards, master strategy summary. Uses IBM Plex Mono + Inter fonts and dark theme (`#04040d`).

Historical snapshots of past reports are kept as `YYYY-MM-DD.html` files in `Backup/`.

## File Naming Conventions

All files stored in `doc/` and other documentation/backup folders must include the date as a prefix:

- **Format:** `YYYY-MM-DD-<description>.<ext>` or `YYYYMMDD-<description>.<ext>`
- **Examples:**
  - `2026-07-03-improvement-analysis.html`
  - `2026-07-03-line-setup.html`
  - `20260703-todo-list.md`
  
This ensures version history and easy tracking of when files were created or updated.
