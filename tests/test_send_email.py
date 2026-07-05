"""
scripts/send_email.py 的單元測試。

前提：send_email.py 必須是「可安全 import」的模組（發信動作放在 main() 並用
`if __name__ == "__main__":` 保護），否則 import 當下就會嘗試連 Gmail SMTP。
"""
from datetime import datetime, timezone, timedelta


def test_build_email_uses_date_override_when_set(monkeypatch):
    """
    迴歸測試：手動用 date_override 補跑過去某天的報告時，Email 通知顯示的日期
    原本永遠是「今天」，跟報告內容的日期不一致。build_email() 要優先採用
    DATE_OVERRIDE 環境變數（跟 generate_report.py 同一套規則）。
    """
    monkeypatch.setenv("DATE_OVERRIDE", "2026-06-16")
    monkeypatch.setenv("NOTIFY_EMAIL", "a@example.com, b@example.com")
    monkeypatch.setenv("SUMMARY", "測試摘要內容")

    from scripts.send_email import build_email

    subject, body, recipients = build_email()
    assert "2026/06/16" in subject
    assert "2026/06/16" in body
    assert recipients == ["a@example.com", "b@example.com"]
    assert "測試摘要內容" in body


def test_build_email_defaults_to_today_without_override(monkeypatch):
    monkeypatch.delenv("DATE_OVERRIDE", raising=False)
    monkeypatch.delenv("SUMMARY", raising=False)
    monkeypatch.setenv("NOTIFY_EMAIL", "a@example.com")

    from scripts.send_email import build_email

    subject, _body, recipients = build_email()
    today_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y/%m/%d")
    assert today_str in subject
    assert recipients == ["a@example.com"]
