"""Email 通知（Gmail 備用方案）"""
import os, smtplib
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

TZ_TW = timezone(timedelta(hours=8))
today  = datetime.now(TZ_TW)
date_str = today.strftime("%Y/%m/%d")

repo     = os.environ.get("GITHUB_REPOSITORY", "jason-hey/investment-report-2026")
owner    = repo.split("/")[0]
repo_name= repo.split("/")[1]
url      = f"https://{owner}.github.io/{repo_name}/"

subject = f"📊 {date_str} 投資情報已更新"
body = f"""
{date_str} 每日投資情報已自動生成完成！

🔗 查看報告：{url}

⚡ 自動生成 by Claude AI + GitHub Actions
"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = subject
msg["From"]    = os.environ["GMAIL_USER"]
msg["To"]      = os.environ["NOTIFY_EMAIL"]

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
    server.send_message(msg)
    print("  ✅ Email 已發送")
