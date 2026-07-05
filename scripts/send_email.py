"""Email 通知 — 支援多個收件人（NOTIFY_EMAIL 用逗號分隔）"""
import os, smtplib
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

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


def main():
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
