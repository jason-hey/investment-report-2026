# Investment Report Automation

每日自動生成投資情報 HTML，部署至 GitHub Pages，並通知 Telegram / Email。

## 三件事，技術上分別怎麼做

### ① 每天 8:00 自動更新內容
GitHub Actions cron job：`0 0 * * 1-5`（UTC 00:00 = 台灣 08:00，週一至週五）
觸發 `generate_report.py` 呼叫 Claude API + web_search，重新生成 `index.html`。

### ② 自動發佈到網路
`git push` 後，GitHub Pages 會自動偵測 `index.html` 變更並重新部署。
**網址永遠不變**：`https://jason-hey.github.io/investment-report-2026/`
不需要每天發新網址，同一個網址內容每天更新。

### ③ 自動通知（你自己 + 其他人）
- **Telegram**：傳送給 `TELEGRAM_CHAT_ID` 指定的單一聊天室/群組
- **Email**：`NOTIFY_EMAIL` 可填多個地址，用逗號分隔即可群發
  例：`NOTIFY_EMAIL = "jason@gmail.com,colleague@company.com,friend@gmail.com"`

---

## 設定步驟

### 1. 上傳到 GitHub
把此資料夾所有內容放進 `jason-hey/investment-report-2026` repo 根目錄。

### 2. 設定 Secrets（Settings → Secrets and variables → Actions）

| Secret | 說明 | 必填 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API 金鑰 | ✅ |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 可選 |
| `TELEGRAM_CHAT_ID` | 接收通知的 Chat ID | 可選 |
| `GMAIL_USER` | Gmail 帳號 | 可選 |
| `GMAIL_APP_PASSWORD` | Gmail 16位應用程式密碼 | 可選 |
| `NOTIFY_EMAIL` | 收件人（可逗號分隔多人）| 可選 |

兩種通知方式可同時啟用，沒設定的會自動跳過。

### 3. 啟用 GitHub Pages
`Settings → Pages → Source: Deploy from branch → main / (root)`

### 4. 開啟 Actions 寫入權限
`Settings → Actions → Workflow permissions → Read and write`

---

## 報告網址（固定不變）
`https://jason-hey.github.io/investment-report-2026/`

## 執行時間
週一至週五 台灣時間 **08:00**（UTC 00:00）

## 手動觸發測試
`Actions → Daily Investment Report → Run workflow`
可輸入 `date_override`（格式 `2026-06-16`）測試特定日期，留空則用今天。
