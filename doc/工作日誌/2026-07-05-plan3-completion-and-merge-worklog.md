# 工作日誌：Plan 3 完成、最終審查、合併至 main

**日期：** 2026-07-05
**狀態：** ✅ 全部完成並已合併、已推上 GitHub

---

## 目前進度（詳細說明）

延續 [2026-07-04-report-architecture-rewrite-worklog.md](2026-07-04-report-architecture-rewrite-worklog.md) 的中斷點（Task 9 尚未開始），本次對話完成了以下全部工作：

### 1. Plan 3（台股當日選股訊號評分系統）Task 9 ~ 14 全部完成

| Task | 內容 | 結果 |
|---|---|---|
| 9 | AI JSON schema 新增 `stock_signal_reasons` 欄位 | ✅ 刻意縮小範圍，只加 schema／`REQUIRED_JSON_FIELDS`／測試，**沒有**同時把 prompt 區塊接上——因為 `generate_report.py` 沒有 `if __name__` 保護、import 時就會整個執行，太早接上 `signal_scores_json` 這個當時還不存在的變數會讓既有 subprocess 迴歸測試從「預期在 API 金鑰處失敗」變成「NameError 直接死掉」。這個判斷後來被證明是對的：Task 13 才是真正把變數接上的地方。 |
| 10 | `build_signal_scoring_context()`（`report_render.py`） | ✅ Code review 抓到：`ai_reasons` 是 AI 生成的 JSON，直接用 `item["code"]` 索引在缺欄位時會 KeyError、拖垮整份報告。改用 `.get()` 防呆＋None 正規化，補測試。 |
| 11 | 模板新增「今日觀察清單」+「昨日選股回顧」區塊 | ✅ 插入 template 時發現：`build_template_context()` 當時還沒有 `signal_scoring_context` 參數，模板直接寫 `signal_scoring.picks` 會讓既有的 `tests/conftest.py` autouse fixture 在 import 階段就整個 UndefinedError 崩潰。加了過渡期防呆（`is defined`/`is mapping`），並標記 TODO 待 Task 12 處理。 |
| 12 | `build_template_context()` 串接 `signal_scoring` context key | ✅ **偏離 plan 文件**：plan 寫「必填參數」，但比照 Plan 2 的 `korea_data`/`oil_data` 慣例改成有預設值——理由跟 Task 9 一樣，Task 13 的真正接線是下一個獨立 task，必填會讓現有呼叫端直接 TypeError。Review 後又追加：把預設值抽成 `_default_signal_scoring_context()` 函式（呼叫 `build_signal_scoring_context([], [], ...)` 而非手刻第二份「空殼長怎樣」的定義），避免兩處未來不同步。 |
| 13 | `generate_report.py` 主流程串接 | ✅ 最大也最關鍵的整合 task。除了 plan 文件既定的串接步驟，額外處理了兩個先前 review 就發現、記錄在待辦的設計問題：（a）法人資料的 `STOCK_DAY_ALL` API 被 `fetch_institutional_3day_ranking()` 和新的 `fetch_watchlist_institutional()` 各打一次，改成兩個函式都加上可選的「已預抓資料」參數，`generate_report.py` 只打一次、傳給兩邊共用；（b）「昨日選股回顧」勝率計算原本會用 `fetch_quotes()`（只涵蓋 4 檔台股）當報價來源，導致 65 檔觀察清單裡 61 檔會被誤判為「沒漲」，改成從已經抓到的 `watchlist_price_history` 自己算漲跌，涵蓋全部 65 檔。Review 又額外抓到一個：`build_signal_scoring_context()` 對非 dict 的 AI 輸出項目（例如 AI 直接輸出一個字串而不是物件）沒有防呆，補上 `isinstance` 檢查。 |
| 14 | 端到端人工驗證 | ✅ 用真實 yfinance/TWSE 資料跑過一次完整訊號計算（65 檔中 53 檔命中至少一項訊號，分數分布合理，非全 0 分也非全滿分）；驗證勝率回顧的首次執行、讀寫 round-trip 都正常；`pytest tests/ -v` 全過、無殘留檔案；用真實資料組出完整 context 渲染成 HTML，確認「今日觀察清單」表格與「昨日選股回顧」區塊都正確顯示、無殘留 Jinja 標記。 |

### 2. 三份 plan 的最終整體審查（finishing 前的最後一道關卡）

在把整個分支（63+ commits、涵蓋 Plan 1/2/3）視為一個整體重新審查時，抓到一個先前逐 task 審查沒發現的問題（因為它只有在「看整個檔案」而非「看單一 diff」時才會浮現）：

- **安全性問題（最嚴重）**：`scripts/report_render.py` 的 Jinja2 `Environment` 設定成 `autoescape=False`。原始架構設計（Plan 1）的意圖是「只有 3 個欄位（`ai_infra_html`／`lly_foundayo.extra_html`／`market_deep_dive_html`）信任 AI 直接輸出 HTML，其餘敘述欄位都應該是安全的純文字」，但因為 autoescape 整個關掉，這個信任邊界形同虛設——**所有**敘述欄位（新聞、主題卡片、風險矩陣、`stock_signal_reasons` 等）都沒有做 HTML escape。這些文字來自 AI 的 `web_search` 結果整理，若搜尋到的網頁內容帶有惡意標籤，AI 逐字引用後會原樣被發布到公開的 GitHub Pages 網站上。修正：改成 `autoescape=True`（確認過模板裡只有那 3 個地方用 `| safe`，沒有其他地方依賴「不 escape」這個行為），並補上迴歸測試鎖定這個安全邊界。
- 順手處理兩個較低優先的落差：`CLAUDE.md` 從 Plan 1 開始就沒更新過，還在描述「AI 產生整份 HTML」的舊架構，已重寫成符合現況的敘述；補了一個測試確認 `US_TO_TW_SUPPLY_CHAIN` 的美股代號都在 `US_HEATMAP_TICKERS` 清單裡（避免未來新增映射時漏掉對應熱力圖標的，訊號會靜默失效）。

### 3. 合併與發布

- 用 `superpowers:finishing-a-development-branch` skill 走完流程：確認 84/84 測試通過 → 使用者選擇「merge to main locally」→ fast-forward 合併（`bba5c9a..9e223e5`）→ 合併後的 main 再跑一次測試確認 84/84 通過 → 清掉 worktree 與 feature branch。
- 使用者確認後，額外把 `main` push 上 `origin/main`（`cc7ac7d..9e223e5`，之後又加了工作日誌 commit `288e785`）。

---

## 下一步（具體任務）

目前沒有已知的待辦事項——三份 plan 都已完成、審查、合併、推上遠端。可能的下一步方向（供參考，非既定任務）：

1. **觀察下一次 GitHub Actions 排程執行**（平日台灣時間 08:00）：這是新架構＋選股訊號系統第一次在正式排程環境（而非本機/測試）執行。重點觀察：
   - `data/stock_signals_history.json` 是否正確被 commit（`.github/workflows/daily-update.yml` 用 `git add -A`，理論上會抓到）
   - 65 檔觀察清單裡有 5 檔（5347 世界先進、3529 力旺、3324 雙鴻、6274 台燿、8299 群聯）在本機測試時 yfinance 抓不到資料（`possibly delisted`，很可能是 Yahoo Finance 對這幾檔小型股的資料涵蓋度問題，非本專案程式碼問題）——正式環境是否也一樣，若是的話評分系統長期只會用 60 檔而非 65 檔，屬已知且可接受的降級。
   - 每日報告的「今日觀察清單」與「昨日選股回顧」區塊在真正的 AI 生成敘述（而非本次測試用的假資料）搭配下呈現是否正常。
2. 若使用者對選股訊號評分系統有回饋（例如門檻值想調整、想加新訊號），可以再開新的 plan/task 處理。
3. `data/` 目錄會隨每日執行持續累積 `stock_signals_history.json` 的歷史紀錄（上限 30 天），屬預期行為，不需要人工介入。

---

## 相關檔案路徑

**本次對話修改的程式碼**（在 main 分支，已推上遠端）：
- `scripts/generate_report.py` — Task 9（JSON schema）、Task 13（主流程完整串接）
- `scripts/report_render.py` — Task 10（`build_signal_scoring_context()`）、Task 12（context 串接＋預設值 helper）、最終審查（`autoescape=True`）
- `scripts/data_fetchers.py` — Task 13 的 dedupe fix（`fetch_institutional_3day_ranking`/`fetch_watchlist_institutional` 新增可選預抓資料參數）
- `templates/report.html.j2` — Task 11（新增「今日觀察清單」＋「昨日選股回顧」區塊）
- `tests/conftest.py` — Task 13（5 個新 fetcher 的 stub）
- `tests/test_report_render.py`、`tests/test_signal_scoring.py`、`tests/test_data_fetchers.py` — 對應測試＋最終審查補的安全性/一致性迴歸測試
- `CLAUDE.md` — 最終審查更新，反映新架構
- `data/stock_signals_history.json` — 執行時才會產生（尚未在 repo 裡出現過，因為本機驗證都在測試沙盒或臨時資料夾跑）

**Spec / Plan 文件**（現在都在 main 分支）：
- `docs/superpowers/specs/2026-07-03-report-architecture-and-features-design.md`
- `docs/superpowers/plans/2026-07-03-report-architecture-rewrite.md`（Plan 1，已完成）
- `docs/superpowers/plans/2026-07-04-new-market-data-sections.md`（Plan 2，已完成）
- `docs/superpowers/plans/2026-07-04-stock-signal-scoring.md`（Plan 3，已完成）

**舊工作日誌**（同一資料夾，記錄 Task 1-8 的進度與中斷點）：
- [doc/工作日誌/2026-07-04-report-architecture-rewrite-worklog.md](2026-07-04-report-architecture-rewrite-worklog.md)

---

## 如何在新對話中接續

目前沒有進行中的分支或未完成的 task——如果開新對話，代表是要處理**新的需求**（例如調整選股訊號門檻、新增功能、修 bug），而不是接續本次的工作。可以直接告訴我新需求，我會視情況決定是否需要用 `brainstorming`／`writing-plans` 這類 skill 重新規劃。

若只是想確認正式環境跑得如何，可以請我檢查 GitHub Actions 執行紀錄或最新的 `index.html`／`data/stock_signals_history.json`。
