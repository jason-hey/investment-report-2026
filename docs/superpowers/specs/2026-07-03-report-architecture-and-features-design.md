# 每日報告架構重寫 + 新功能規劃（設計文件）

日期：2026-07-03
狀態：已與使用者確認，待轉為實作計畫

## 背景

本文件整合兩份既有分析／規劃文件中「尚未實作」的項目，統一設計成一次性的重構＋擴充：

- [doc/2026-07-03-improvement-analysis.html](../../../doc/2026-07-03-improvement-analysis.html) 的 #1（模板＋JSON 資料分離）與 #12（通知內容加值）
- [doc/2026-07-03-stock-signal-plan.html](../../../doc/2026-07-03-stock-signal-plan.html) 全文（台股當日選股訊號評分表）
- [doc/2026-07-03-Todo list/Todo list](../../../doc/2026-07-03-Todo%20list/Todo%20list) 中尚未完成的 4 項：韓國股市、美股熱力圖、美股資金板塊、油價走勢圖

已完成、不在本次範圍內的項目：LINE 群組通知、自動觸發發布（schedule + workflow_dispatch）、改善分析文件的 #2/#3/#4/#5/#6/#7/#8/#9/#10/#11。

## 範圍與優先順序

使用者選擇「全部一次做完，不分批」。實作順序依相依關係排列：

1. 架構重寫（A）— 其他新功能都要建立在新架構之上
2. 新資料區塊（B）與通知強化（D）— 依附在新架構的模板機制上
3. 選股訊號評分系統（C）— 量體最大、資料來源最多，放最後

雖然一次做完不分批驗收，實作時每個子項目仍各自獨立 commit，方便追蹤與回溯。

## A. 架構重寫：模板 + JSON 資料分離

### 問題

現行 `scripts/generate_report.py` 每天要求 Claude 生成完整的 100KB+ HTML（含所有 CSS/JS/Chart.js 設定）。版面可能每天長得不一樣、JS 有機會寫壞、輸出 token 消耗大。

### 決策：數字與圖表全部由 Python 計算，敘述性文字仍由 AI 負責

- **Python 負責**：所有可從已預抓資料計算出的數字與圖表設定 —— P/E 走勢、法人排行、ADR 溢價、產業輪動、熱力圖、油價走勢、選股評分表等，直接算成 Chart.js 設定與表格資料，注入模板。
- **AI 負責**：敘述性內容 —— 新聞解讀、策略總結、風險矩陣文字說明、主題卡片文字，以及新增的 `daily_brief`（2–3 行摘要，供通知使用）。這部分仍用現有的 streaming + `pause_turn` + `web_search` 迴圈，但 prompt 大幅縮小（只要求 JSON，不要求完整 HTML）。
- **AI 回傳格式**：結構化 JSON（例如 `{"news_items": [...], "strategy_summary": "...", "risk_matrix_notes": {...}, "theme_cards": [...], "daily_brief": "..."}`），取代目前用 regex 從 ` ```html ``` ` fence 抓 HTML 的做法。

### 模板技術：Jinja2

新增 `templates/report.html.j2`，取代「AI 生成整份 HTML」。此模板固定版面（ticker 跑馬燈、hero banner、五項警示指標、KPI 儀表板、Chart.js 圖表、財報日曆、新聞分頁、風險矩陣、主題卡片、策略總結區），並新增 B、C 兩節要用到的區塊。Jinja2 相較純字串樣板的優勢：對「筆數不固定」的清單（新聞項目、財報日曆列、熱力圖格子、選股評分列）能用迴圈/條件式處理，可讀性與可維護性都比手刻字串拼接高。

### 檔案拆分

現行 `scripts/generate_report.py` 已 700+ 行，且即將再新增大量資料抓取邏輯，故拆分為：

| 檔案 | 職責 |
|---|---|
| `scripts/data_fetchers.py` | 所有 yfinance / TWSE OpenAPI / MOPS 預抓函式（既有 + 新增） |
| `scripts/signal_scoring.py` | 選股訊號評分邏輯 + 勝率歷史紀錄讀寫 |
| `templates/report.html.j2` | 報告模板 |
| `scripts/generate_report.py` | 純協調：呼叫 fetchers → 呼叫 Claude 取得敘述 JSON → 渲染模板 → 驗證 → 寫檔 |

### 驗證與錯誤處理

發布前驗證邏輯維持現行做法（`validate_html`：最小長度、`</html>` 結尾、`<table`/`<canvas`/`<script` 存在），但驗證對象改為「渲染後的最終 HTML」而非「AI 直接輸出的 HTML」。若 AI 回傳的 JSON 缺少必要欄位（例如 `daily_brief` 或 `news_items`），視為生成失敗，比照現行「不合格就 raise、不發布」的原則處理，不做欄位層級的容錯退化（避免半份資料悄悄上線）。

## B. 新資料區塊

四項全部由 Python 用 yfinance 免費資料算出，不經過 AI／web_search，注入新模板區塊：

| 項目 | 資料來源 | 內容 |
|---|---|---|
| 韓國股市 | yfinance：`^KS11`（KOSPI）+ 三星電子、SK 海力士 | 指數與大股當日漲跌 |
| 美股熱力圖 | yfinance：固定 ~40 檔美股清單 | 依當日漲跌 % 著色的格狀熱力圖 |
| 美股資金板塊輪動 | yfinance：11 檔 SPDR 產業 ETF（XLK/XLF/XLE...） | 當日 + 一週表現，作為資金輪動代理指標 |
| 油價走勢 | yfinance：WTI（`CL=F`）、Brent（`BZ=F`） | 走勢圖（比照現有 VIX 走勢圖做法） |

## C. 台股當日選股訊號評分系統

### 選股清單範圍

固定精選約 100 檔台股（涵蓋規劃文件中提到的供應鏈：台積電供應鏈、AI 伺服器、蘋果概念、記憶體、金融），寫死維護在 `signal_scoring.py`。刻意不掃描全市場，理由：控制 yfinance 呼叫量與執行時間、避免不穩定。

### v1 評分項目（全部使用本專案已驗證過的資料來源，不做需要爬蟲的項目）

1. ADR 溢價（TSM/UMC/ASX 對應台股，用 yfinance 換匯計算）
2. 美股族群 → 台股供應鏈映射（寫死對照表，依當日美股漲跌點亮對應台股）
3. 外資＋投信同步買超（延伸既有 `fetch_institutional_3day_ranking` 的 TWSE OpenAPI 資料源，計算交集）
4. 買超金額 ÷ 當日成交值比重（取代絕對金額排序）
5. 券資比偏高 + 股價轉強（軋空候選，TWSE OpenAPI 融資融券資料集）
6. 月營收創新高 / YoY 大增（TWSE OpenAPI 月營收資料集）
7. 量價齊揚突破（20 日新高 + 成交量 > 5 日均量 1.5 倍，yfinance 日線計算）
8. 相對強度 RS 排名（近 20 日漲幅 − 加權指數 `^TWII` 漲幅）

**延後項目**：法說會日程 — MOPS 沒有乾淨的 JSON API，需要網頁爬取，穩定性風險高，v1 不做，記錄為未來工作。

### 呈現方式

「今日觀察清單」綜合評分表：每檔股票列出命中哪些訊號、命中數、一行「為什麼」文字摘要（此摘要文字由 AI 依據 Python 算好的命中結果撰寫，不需要 AI 自己判斷數字）。

### 勝率回顧（持久化機制）

- 新增 `data/stock_signals_history.json`，隨每日報告一起 commit。
- 結構：以日期為 key，記錄當天入選清單（股票代號、得分、命中訊號）。
- 每次執行時：讀取「前一交易日」的入選清單 → 用 yfinance 抓這些股票「今天」的實際漲跌 → 算出命中率，呈現在報告的「昨日選股回顧」區塊，並累積歷史勝率統計（例如近 20 個交易日整體命中率）→ 再把「今天」新入選的清單寫回 JSON，供下次執行使用。

## D. 通知內容強化（實作計畫階段發現：此項已完成，範圍縮減為「搬遷」）

寫這份 spec 時參考的是 `doc/2026-07-03-improvement-analysis.html` 文字描述（#12：通知只有連結），但實際檢視現行程式碼（commit `8f1fc57`）發現這項已經做了：`generate_report.py` 目前會從 AI 輸出的 HTML 裡用 `<!--SUMMARY ... SUMMARY-->` 註解 regex 抓出 2–3 行摘要，透過 `GITHUB_OUTPUT` 傳給 workflow，Telegram / LINE / Email 三個通知步驟都已經會把摘要接在訊息最前面（見 `daily-update.yml` 第 62–130 行、`send_email.py` 第 19–26 行）。

因此 D 不需要新增功能，只需要在 A 的架構改動中把「摘要來源」從 regex-on-HTML-comment 改成「直接讀 AI 回傳 JSON 的 `daily_brief` 欄位」，`GITHUB_OUTPUT` 寫入邏輯與 workflow 端完全不動。

## 測試與驗證方式

- 本機用 `DATE_OVERRIDE=YYYY-MM-DD python scripts/generate_report.py` 對過去幾個不同交易日（含台股休市日、財報密集日）跑過，確認：
  - 模板渲染出的 HTML 通過現行 `validate_html` 檢查
  - 新增的四個資料區塊（韓國、熱力圖、板塊輪動、油價）數字正確、圖表能畫出來
  - 選股評分表在有/沒有前一日歷史紀錄兩種情況下都不會出錯（第一次執行時 `data/stock_signals_history.json` 是空的）
  - 通知訊息（本機模擬 workflow 讀檔邏輯）能正確帶出 `daily_brief`
- 因為是取代目前正式在跑的每日 pipeline，實作完成後建議先在獨立分支上人工跑過至少一次完整流程，確認輸出網頁在瀏覽器中正常呈現，再合併。

## 開放風險（已知，不阻擋開發）

- TWSE OpenAPI 的融資融券、月營收資料集欄位格式需要在實作時實際查驗（現有程式碼只驗證過三大法人買賣超資料集的格式）。
- Jinja2 需新增為專案相依套件（`requirements.txt`），需鎖版本比照現有做法。
- 選股評分系統的「命中原因」文字仍需要一次 AI 呼叫（在敘述 JSON 內一併處理，不額外增加 API 呼叫次數）。
