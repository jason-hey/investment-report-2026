# 工作日誌：帳單額度中斷復原、失敗通知升級、AI 產生區塊文字對比度修正

**日期：** 2026-08-04（週二）
**狀態：** ✅ 主要問題已修復並推上 GitHub（commit `cf8971d` → `b7d0d7e` → `2e5aea2`）；⚠️ Email 通知待使用者手動清除 GitHub secret 才會真正暫停；⚠️ prompt 修正尚未經過真實排程驗證

---

## 目前進度（詳細說明）

### 1. 起因：接續上次對話，發現 pipeline 已停擺 12 天

對話從「我上次做到哪」開始。上次（2026-07-05）的日誌結尾是「等 2026-07-07 排程驗證」，但本機分支落後 origin 11 個 commit，且從 GitHub Actions API 查出：**排程從 2026-07-22 起，之後每一次執行（排程與手動）全部失敗**，直到今天都沒有再發布新報告。

用使用者貼出的 Actions log 找到真正原因：

```
anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error':
{'type': 'invalid_request_error', 'message': 'Your credit balance is too
low to access the Anthropic API. Please go to Plans & Billing to upgrade
or purchase credits.'}}
```

**Anthropic API 帳戶額度用完**——不是程式碼問題。所有 Python 資料抓取（yfinance/TWSE/VIX/熱力圖/產業輪動/油價/選股訊號）都成功，只有呼叫 Claude API 寫敘述文字那一步失敗。排除了「`claude-sonnet-4-6` 模型已棄用」的假設（用 `claude-api` skill 查證，該模型目前仍是 active 的 legacy 模型，只是不是最新款）。

使用者去 console.anthropic.com 儲值後，排程恢復正常，成功產出 2026-08-04 報告（commit `d3ca7ea`）。

### 2. 失敗通知升級：加上錯誤分類，不用再翻 Actions log（commit `cf8971d`）

在等待使用者處理帳單期間，先把「失敗時怎麼知道原因」這件事修好：

- 新增 `scripts/failure_alert.py`：從 `generate_report.py` 執行時的 log 文字比對已知錯誤類型（額度不足／速率限制／金鑰失效／服務過載／權限不足），組出「分類標籤 + 錯誤片段 + 執行紀錄連結」的通知內容。Telegram/LINE/Email 三邊共用同一套邏輯。
- `scripts/send_email.py` 新增 `build_failure_email()`，`main()` 依 `NOTIFY_MODE=failure` 切換——原本失敗時完全不會發 Email，現在會了。
- `.github/workflows/daily-update.yml`：「Generate report」step 改用 `tee` 把輸出同時寫進 `generate_report.log`；「Send failure alert」step 讀這份 log 分類後組訊息。
- 新增 `tests/test_failure_alert.py`、擴充 `tests/test_send_email.py`。**這批測試只用手動推演邏輯驗證過，本機沒有真的 Python 環境可以跑 `pytest`**（`python`/`python3` 在這台機器上只是 Windows Store 空殼，不是真正的直譯器）——建議找機會在有 Python 的環境跑一次 `pytest tests/test_failure_alert.py tests/test_send_email.py -v` 確認全過。
- 推送後用 GitHub API 確認 workflow `state: active`，語法沒有重蹈 2026-07-05 那次 YAML 縮排錯誤的覆轍。

### 3. AI 產生區塊文字對比度失敗（commit `b7d0d7e`）

使用者貼出截圖：「三地市場深度分析」區塊裡的美股分析、韓股分析表格，數值文字幾乎看不見（淺色字疊淺色/白色背景）。

根因：`market_deep_dive_html` / `ai_infra_html` / `lly_foundayo.extra_html` 這三個欄位是 AI 直接產生原始 HTML（模板裡標記 `| safe` 直接嵌入頁面），prompt 對格式的要求只有一句模糊的「沿用你過去產出這個區塊時的既有格式規則」。因為 AI 每次都是空白 context 重新生成，並沒有真正的「過去」可循，這次它輸出了白底卡片卻沒設文字顏色，文字繼承了頁面深色主題的預設淺色文字 → 疊在自己設的白色卡片背景上，完全看不到。

除了使用者截圖的兩個表格，**主動排查了另外兩個 `| safe` 注入點**，抓到同一類問題的另一種形式：「AI 基礎建設驗證指標」與「Foundayo 商業化深度分析」這兩個標題，設了深色文字（`color:#1e293b`）但外層沒設背景（等於直接露出頁面深色底）→ 深字疊深底，同樣看不見。

修正：
- **已發布頁面**（`index.html` + `Backup/2026-08-04.html`）：三地市場深度分析區塊的外層容器補上 `color:#1e293b`（讓所有沒自己設色的子元素正確繼承）；兩個標題的文字色從深色改成淺色。
- **未來報告的 prompt**（`scripts/generate_report.py` 的 `JSON_OUTPUT_SPEC`）：把模糊的「沿用既有格式規則」換成明確的「HTML 格式規則」區塊，給死深色主題色碼表（卡片背景/文字色、漲跌色、信心徽章色、表格配色），並明訂「最外層容器必須同時設定 background 與 color，不可只設一個」「絕對不可用白色/淺色卡片背景」。
- 存了一筆 feedback 記憶（`feedback_ai_html_contrast.md`）：以後遇到這類問題要主動檢查全部 3 個 `| safe` 注入點，不只修使用者回報的那一處。

**⚠️ 尚未驗證**：這個 prompt 修正還沒有真的被 AI 執行過一次——上次成功生成（`d3ca7ea`）是修正 prompt「之前」的產物，index.html 裡看到的正確效果是我**手動修補**的，不是 AI 照新規則生成的。第一次真正的驗證要等下一次排程重新呼叫 Claude API。

### 4. Email 失敗通知本身也失敗：Gmail 憑證過期（commit `2e5aea2`）

使用者貼出 run #75（就是產生 2026-08-04 報告那次手動觸發）的 log：Email 登入被拒 `535 Username and Password not accepted`。查證：

- 報告本身生成、發布都成功，Telegram/LINE 通知也都成功送達。
- 真正壞掉的是 `GMAIL_APP_PASSWORD` 這組 Gmail App Password——已失效/被撤銷，導致「Send Email notification」（平常會發的成功信）先失敗。
- 觸發「Send failure alert」後，**新加的失敗通知 Email 用同一組壞掉的憑證再送一次，也失敗**，導致「Send failure alert」這個 step 本身也被標記失敗，蓋掉了「Telegram/LINE 其實都成功送達」這個事實。

修正：把失敗通知裡的 Email 呼叫改用 `|| echo "::warning::..."` 包起來，寄信失敗只印警告，不會讓整個 step 的結束碼被「寄信本身失敗」重新定義。

### 5. 使用者要求暫停 Email 通知

沒有改程式碼——現有 workflow 本來就會在 `GMAIL_USER`/`GMAIL_APP_PASSWORD` 這兩個 secret 不存在時自動跳過所有 Email 步驟（成功信與失敗信都是）。請使用者自己到 **repo → Settings → Secrets and variables → Actions** 刪除 `GMAIL_APP_PASSWORD`（或 `GMAIL_USER`）。**這一步使用者當下還沒做**，只是說要自己去做。

---

## 下一步（具體任務）

1. **（使用者待辦，不是 Claude 待辦）到 GitHub 刪除 `GMAIL_APP_PASSWORD`（或 `GMAIL_USER`）secret**，真正暫停 Email 通知。日後想恢復：去 [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) 重新產生一組 App Password，更新回這個 secret 即可，不需要再改程式碼。
2. **觀察下一次排程執行**（下一個平日台灣時間 08:00）：這是本次修正後第一次真正的完整驗證，要確認：
   - 報告正常生成、發布到 [GitHub Pages](https://jason-hey.github.io/investment-report-2026/)
   - 「三地市場深度分析」「AI 基礎建設驗證指標」「Foundayo 商業化深度分析」這三個 AI 產生的區塊，文字對比度是否正常——**這是新 prompt 規則第一次真正被 AI 執行**，如果 AI 沒有照規則做（換句話說，模糊指示換成明確色碼表還是沒有完全解決 drift 問題），需要考慮更強硬的做法（例如在 template 裡加 CSS 防禦性 fallback，或把這三個欄位拆成結構化欄位而不是讓 AI 直接寫 HTML——`generate_report.py` 裡本來就有一段註解在討論這個取捨）
   - Email 通知確認不再發送（如果使用者已完成待辦事項 1）
   - Telegram/LINE 通知是否正常送達
3. **找機會在有真正 Python 環境的地方跑一次完整測試**：`pytest tests/ -v`，尤其確認今天新增的 `tests/test_failure_alert.py` 與 `tests/test_send_email.py` 新案例全過（本機這台機器沒有真的 Python 直譯器，今天的測試只靠手動邏輯推演驗證，沒有實際執行過）。
4. 若下次排程失敗：新的失敗通知（Telegram/LINE，若 Email 已停用則不含 Email）應該會直接顯示分類後的錯誤原因，不用再翻 Actions log。

---

## 相關檔案路徑

**本次修改（commit `cf8971d` → `b7d0d7e` → `2e5aea2`，皆已推上遠端）：**
- `scripts/failure_alert.py`（新檔）— 失敗原因分類（額度不足／速率限制／金鑰失效／服務過載／權限不足）+ 通知訊息組裝
- `scripts/send_email.py` — 新增 `build_failure_email()`、`main()` 依 `NOTIFY_MODE=failure` 切換
- `.github/workflows/daily-update.yml` — Generate report 用 `tee` 留 log；Send failure alert 讀 log 分類、新增失敗 Email、失敗 Email 本身失敗不再連坐整個 step
- `scripts/generate_report.py` — `JSON_OUTPUT_SPEC` 新增「HTML 格式規則」區塊（深色主題色碼表，取代模糊的「沿用既有格式規則」）
- `index.html`、`Backup/2026-08-04.html` — 手動修補三處對比度失敗（三地市場深度分析外層容器補 `color`；AI 基礎建設驗證指標、Foundayo 商業化深度分析兩個標題文字色改淺）
- `tests/test_failure_alert.py`（新檔）、`tests/test_send_email.py` — 對應測試（**尚未實際執行過，只有手動推演**）

**記憶（本次新增，`~/.claude/projects/.../memory/`）：**
- `feedback_ai_html_contrast.md` — 提醒以後要主動檢查全部 3 個 `| safe` 注入點，不只修使用者回報的那一處

**待使用者操作（不是程式碼變更）：**
- GitHub repo Settings → Secrets and variables → Actions → 刪除 `GMAIL_APP_PASSWORD`（暫停 Email 通知）

---

## 如何在新對話中接續

- 若是**下次排程後的檢查**：請 Claude 檢查最新 GitHub Actions 執行紀錄、`index.html`，重點確認「三地市場深度分析」等三個 AI 產生區塊的文字對比度是否正常（新 prompt 規則第一次實戰驗證），以及 Email 通知是否確實沒有發送。
- 若**對比度問題又出現**：代表 prompt 層級的規則不夠強，需要考慮 template CSS 防禦性 fallback 或把這三個欄位改成結構化欄位（`generate_report.py` 檔案內有相關取捨的註解可參考）。
- 若使用者**已經去 Google 重新申請 App Password 想恢復 Email**：確認新密碼已更新到 `GMAIL_APP_PASSWORD` secret 即可，不需要改程式碼。
- 若是**新需求**：直接描述，視情況重新規劃。
