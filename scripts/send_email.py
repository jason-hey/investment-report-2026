"""Email 通知 — 支援多個收件人（NOTIFY_EMAIL 用逗號分隔）"""
import os, smtplib, sys
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

# 跟 scripts/generate_report.py 同樣的原因：本檔案用「python scripts/send_email.py」
# （repo 根目錄執行）啟動時，sys.path[0] 會是 scripts/ 而非 repo 根目錄，
# 底下的 `from scripts.failure_alert import ...` 會找不到 scripts 這個套件。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.failure_alert import build_failure_message

TZ_TW = timezone(timedelta(hours=8))


def build_email():
    """組出 (subject, body, recipients)。日期優先採用 DATE_OVERRIDE（跟
    generate_report.py 同一套規則）：手動補跑歷史日期時，通知顯示的日期要跟
    報告內容一致，不能永遠顯示「今天」。"""
    if os.environ.get("DATE_OVERRIDE"):
        today = datetime.strptime(os.environ["DATE_OVERRIDE"], "%Y-%m-%d").replace(tzinfo=TZ_TW)
    else:
        today = datetime.now(TZ_TW)
    date_str = today.strftime("%Y/%m/%d")

    repo     = os.environ.get("GITHUB_REPOSITORY", "jason-hey/investment-report-2026")
    owner    = repo.split("/")[0]
    repo_name= repo.split("/")[1]
    url      = f"https://{owner}.github.io/{repo_name}/"

    # 支援多個收件人：NOTIFY_EMAIL = "a@gmail.com,b@gmail.com,c@company.com"
    recipients_raw = os.environ["NOTIFY_EMAIL"]
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    summary = os.environ.get("SUMMARY", "").strip()
    summary_block = f"{summary}\n\n" if summary else ""

    subject = f"📊 {date_str} 投資情報已更新"
    body = f"""
{date_str} 每日投資情報已自動生成完成！

{summary_block}🔗 查看報告：{url}

⚡ 自動生成 by Claude AI + GitHub Actions
"""
    return subject, body, recipients


def build_failure_email(log_text: str, run_url: str):
    """組出 pipeline 失敗通知信的 (subject, body, recipients)。內文跟 Telegram/LINE
    共用同一套錯誤分類邏輯（scripts/failure_alert.py），避免三個通知管道各寫一份、
    分類結果不一致。"""
    recipients_raw = os.environ["NOTIFY_EMAIL"]
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    subject = "⚠️ 投資情報 pipeline 執行失敗"
    body = build_failure_message(log_text, run_url)
    return subject, body, recipients


def main():
    if os.environ.get("NOTIFY_MODE") == "failure":
        log_path = os.environ.get("GENERATE_LOG_PATH", "")
        log_text = ""
        if log_path and os.path.exists(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as f:
                log_text = f.read()
        subject, body, recipients = build_failure_email(log_text, os.environ.get("RUN_URL", ""))
    else:
        subject, body, recipients = build_email()

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = os.environ["GMAIL_USER"]
    msg["To"]      = ", ".join(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg, to_addrs=recipients)
        print(f"  ✅ Email 已發送給 {len(recipients)} 位收件人：{recipients}")


if __name__ == "__main__":
    main()
