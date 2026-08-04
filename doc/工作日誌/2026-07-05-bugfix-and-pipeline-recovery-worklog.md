# 工作日誌：全程式碼 bug 審查、6 項修正、pipeline 復活

**日期：** 2026-07-05（同日第二份日誌，接在 [2026-07-05-plan3-completion-and-merge-worklog.md](2026-07-05-plan3-completion-and-merge-worklog.md) 之後）
**狀態：** ✅ 全部完成、已推上 GitHub（commit `38af08c`）、workflow 已實測恢復正常

---

## 目前進度（詳細說明）

### 1. 起因與過程

本次對話從「檢查目前程式有無 bug」開始，全面審查了 `scripts/` 下 5 個 Python 檔、workflow YAML 與模板，先找出 5 個輕微的資料品質／邊界問題。過程中使用者貼出 GitHub Actions 的截圖，發現**第 6 個、也是最嚴重的問題**：workflow 檔案本身有 YAML 語法錯誤，GitHub 判定 Invalid workflow file，**整條每日 pipeline 當時完全停擺**（連排程都不會觸發）。

### 2. 六項修正（依嚴重度排列）

| # | 問題 | 修正 | 位置 |
|---|---|---|---|
| 6（緊急） | failure alert 步驟的多行 `MSG="..."` 字串續行沒縮排，在 `run: \|` 區塊裡縮排不足的行會終止整個區塊 → 整份 workflow 無法解析、pipeline 停擺 | 改用 `printf` 組多行訊息（比照 Telegram/LINE 步驟既有寫法），並以 `yaml.safe_load` 驗證可解析 | `.github/workflows/daily-update.yml` |
| 1 | P/E 歷史前視偏差：`quarterly_income_stmt` 索引是「季度截止日」而非「公布日」，TTM EPS 提前 1~2 個月生效 | 生效日改為「截止日 + 45 天」（美股 10-Q／台股季報期限的估計公布日） | `scripts/data_fetchers.py` `fetch_pe_history()` |
| 2 | 勝率回顧的 `prev_trading_date` 只跳週末不跳台股假日 → 假日前後會拿錯誤日期查歷史入選清單、用選股之前的漲跌評判選股 | 新增 `prev_trading_day()`：用 XTAI 行事曆找前一實際交易日，查詢失敗保守退回只跳週末；`generate_report.py` 接上 | `scripts/data_fetchers.py`、`scripts/generate_report.py` |
| 3 | `validate_narrative_json()` 只檢查欄位存在——AI 輸出 `null`／型別錯誤會通過驗證，直到模板深處才炸出難懂的 Jinja traceback；另外 `lly_foundayo` 缺圖表欄位、字串數字（`"1,390"`）、幻覺項目都會讓渲染直接失敗 | `REQUIRED_JSON_FIELDS` 改為「欄位 → 期望型別」dict、驗證回傳點名欄位的問題清單；新增 `_sanitize_lly_foundayo()` + `_to_chart_number()`（缺欄位補 `[]`、字串數字轉真數字、壞項目丟棄） | `scripts/generate_report.py`、`scripts/report_render.py` |
| 4 | 手動用 `date_override` 補跑歷史報告時，Email/Telegram/LINE 通知顯示的日期永遠是「今天」，跟報告內容不一致 | `send_email.py` 重構為可測試的 `build_email()` + `main()`（加 `if __name__` 保護）並支援 `DATE_OVERRIDE`；workflow 的 Telegram/LINE 步驟同步傳入並優先採用 | `scripts/send_email.py`、`.github/workflows/daily-update.yml` |
| 5 | 價格顯示用 `:,g` 只有 6 位有效數字：加權指數 23,456.78 被截成 23,456.8 | 新增 `_fmt_price()`（千分位 + 最多 2 位小數、去尾端 0），ticker 跑馬燈／KPI 卡片／漲跌字串全面改用 | `scripts/report_render.py` |

### 3. TDD 與驗證

- 全程遵循 TDD：每項修正先寫失敗的迴歸測試（watch RED）再實作（watch GREEN）。測試數 **84 → 97，全數通過**。
- 插曲：過程中 Claude Code 的 Bash 工具短暫不可用（權限分類器暫時故障），Fix 3 的實作先於 RED 觀察完成；事後用 `git stash` 把實作退回舊版、確認 3 個新測試對舊程式碼確實失敗（RED），還原後再確認通過（GREEN），補齊了 TDD 的觀察步驟。
- 審查時同場排除的疑慮（實測確認**不是** bug）：yfinance 1.5.1 的 `period="2wk"`/`"2mo"` 是合法參數；模板對空資料有防護；`| tojson` 注入安全；`autoescape` 信任邊界正確。

### 4. 發布與實測

- commit `38af08c`（10 個檔案）push 上 `origin/main`。
- GitHub API 確認 workflow 狀態恢復 `active`（不再 Invalid）。
- 本機真實執行 `python scripts/generate_report.py`：正確判斷 2026-07-03（五）為美股假日（美國國慶補假）→ 跳過生成、exit 0。
- 使用者在 GitHub 手動觸發一次 workflow：**succeeded in 22s**——Generate report 2 秒（假日跳過）、無變更不 commit、通知步驟全部正確跳過（設計行為：只有真的發布新報告才通知）。pipeline 確認復活。

---

## 下一步（具體任務）

1. **等 2026-07-07（週二）08:00 台灣時間的排程執行**——這會是修復後（也是新架構＋選股訊號系統）第一次真正的完整生成與發布。要確認：
   - 新報告成功生成、`index.html` 更新、GitHub Pages 網頁更新（`https://jason-hey.github.io/investment-report-2026/`）
   - Telegram/LINE/Email 通知正常送達、通知裡的摘要（`daily_brief`）有內容
   - `data/stock_signals_history.json` 第一次被 commit 進 repo
   - （延續前一份日誌的觀察項）65 檔觀察清單中 5 檔（5347/3529/3324/6274/8299）yfinance 缺資料的狀況在正式環境是否相同
2. 若週二報告有問題：把 Actions log 或網頁現象貼給 Claude 查。
3. （可選、非必要）P/E 的「+45 天」是估計公布日；若未來想更精確，可改用 `ticker.earnings_dates`（真實公布日）——目前估計值已足夠消除前視偏差的主要影響。

---

## 相關檔案路徑

**本次修改（commit `38af08c`，已推上遠端）：**
- `.github/workflows/daily-update.yml` — YAML 語法修復（printf）+ 三個通知步驟支援 `DATE_OVERRIDE`
- `scripts/data_fetchers.py` — `fetch_pe_history()` 45 天公布日延遲、新增 `prev_trading_day()`
- `scripts/generate_report.py` — `REQUIRED_JSON_FIELDS` 型別 dict、`validate_narrative_json()` 型別檢查、接上 `prev_trading_day()`
- `scripts/report_render.py` — `_fmt_price()`、`_to_chart_number()`、`_sanitize_lly_foundayo()`
- `scripts/send_email.py` — 重構為 `build_email()`/`main()`、支援 `DATE_OVERRIDE`
- `tests/conftest.py` — stub `prev_trading_day`
- `tests/test_data_fetchers.py`、`tests/test_generate_report.py`、`tests/test_report_render.py` — 13 個新迴歸測試
- `tests/test_send_email.py` — 新檔

**前一份日誌（同日稍早，Plan 1-3 完成與合併）：**
- [doc/工作日誌/2026-07-05-plan3-completion-and-merge-worklog.md](2026-07-05-plan3-completion-and-merge-worklog.md)

---

## 如何在新對話中接續

目前**沒有進行中的分支或未完成的任務**。開新對話時：

- 若是**週二排程後的檢查**：請 Claude 檢查最新的 GitHub Actions 執行紀錄、`index.html` 與 `data/stock_signals_history.json`，對照上方「下一步」清單逐項確認。
- 若報告生成**失敗或內容異常**：貼上 Actions log 或截圖即可，本日誌的修正清單可幫助快速定位是否為回歸。
- 若是**新需求**（調整訊號門檻、加功能等）：直接描述需求，視情況用 brainstorming／writing-plans 重新規劃。
