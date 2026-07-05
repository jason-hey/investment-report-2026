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


def _valid_narrative_skeleton():
    """依 REQUIRED_JSON_FIELDS 的期望型別建出每個欄位都是「正確型別的空值」的資料。"""
    from scripts.generate_report import REQUIRED_JSON_FIELDS

    return {field: expected_type() for field, expected_type in REQUIRED_JSON_FIELDS.items()}


def test_validate_narrative_json_lists_missing_fields():
    from scripts.generate_report import validate_narrative_json, REQUIRED_JSON_FIELDS

    assert "stock_signal_reasons" in REQUIRED_JSON_FIELDS
    # None 輸入：全部欄位都缺
    assert len(validate_narrative_json(None)) == len(REQUIRED_JSON_FIELDS)
    # 欄位齊全且型別正確 → 通過
    assert validate_narrative_json(_valid_narrative_skeleton()) == []
    # 缺一個欄位 → 問題清單恰好一筆、且點名該欄位
    partial = _valid_narrative_skeleton()
    partial.pop("daily_brief")
    problems = validate_narrative_json(partial)
    assert len(problems) == 1
    assert "daily_brief" in problems[0]


def test_validate_narrative_json_rejects_null_field_value():
    """
    迴歸測試：舊版只檢查「欄位存在」，AI 輸出 "lly_foundayo": null 會通過驗證，
    直到模板深處（lly_foundayo.weekly_trx | tojson）才炸出難懂的 Jinja traceback。
    驗證階段就要把 null 欄位抓出來，錯誤訊息直接點名欄位。
    """
    from scripts.generate_report import validate_narrative_json

    data = _valid_narrative_skeleton()
    data["lly_foundayo"] = None
    problems = validate_narrative_json(data)
    assert len(problems) == 1
    assert "lly_foundayo" in problems[0]


def test_validate_narrative_json_rejects_wrong_type_field_value():
    from scripts.generate_report import validate_narrative_json

    data = _valid_narrative_skeleton()
    data["news"] = []          # 應為 dict（依分類的物件），AI 幻覺輸出成陣列
    data["ai_infra_html"] = 123  # 應為 str
    problems = validate_narrative_json(data)
    assert len(problems) == 2
    assert any("news" in p for p in problems)
    assert any("ai_infra_html" in p for p in problems)
