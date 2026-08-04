"""
失敗通知訊息組裝。

從 generate_report.py 執行時的 stdout/stderr log 文字裡分類錯誤原因（額度不足／
速率限制／金鑰失效……），組出人類可讀的通知內容，讓 Telegram/LINE/Email 不用
每次都要點進 GitHub Actions 網頁翻 log 才知道失敗原因。
"""
import re

# (比對錯誤訊息用的 regex, 顯示用的中文標籤) —— 依常見成因排序，找到第一個相符的就用。
_ERROR_PATTERNS = [
    (re.compile(r"credit balance is too low", re.I), "Anthropic API 額度不足，請至 console.anthropic.com 儲值"),
    (re.compile(r"rate_limit_error", re.I), "Anthropic API 已達速率限制（rate limit）"),
    (re.compile(r"authentication_error|invalid x-api-key", re.I), "Anthropic API 金鑰無效或已過期"),
    (re.compile(r"overloaded_error", re.I), "Anthropic API 服務過載，請稍後重試"),
    (re.compile(r"permission_error", re.I), "Anthropic API 金鑰權限不足"),
]

_DEFAULT_LABEL = "執行失敗，原因未分類（詳見下方錯誤內容）"


def classify_error(log_text: str) -> str:
    """依 log 文字內容比對已知錯誤類型；找不到就回傳通用標籤。"""
    for pattern, label in _ERROR_PATTERNS:
        if pattern.search(log_text):
            return label
    return _DEFAULT_LABEL


def extract_error_snippet(log_text: str, max_lines: int = 8, max_chars: int = 600) -> str:
    """取 log 最後幾行非空白內容，作為通知訊息附上的具體錯誤細節。

    只保留「最後」的內容（而非從頭截斷）：實際錯誤訊息通常在 traceback 尾端，
    Telegram 等通知平台又有長度限制，保留尾段最符合「一眼看出原因」的需求。
    """
    lines = [line.rstrip() for line in log_text.splitlines() if line.strip()]
    snippet = "\n".join(lines[-max_lines:])
    if len(snippet) > max_chars:
        snippet = "…" + snippet[-max_chars:]
    return snippet


def build_failure_message(log_text: str, run_url: str) -> str:
    """組出失敗通知的純文字內容（Telegram/LINE 直接用；Email 當作信件內文）。"""
    label = classify_error(log_text)
    snippet = extract_error_snippet(log_text)

    parts = ["投資情報 pipeline 執行失敗 ⚠️", "", label]
    if snippet:
        parts += ["", snippet]
    parts += ["", f"請檢查執行紀錄：{run_url}"]
    return "\n".join(parts)


if __name__ == "__main__":
    import sys

    log_path, run_url_arg = sys.argv[1], sys.argv[2]
    with open(log_path, encoding="utf-8", errors="replace") as f:
        log_content = f.read()
    print(build_failure_message(log_content, run_url_arg))
