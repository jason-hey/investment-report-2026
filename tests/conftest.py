"""
scripts/generate_report.py 是「頂層腳本」風格的模組：import 它會立刻執行資料抓取
（yfinance / TWSE OpenAPI，真實網路呼叫）與呼叫 Claude API，並且在
`os.environ["ANTHROPIC_API_KEY"]` 不存在時會直接 KeyError。

這在測試環境是不可行的（無網路、無真實金鑰、也不該打真的 API）。但我們仍然需要
匯入並測試它裡面定義的純函式（extract_json_block / validate_narrative_json）與
REQUIRED_JSON_FIELDS 常數。

實驗結論（見任務討論）：
- Python 的 `from module import name` 要求整個 module 成功執行完畢才能取出 name；
  只要模組執行過程中拋出例外（包含 SystemExit），import 整體失敗，模組也不會留在
  sys.modules 裡讓我們事後挖出已定義的名稱。因此「讓模組提早 exit(0)」或「重複利用
  partial 模組」這兩個念頭都行不通（皆已用一個最小重現腳本驗證過）。
- 唯一乾淨可行的做法：在 generate_report 第一次被 import 的當下，暫時把它會呼叫的
  外部副作用（資料抓取函式、Anthropic 用戶端）換成假的、瞬間回傳、不連網的版本，讓
  整個模組順利執行到檔尾一次，然後立刻把這些函式/類別還原成原本的實作。
  之後同一個 process 裡任何測試再 `from scripts.generate_report import X` 都只是
  查 sys.modules 的 cache，不會重新執行模組、也不會用到假資料。

這個 fixture 是 session-scoped + autouse，確保在任何測試檔（包含本檔）第一次匯入
scripts.generate_report 之前，副作用已經被暫時替換掉；替換動作結束後立刻還原，
因此不會影響 tests/test_data_fetchers.py 直接呼叫 scripts.data_fetchers 真正實作的測試。
"""
import json
import os
import types

import pytest


def _fake_narrative_json():
    """符合 REQUIRED_JSON_FIELDS 的最小假資料，讓 validate_narrative_json() 通過。"""
    return {
        "daily_brief": "test daily brief",
        "header_pills": [],
        "data_validation": [],
        "hero_events": [],
        "warning_indicators": {},
        "night_session": {},
        "news": {},
        "ai_infra_html": "",
        "theme_cards": [],
        "strategy_cards": [],
        "risk_matrix_rows": [],
        "market_deep_dive_html": "",
        "lly_foundayo": {},
    }


def _stub_and_import_generate_report():
    import anthropic
    import scripts.data_fetchers as data_fetchers

    # ── 暫存所有將被替換的原始物件，稍後要原樣還原 ──
    originals = {
        "is_prev_us_day_holiday": data_fetchers.is_prev_us_day_holiday,
        "is_prev_tw_day_holiday": data_fetchers.is_prev_tw_day_holiday,
        "fetch_earnings_calendar": data_fetchers.fetch_earnings_calendar,
        "fetch_all_pe_data": data_fetchers.fetch_all_pe_data,
        "fetch_institutional_3day_ranking": data_fetchers.fetch_institutional_3day_ranking,
        "load_market_analysis_prompt": data_fetchers.load_market_analysis_prompt,
        "fetch_all_fear_index": data_fetchers.fetch_all_fear_index,
    }
    original_anthropic_cls = anthropic.Anthropic
    had_api_key = "ANTHROPIC_API_KEY" in os.environ
    original_api_key = os.environ.get("ANTHROPIC_API_KEY")
    had_date_override = "DATE_OVERRIDE" in os.environ
    original_date_override = os.environ.get("DATE_OVERRIDE")
    had_github_output = "GITHUB_OUTPUT" in os.environ
    original_github_output = os.environ.get("GITHUB_OUTPUT")

    fake_json_text = "```json\n" + json.dumps(_fake_narrative_json()) + "\n```"

    class _FakeStream:
        def __enter__(self):
            self.text_stream = iter([])
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_final_message(self):
            return types.SimpleNamespace(
                stop_reason="end_turn",
                content=[types.SimpleNamespace(text=fake_json_text)],
            )

    class _FakeMessages:
        def stream(self, **kwargs):
            return _FakeStream()

    class _FakeAnthropicClient:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    try:
        # 假 API 金鑰：只需要讓 os.environ["ANTHROPIC_API_KEY"] 存在，不會真的打 API
        # （因為 anthropic.Anthropic 本身也被換成假的）。
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
        # 固定用一個絕不會有 Backup/<date>.html 存在的日期，避免模組一開頭的
        # 「今日已發布，exit(0)」提早結束（見上方模組 docstring 的實驗結論：
        # exit(0) 會讓整個 import 失敗，不能讓它發生）。
        os.environ["DATE_OVERRIDE"] = "2099-01-01"
        # 模組尾端若偵測到 GITHUB_OUTPUT 存在會真的寫入該檔案；測試環境若剛好繼承了
        # 呼叫端（例如 CI runner）留下的 GITHUB_OUTPUT，這裡先移除，避免污染真實檔案。
        os.environ.pop("GITHUB_OUTPUT", None)

        data_fetchers.is_prev_us_day_holiday = lambda *_a, **_k: False
        data_fetchers.is_prev_tw_day_holiday = lambda *_a, **_k: False
        data_fetchers.fetch_earnings_calendar = lambda *_a, **_k: []
        data_fetchers.fetch_all_pe_data = lambda *_a, **_k: {"tw": [], "us": []}
        data_fetchers.fetch_institutional_3day_ranking = lambda *_a, **_k: None
        data_fetchers.load_market_analysis_prompt = lambda *_a, **_k: None
        data_fetchers.fetch_all_fear_index = lambda *_a, **_k: {
            "us": {"symbol": "^VIX", "name": "美股 VIX 恐懼指數", "history": []}
        }
        anthropic.Anthropic = _FakeAnthropicClient

        import scripts.generate_report  # noqa: F401  首次匯入，全程使用上面的假實作
    finally:
        for name, fn in originals.items():
            setattr(data_fetchers, name, fn)
        anthropic.Anthropic = original_anthropic_cls

        if had_api_key:
            os.environ["ANTHROPIC_API_KEY"] = original_api_key
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)

        if had_date_override:
            os.environ["DATE_OVERRIDE"] = original_date_override
        else:
            os.environ.pop("DATE_OVERRIDE", None)

        if had_github_output:
            os.environ["GITHUB_OUTPUT"] = original_github_output
        else:
            os.environ.pop("GITHUB_OUTPUT", None)


@pytest.fixture(autouse=True, scope="session")
def _stubbed_generate_report_import():
    """在任何測試需要 scripts.generate_report 之前，先用替身跑過一次模組頂層程式碼。"""
    _stub_and_import_generate_report()
    yield
