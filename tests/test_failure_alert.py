"""
scripts/failure_alert.py 的單元測試。

背景：pipeline 失敗時（.github/workflows/daily-update.yml 的「Send failure alert」
step）原本的 Telegram/LINE/Email 通知只有一句「請檢查執行紀錄」+ Actions 連結，
看不出是哪種錯誤（額度不足／速率限制／金鑰失效……），每次都要點進 Actions 網頁
翻 log 才知道。這裡把「從 log 文字分類錯誤原因＋組出通知訊息」抽成純函式，方便
在 Telegram/LINE（純文字）與 Email（send_email.py）共用同一套分類邏輯。
"""
from scripts.failure_alert import (
    build_failure_message,
    classify_error,
    extract_error_snippet,
)


def test_classify_error_recognizes_low_credit_balance():
    log = (
        "anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': "
        "{'type': 'invalid_request_error', 'message': 'Your credit balance is too "
        "low to access the Anthropic API. Please go to Plans & Billing to upgrade "
        "or purchase credits.'}}"
    )
    assert "額度不足" in classify_error(log)


def test_classify_error_recognizes_rate_limit():
    log = "anthropic.RateLimitError: Error code: 429 - {'type': 'rate_limit_error', ...}"
    assert "速率限制" in classify_error(log)


def test_classify_error_recognizes_authentication_error():
    log = "anthropic.AuthenticationError: Error code: 401 - {'type': 'authentication_error', ...}"
    assert "金鑰" in classify_error(log)


def test_classify_error_falls_back_to_generic_label_for_unknown_errors():
    log = "Traceback (most recent call last):\nValueError: something unexpected broke"
    label = classify_error(log)
    assert label
    assert "額度" not in label
    assert "速率限制" not in label


def test_extract_error_snippet_keeps_last_lines_only():
    log = "\n".join(f"line {i}" for i in range(1, 21))
    snippet = extract_error_snippet(log, max_lines=3)
    assert snippet == "line 18\nline 19\nline 20"


def test_extract_error_snippet_truncates_long_content_from_the_left():
    """
    Telegram 單則訊息有長度限制，snippet 太長時應該保留「最後」的內容（通常是
    實際錯誤訊息所在），而不是從頭截斷。
    """
    log = "x" * 1000
    snippet = extract_error_snippet(log, max_lines=1, max_chars=50)
    assert len(snippet) <= 51  # 50 + 省略號
    assert snippet.endswith("x" * 50)


def test_extract_error_snippet_skips_blank_lines():
    log = "line 1\n\n\nline 2\n\n"
    assert extract_error_snippet(log, max_lines=5) == "line 1\nline 2"


def test_build_failure_message_includes_label_snippet_and_run_url():
    log = (
        "  Some earlier progress output\n"
        "anthropic.BadRequestError: Error code: 400 - {'type': 'error', 'error': "
        "{'type': 'invalid_request_error', 'message': 'Your credit balance is too "
        "low to access the Anthropic API.'}}"
    )
    run_url = "https://github.com/jason-hey/investment-report-2026/actions/runs/12345"

    msg = build_failure_message(log, run_url)

    assert "額度不足" in msg
    assert "credit balance is too low" in msg
    assert run_url in msg


def test_build_failure_message_without_log_still_includes_run_url():
    run_url = "https://github.com/jason-hey/investment-report-2026/actions/runs/12345"
    msg = build_failure_message("", run_url)
    assert run_url in msg
