import json
import os
import subprocess
import sys


def test_script_is_directly_executable_from_repo_root_without_module_not_found_error():
    """
    迴歸測試（Task 10 端到端驗證中發現的重大 bug）：CLAUDE.md 與
    .github/workflows/daily-update.yml 都用「python scripts/generate_report.py」
    （repo 根目錄執行）啟動本檔案。這種呼叫方式下，Python 會把「腳本所在目錄」
    （scripts/）放進 sys.path[0] 而不是目前工作目錄，導致
    `from scripts.data_fetchers import ...` 找不到 scripts 套件、直接
    ModuleNotFoundError，整條 pipeline 在最開頭就崩潰——即使 pytest 測試全部通過
    也測不出來，因為 pytest 自己會把 repo 根目錄加進 sys.path，掩蓋了這個問題。

    這裡真的用 subprocess 依照文件記載的方式啟動一次，只驗證它能跑過
    import／資料抓取階段，在「缺少 ANTHROPIC_API_KEY」這個預期位置失敗
    ——而不是在 import 階段就用 ModuleNotFoundError 崩潰。
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "DATE_OVERRIDE": "2026-06-16"}
    env.pop("ANTHROPIC_API_KEY", None)

    result = subprocess.run(
        [sys.executable, "scripts/generate_report.py"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )

    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert "UnicodeEncodeError" not in result.stderr, result.stderr
    assert "KeyError: 'ANTHROPIC_API_KEY'" in result.stderr, result.stderr


def test_extract_json_block_parses_fenced_json():
    from scripts.generate_report import extract_json_block

    text = 'some preamble\n```json\n{"daily_brief": "abc"}\n```\ntrailing text'
    assert extract_json_block(text) == {"daily_brief": "abc"}


def test_extract_json_block_returns_none_when_no_fence():
    from scripts.generate_report import extract_json_block

    assert extract_json_block("no json here") is None


def test_extract_json_block_returns_none_on_invalid_json():
    from scripts.generate_report import extract_json_block

    assert extract_json_block("```json\n{not valid json\n```") is None


def test_extract_json_block_handles_nested_triple_backticks_in_string_value():
    from scripts.generate_report import extract_json_block

    # market_deep_dive_html / 新聞內文等自由文字欄位理論上可能剛好包含 ``` 字元；
    # 非貪婪 regex 會在這裡提早截斷，導致合法 JSON 被誤判為解析失敗。
    text = '```json\n{"daily_brief": "some ```code``` inside"}\n```'
    assert extract_json_block(text) == {"daily_brief": "some ```code``` inside"}


def test_validate_narrative_json_lists_missing_fields():
    from scripts.generate_report import validate_narrative_json, REQUIRED_JSON_FIELDS

    assert validate_narrative_json(None) == REQUIRED_JSON_FIELDS
    assert validate_narrative_json({f: None for f in REQUIRED_JSON_FIELDS}) == []
    partial = {f: None for f in REQUIRED_JSON_FIELDS if f != "daily_brief"}
    assert validate_narrative_json(partial) == ["daily_brief"]
