# Investment Report Automation

每日自動生成投資情報 HTML，部署至 GitHub Pages，並傳送 LINE / Email 通知。

## 設定步驟

### 1. 上傳到 GitHub
把此資料夾的所有內容放進你的 repo：`jason-hey/investment-report-2026`

### 2. 設定 Secrets（Settings → Secrets → Actions）

| Secret | 說明 | 必填 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 金鑰 | ✅ |
| `LINE_NOTIFY_TOKEN` | LINE Notify Token（見下方取得方式）| 二選一 |
| `GMAIL_USER` | Gmail 帳號 | 二選一 |
| `GMAIL_APP_PASSWORD` | Gmail 應用程式密碼 | 二選一 |
| `NOTIFY_EMAIL` | 收件人 Email | 搭配 Gmail 用 |

### 3. 啟用 GitHub Pages
Settings → Pages → Deploy from branch: `main` / `(root)`

### 4. 開啟 Actions 寫入權限
Settings → Actions → Workflow permissions → Read and write

---

## 取得 LINE Notify Token（5 分鐘完成）

1. 前往 https://notify-bot.line.me/my/
2. 登入 LINE 帳號
3. 點「Generate token」
4. 選擇通知目標：「1-on-1 chat with LINE Notify」（個人通知）
5. 複製 Token
6. 在 GitHub repo Secrets 貼上為 `LINE_NOTIFY_TOKEN`

---

## 報告網址
`https://jason-hey.github.io/investment-report-2026/`

## 執行時間
台灣時間週一至週五 早上 07:30（UTC 23:30 前一天）

## 手動觸發
GitHub → Actions → Daily Investment Report → Run workflow
可以輸入 `date_override`（格式 2026-06-05）測試特定日期
