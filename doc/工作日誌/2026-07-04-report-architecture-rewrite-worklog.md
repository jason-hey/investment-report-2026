# 工作日誌：每日報告架構重寫 + 選股訊號評分系統

**日期：** 2026-07-04
**分支：** `worktree-report-architecture-rewrite`
**Worktree 路徑：** `E:\Users\Ken\Desktop\Projects\investment-report-2026\.claude\worktrees\report-architecture-rewrite`
**Main 分支狀態：** 完全未受影響，乾淨

---

## 整體目標

把每日報告產生流程從「AI 產生整份 100KB+ HTML」改成「Python 算好所有數字/圖表 → Jinja2 模板渲染 → AI 只負責寫敘述文字（JSON）」。

Spec：[docs/superpowers/specs/2026-07-03-report-architecture-and-features-design.md](../../docs/superpowers/specs/2026-07-03-report-architecture-and-features-design.md)（此路徑在 worktree 分支上）

共分三份計畫，用 **Subagent-Driven Development**（每個 task：implementer subagent → spec-compliance reviewer → code-quality reviewer 兩階段審查）執行：

| Plan | 內容 | 狀態 |
|---|---|---|
| Plan 1 | 架構重寫（模板 + JSON 資料分離，10 tasks） | ✅ 全部完成並已合併至此分支 |
| Plan 2 | 新市場資料區塊（韓股、美股熱力圖、板塊輪動、油價，9 tasks） | ✅ 全部完成並已合併至此分支 |
| Plan 3 | 台股當日選股訊號評分系統（14 tasks） | 🔄 進行中，見下方 |

---

## Plan 3 進度明細（`docs/superpowers/plans/2026-07-04-stock-signal-scoring.md`）

| Task | 內容 | 狀態 |
|---|---|---|
| 1 | `TW_STOCK_WATCHLIST`（65 檔精選台股）+ `US_TO_TW_SUPPLY_CHAIN` 映射表 | ✅ 完成 |
| 2 | `fetch_adr_premiums()`（ADR 溢價：TSM/UMC/ASX） | ✅ 完成 |
| 3 | `fetch_margin_trading()`（融資融券、軋空候選用） | ✅ 完成 |
| 4 | `fetch_monthly_revenue()`（月營收 YoY） | ✅ 完成 |
| 5 | `fetch_watchlist_institutional()`（法人買賣超 + 成交值比重） | ✅ 完成 |
| 6 | `fetch_watchlist_price_history()`（量價突破 + RS 相對強度用歷史資料） | ✅ 完成 |
| 7 | 8 項訊號計算函式 + `compute_signal_scores()` 綜合評分 | ✅ 完成 |
| 8 | 勝率回顧持久化（`data/stock_signals_history.json`） | ✅ 完成 |
| 9 | AI JSON schema 新增 `stock_signal_reasons` 欄位 | 🔄 **下次從這裡接續**（尚未開始實作，僅讀了現有 `generate_report.py` 的 schema 結構） |
| 10 | `build_signal_scoring_context()`（`scripts/report_render.py`） | ⏳ 未開始 |
| 11 | 模板新增「今日觀察清單」評分表 + 「昨日選股回顧」區塊 | ⏳ 未開始 |
| 12 | `build_template_context()` 串接 `signal_scoring` context key | ⏳ 未開始 |
| 13 | `generate_report.py` 主流程串接（含 `tests/conftest.py` stub 更新） | ⏳ 未開始（**有兩個已知的設計問題要在這個 task 一併處理，見下方「下次接續時要注意」**） |
| 14 | 端到端人工驗證（真實資料跑一次、確認 `pytest tests/ -v` 全過、瀏覽器視覺檢查） | ⏳ 未開始 |
| — | 三份 plan 全部完成後：整體 final review + `finishing-a-development-branch` 決定合併方式 | ⏳ 未開始 |

---

## 今天做了什麼（詳細）

沿用上一輪中斷點（Task 1 的 code quality review 被中斷），今天完整跑完 Task 1 的 review，並依序完成 Task 2~8，每個 task 都經過「implementer → spec-compliance reviewer → code-quality reviewer」兩階段審查，**審查中共抓到並修正了 9 個真實問題**（不是吹毛求疵的風格問題，是會影響數字正確性或讓每日排程崩潰的實質 bug）：

1. **Task 1**：清單文件寫「~100 檔」但實際只有 65 檔（文件與實際不符）、未使用的 import、「十铨」誤用簡體字（應為「十銓」）——已修正並補 commit。
2. **Task 2**：`ADR_TICKERS` 裡 ASX（日月光投控 ADR）的比例寫成 1:5，**經 WebSearch 查證 SEC 20-F 申報文件與 Nasdaq 掛牌頁面，正確比例是 1:2**（1:5 是 2003 年上市時的舊比例）。若不修正，ASX 的 ADR 溢價訊號會系統性錯誤約 2.5 倍。TSM、UMC 的 1:5 比例經查證仍正確。
3. **Task 3**：`fetch_margin_trading()` 內重複定義了跟 `_fetch_twse_t86()` 一模一樣的 `to_int()` helper，已抽成共用的 `_twse_to_int()`。
4. **Task 4**：`fetch_monthly_revenue()` 用 `dict.get(key, "")` 防呆，但這個寫法只在「key 不存在」時生效，TWSE 若回傳 `null` 值（例如新上市公司資料不全）會讓 `.strip()` 拋 `AttributeError`，被外層 `except` 吃掉後**靜默丟失當次整批資料**。已改用 `(row.get(key) or "")` 並補迴歸測試。
5. **Task 6**：`fetch_watchlist_price_history()` 把 Close 和 Volume 兩個欄位「各自」過濾 NaN，若 NaN 出現在不同列，會讓兩個 list 位置錯位（同一個 index 卻對應到不同交易日）。已改成逐列一起過濾（`zip` 後一起判斷），並補迴歸測試。這個問題被判定為「非理論風險」——這個檔案裡已經有 `_has_nan_close` 這個因為真實遇過 yfinance NaN 問題而加的既有防線可以佐證。
6. **Task 7**：`score_rs_rank_signal()` 對 `closes[-21]` 沒有做零值防呆，遇到停牌股或異常資料會 `ZeroDivisionError`，**讓整個每日排程在還沒產出任何報告前就崩潰**（比現有「HTML 驗證失敗就不發布」的機制還更早、更嚴重）。已加零值防呆。
7. **Task 7**：`score_us_supply_chain_signal()` 若同一檔台股被兩個不同美股觸發（例如 NVDA 跟 AMD 都對應到緯創 3231），後蓋前會悄悄丟失第一個觸發來源的說明文字，影響 Task 9 AI 寫的「入選理由」正確性。已改成把所有觸發來源串接起來。
8. **Task 8**：`load_signal_history()` 只防「JSON 語法錯誤」，沒防「格式對但形狀不對」（例如檔案是合法 JSON 但內容是 list 不是 dict）；`compute_win_rate_review()` 對手動可編輯的歷史檔案裡的 `pick["code"]` 做直接存取，缺欄位會讓整個回顧函式崩潰。已加 `isinstance(dict)` 檢查與 `.get()` 防呆，並補了 5 個先前完全沒有覆蓋到的測試（`total_picks==0`、缺 code、非 dict JSON、壞掉的 JSON、`record_todays_picks()` 的裁剪邏輯本身）。

所有修正都已個別 commit（commit 訊息說明了問題來源與修法），完整 commit 歷史見 `git log --oneline` on `worktree-report-architecture-rewrite` 分支。截至目前 `pytest tests/ -v` **72 個測試全過**。

---

## 下次接續時要注意（重要，避免遺漏）

在 Task 8 的 code quality review 中，reviewer 額外指出兩個**尚未修正、要在 Task 13（主流程串接）時一併處理**的設計層級問題，這兩點目前只是記錄在對話裡，**還沒寫進任何 commit 或檔案**，必須在開新對話後手動記得：

1. **重複的 STOCK_DAY_ALL 網路呼叫**：Task 5 新增的 `_fetch_twse_close_prices_and_value()` 跟既有的 `_fetch_twse_close_prices()`（被 `fetch_institutional_3day_ranking()` 使用）打的是同一個 TWSE endpoint。等 Task 13 把 `fetch_watchlist_institutional()` 也串進 `generate_report.py` 主流程後，同一次執行會打兩次一模一樣的 API——應該讓兩者共用同一次抓取結果，或把 `_fetch_twse_close_prices()` 改成呼叫 `_fetch_twse_close_prices_and_value()` 取第一個回傳值的薄包裝。
2. **勝率回顧的報價來源形狀不對**：`compute_win_rate_review()` 預期的 `quotes_by_code` 需要有 `"change"`／`"change_pct"` 欄位（`fetch_quotes()` 回傳的格式），但 `fetch_quotes()` 的 `QUOTE_TICKERS` 只涵蓋 4 檔台股代號（2330/2317/2454/0050），跟 Task 3 選股清單的 ~65 檔watchlist 差很多。若 Task 13 直接把 `fetch_quotes()` 的結果傳給 `compute_win_rate_review()`，65 檔裡只有 4 檔查得到報價，其餘 61 檔都會被當成「沒漲」而不是「無法判斷」，勝率會被嚴重低估。**Task 13 實作時必須另外抓一份涵蓋整個 watchlist 的當日報價**（可以重用 `fetch_watchlist_price_history()` 抓到的 closes 頭尾兩筆自己算漲跌，或另外呼叫一次涵蓋 watchlist 的報價函式），不能直接沿用 `fetch_quotes()`。

這兩點在 dispatch Task 13 implementer 時，務必把這兩個問題寫進 prompt 的 Context 段落，明確要求一併解決，不要只照抄 plan 文件裡的原始程式碼片段（plan 文件寫 plan 時還沒有 Task 5/8 的實作細節，所以沒考慮到這兩個問題）。

---

## 中斷點：Task 9 目前狀態

**尚未開始實作**，對話中斷前只做到「讀取現有 `scripts/generate_report.py` 了解現有 JSON schema 結構」這一步，讀到的關鍵資訊：

- `REQUIRED_JSON_FIELDS`（`scripts/generate_report.py:51-56`）目前內容：
  ```python
  REQUIRED_JSON_FIELDS = [
      "daily_brief", "header_pills", "data_validation", "hero_events",
      "warning_indicators", "night_session", "institutional_summary", "news",
      "ai_infra_html", "theme_cards", "strategy_cards", "risk_matrix_rows",
      "market_deep_dive_html", "lly_foundayo",
  ]
  ```
- `JSON_OUTPUT_SPEC`（給 AI 的 JSON 格式說明文字）從第 166 行開始，在第 293 行被組進 prompt。
- `validate_narrative_json()` 在第 337 行，邏輯是「缺哪些必要欄位就回傳哪些」。

Task 9 的規劃（`docs/superpowers/plans/2026-07-04-stock-signal-scoring.md`，Task 9 段落）要做的事：
1. 在 `REQUIRED_JSON_FIELDS` 加入 `"stock_signal_reasons"`。
2. 在 `JSON_OUTPUT_SPEC` 加一段欄位說明（放在 `institutional_summary` 附近）。
3. 在 prompt 裡新增一個「已預先抓取」區塊，把 `compute_signal_scores()` 算好的 `details` 傳給 AI，只要求 AI 把每檔股票的 `details` 陣列改寫成一句通順的話，**不要求 AI 自己判斷任何數字**（不新增額外的 Claude API 呼叫）。
4. 更新 `tests/test_generate_report.py` 既有的 `test_validate_narrative_json_lists_missing_fields`，確認新欄位有被動態抓進去。

**下一步（新對話開始後第一件事）**：直接對照 plan 文件的 Task 9 段落，dispatch 一個 implementer subagent 完成上述 4 點，然後照例跑 spec-compliance review → code-quality review 兩階段審查，通過後繼續 Task 10。

---

## 相關檔案路徑

**Spec / Plan 文件**（都在 worktree 分支，main 分支上沒有）：
- `docs/superpowers/specs/2026-07-03-report-architecture-and-features-design.md` — 整體設計 spec
- `docs/superpowers/plans/2026-07-04-stock-signal-scoring.md` — Plan 3 完整 14-task 計畫（**下次要看的主要文件**）
- `docs/superpowers/plans/2026-07-03-report-architecture-rewrite.md` — Plan 1（已完成）
- `docs/superpowers/plans/2026-07-04-new-market-data-sections.md` — Plan 2（已完成）

**程式碼**（本次 session 有修改的檔案）：
- `scripts/signal_scoring.py` — 選股清單、映射表、8 項訊號函式、勝率持久化（Task 1-8 都在這裡）
- `scripts/data_fetchers.py` — 5 個新增的資料抓取函式（Task 2-6）+ 共用的 `_twse_to_int()`
- `tests/test_signal_scoring.py` — 對應測試
- `tests/test_data_fetchers.py` — 對應測試

**下次會動到的檔案**（Task 9 起）：
- `scripts/generate_report.py` — Task 9（JSON schema）、Task 13（主流程串接）
- `scripts/report_render.py` — Task 10（`build_signal_scoring_context()`）、Task 12（串接）
- `templates/report.html.j2` — Task 11（模板區塊）
- `tests/conftest.py` — Task 13（fetcher stub 更新）
- `data/stock_signals_history.json` — Task 13 執行時才會產生，目前 repo 裡還不存在

**舊工作日誌**（worktree 內，未 commit，僅供參考，本檔案是它的更新版）：
- `.claude/worktrees/report-architecture-rewrite/doc/2026-07-04-work-log-report-architecture-rewrite.md`

---

## 如何在新對話中接續

1. 開新對話後，先確認還在同一個 worktree：`cd "E:\Users\Ken\Desktop\Projects\investment-report-2026\.claude\worktrees\report-architecture-rewrite"`，`git status` 確認分支是 `worktree-report-architecture-rewrite` 且乾淨。
2. 讀 `docs/superpowers/plans/2026-07-04-stock-signal-scoring.md` 的 Task 9 段落（完整程式碼片段都在裡面）。
3. 用 `superpowers:subagent-driven-development` skill 的流程（implementer → spec review → code quality review）繼續做 Task 9 ~ 14。
4. **務必記得**上面「下次接續時要注意」的兩點，在 Task 13 一併處理。
5. Task 14（端到端驗證）跑完、且 Task 9-14 都通過審查後，做一次涵蓋全部三份 plan 的 final review，再用 `superpowers:finishing-a-development-branch` 決定合併方式（目前 main 分支乾淨未受影響）。
