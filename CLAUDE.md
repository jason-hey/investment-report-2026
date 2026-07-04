# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Automated daily investment report pipeline:
1. GitHub Actions triggers `scripts/generate_report.py` on weekdays at 08:00 Taiwan time (UTC 00:00)
2. The script pre-fetches almost all numbers/charts in Python (yfinance + TWSE OpenAPI), calls Claude API (`claude-sonnet-4-6`) with `web_search` to write only the narrative text as structured JSON, and renders the final page from a Jinja2 template (`templates/report.html.j2`) — the model never writes HTML directly
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

Output: overwrites `index.html`; backs up the newly generated version to `Backup/YYYY-MM-DD.html`; also updates `data/stock_signals_history.json` (yesterday's stock-pick win rate, see below). (The old `archive/` mechanism was removed 2026-07-03 — it backed up the *previous* day's report but labeled it with *today's* date, duplicating `Backup/` under a mislabeled filename.)

## Architecture

The report is built in three layers: **Python pre-fetches and pre-computes every number and chart**, **Claude writes only narrative text** as structured JSON (no HTML), and **Jinja2 renders** the final page from a fixed template. This replaced an earlier design (pre 2026-07-04) where the model generated the entire ~100KB HTML page itself via `web_search` — that approach meant every run risked the model hallucinating numbers or breaking the page's JS/CSS. `git log` on `scripts/generate_report.py` around the "report architecture rewrite" commits documents the migration if more history is needed.

### `scripts/data_fetchers.py`
All data-fetching functions, each degrading gracefully (empty dict/list + a `⚠️` log line) rather than raising, so one bad ticker or a flaky endpoint doesn't take down the whole run:
- Earnings calendar and P/E history via yfinance — P/E history uses real quarterly TTM EPS (`fetch_pe_history`), not a fixed EPS reverse-engineered from today's trailing P/E
- VIX fear index history via yfinance
- Taiwan institutional investors' (外資/投信) 3-consecutive-day same-direction net buy/sell top-10 rankings via TWSE OpenAPI (`fetch_institutional_3day_ranking`) — amounts are estimated from the latest close price, not exact per-day figures; falls back to letting the model search if TWSE data is unavailable
- Korea market (KOSPI + Samsung + SK Hynix), a ~40-stock US heatmap, 11 SPDR sector-rotation ETFs, and WTI/Brent oil prices — all yfinance, all rendered straight from Python, no AI involved
- ADR premium (TSM/UMC/ASX vs. their TW-listed underlying), TWSE margin-trading balances (short-squeeze candidates), TWSE monthly revenue YoY, and per-watchlist institutional buy/sell + trade-value ratio — these feed the stock-signal-scoring system below
- `_fetch_twse_close_prices_and_value()` and `fetch_institutional_3day_ranking()`/`fetch_watchlist_institutional()` accept an optional pre-fetched-data parameter so `generate_report.py` can share one `STOCK_DAY_ALL` TWSE call across both consumers instead of fetching it twice

### `scripts/signal_scoring.py`
Taiwan stock signal-scoring system: a fixed, curated ~65-stock watchlist (`TW_STOCK_WATCHLIST`, deliberately not the whole market — controls yfinance/TWSE call volume) and a US-stock → TW-supply-chain map (`US_TO_TW_SUPPLY_CHAIN`). 8 pure scoring functions (`score_adr_signal`, `score_us_supply_chain_signal`, `score_dual_buy_signal`, `score_buy_value_ratio_signal`, `score_short_squeeze_signal`, `score_revenue_yoy_signal`, `score_breakout_signal`, `score_rs_rank_signal`) each take pre-fetched data and return `{code: {"hit": bool, "detail": str}}`; `compute_signal_scores()` merges all 8 into a ranked "today's watchlist" table. `load_signal_history()`/`save_signal_history()`/`record_todays_picks()`/`compute_win_rate_review()` persist each day's top picks to `data/stock_signals_history.json` (committed to git, capped at 30 days) and compare yesterday's picks against today's actual price moves for a running win-rate.

### `scripts/report_render.py`
Turns pre-fetched data + the AI's narrative JSON into the Jinja2 context and renders `templates/report.html.j2`. Each data source has a `build_*_context()` function; several (`korea_data`, `heatmap_data`, `sector_rotation_data`, `oil_data`, `signal_scoring_context`) default to an empty/normalized shape rather than being required, since their real callers in `generate_report.py` were wired up incrementally across several tasks. AI-authored fields go through `_sanitize_*`/defensive `.get()`-based helpers before hitting the template, since narrative JSON is untrusted model output (could be malformed, missing keys, or — since it originates from `web_search` results — contain adversarial content). `render_report()` uses `autoescape=True`; only 3 fields (`ai_infra_html`, `lly_foundayo.extra_html`, `market_deep_dive_html`) are marked `| safe` in the template and allowed to carry raw AI-authored HTML — every other narrative field is escaped.

### `scripts/generate_report.py`
Orchestration only: skips generation if today's report already exists in `Backup/`, or if the previous US (XNYS) or Taiwan (XTAI) trading day was a market holiday — on a Taiwan-only holiday it instead injects a note into the prompt telling the model to label Taiwan-market figures as "most recent trading day" data rather than today's. Calls all the `data_fetchers`/`signal_scoring` functions above, builds a prompt (fixed portfolio `台積電/鴻海/聯發科/SMH/NVDA/AVGO/ORCL/LLY/0050/IAUM` plus the day's pre-fetched numbers and the day's signal-scoring picks) asking Claude for **JSON only** (`JSON_OUTPUT_SPEC`/`REQUIRED_JSON_FIELDS`), calling it in a **streaming loop** to handle `pause_turn` stop reasons (needed when the model requires multiple web-search iterations). Iterates up to 5 times. Extracts JSON from the final `end_turn` response via regex on ` ```json ``` ` fences (`extract_json_block`), validates all required fields are present (`validate_narrative_json`) — missing fields raise, not degrade — then calls `report_render.build_template_context()`/`render_report()` and validates the *rendered HTML* (`validate_html`: minimum length, closing `</html>`, presence of `<table`/`<canvas`/`<script`) before writing. Either validation failing raises instead of publishing a truncated or incomplete page. Has no `if __name__:` guard — it's a top-level script that runs its whole pipeline on import; `tests/conftest.py` documents how tests stub around this.

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

The generated `index.html` is entirely self-contained (all CSS/JS inline), rendered from `templates/report.html.j2`. Sections, roughly in page order: ticker marquee, hero banner, 5 warning indicators (VIX/HY spread/10Y yield/AI leaders/Taiwan leverage), KPI dashboard, Chart.js charts (P/E trend, VIX history), earnings calendar with filter buttons, Korea market, US stock heatmap, US sector rotation, oil price chart, **今日觀察清單 stock-signal-scoring table + 昨日選股回顧 win-rate review** (Python-computed, AI only writes each pick's one-line reason), Taiwan futures night session, institutional 3-day ranking, news tabs, risk matrix, theme cards, LLY Foundayo tracker, master strategy summary. Uses IBM Plex Mono + Inter fonts and dark theme (`#04040d`).

Historical snapshots of past reports are kept as `YYYY-MM-DD.html` files in `Backup/`.

## File Naming Conventions

All files stored in `doc/` and other documentation/backup folders must include the date as a prefix:

- **Format:** `YYYY-MM-DD-<description>.<ext>` or `YYYYMMDD-<description>.<ext>`
- **Examples:**
  - `2026-07-03-improvement-analysis.html`
  - `2026-07-03-line-setup.html`
  - `20260703-todo-list.md`
  
This ensures version history and easy tracking of when files were created or updated.
