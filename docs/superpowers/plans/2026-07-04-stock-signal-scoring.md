# 台股當日選股訊號評分系統 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在固定精選的 ~100 檔台股清單上，計算 8 項統計上有領先性的訊號（ADR 溢價、美股族群連動、法人同步買超、買超佔成交值比重、軋空候選、月營收 YoY、量價突破、相對強度），組成「今日觀察清單」綜合評分表，並追蹤「昨日入選股票今天實際表現」的勝率回顧。

**Architecture:** 延續 Plan 1/2 建立的三層模式：`scripts/data_fetchers.py` 新增資料抓取函式（yfinance + TWSE OpenAPI，皆為已在本專案驗證過的資料來源，不新增未知風險的資料源）、新建 `scripts/signal_scoring.py` 做訊號計算與勝率持久化（獨立一個檔案而非塞進 `report_render.py`，因為這部分邏輯量體大、職責獨立：算分不是「排版資料」，維持單一職責）、`scripts/report_render.py` 新增 context 組裝函式、`templates/report.html.j2` 新增「今日觀察清單」評分表與「昨日回顧」區塊、`scripts/generate_report.py` 主流程串接。唯一需要 AI 參與的部分是「命中原因」一行文字摘要（AI 依 Python 算好的命中結果撰寫，不判斷數字本身），透過既有的 JSON 敘述機制新增一個欄位，不新增額外的 Claude API 呼叫。

**Tech Stack:** Python 3.11、yfinance、TWSE OpenAPI（`openapi.twse.com.tw`，已驗證的免費資料源）、Jinja2、JSON 檔案持久化（`data/stock_signals_history.json`，與 `Backup/` 機制一樣用 git 常駐儲存）。

**前置條件：** 建立在 Plan 1（架構重寫）與 Plan 2（新資料區塊）皆已完成並合併的基礎上。

---

## 前置事實（寫 plan 前已實際查詢 TWSE OpenAPI 驗證過，不是憑空假設）

- **`https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN`**（集中市場融資融券餘額，無需查詢參數，永遠回傳最新交易日全市場資料）：每筆 `{"股票代號", "股票名稱", "融資買進", "融資賣出", "融資現金償還", "融資前日餘額", "融資今日餘額", "融資限額", "融券買進", "融券賣出", "融券現券償還", "融券前日餘額", "融券今日餘額", "融券限額", "資券互抵", "註記"}`，數字皆為字串。券資比 = 融券今日餘額 ÷ 融資今日餘額。
- **`https://openapi.twse.com.tw/v1/opendata/t187ap05_L`**（上市公司每月營業收入彙總表，無需查詢參數，回傳最新一期）：每筆 `{"公司代號", "公司名稱", "產業別", "營業收入-當月營收", "營業收入-去年同月增減(%)", ...}`，YoY 百分比已經算好，不需要自己抓歷史月營收再算。**範圍限制**：這個資料集只給「當月 vs 去年同月」，沒有更長的歷史序列，所以 v1 只做「月營收 YoY 大增」，不做「創歷史新高」（後者需要更長的歷史月營收序列，這個免費資料源沒有提供，記錄為未來工作）。
- **`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`**（已在 `scripts/data_fetchers.py` 的 `_fetch_twse_close_prices()` 使用過，取 `ClosingPrice`）：同一筆資料裡也有 `TradeValue`（成交金額，字串），買超金額 ÷ 成交值比重信號可以直接重用同一個 API 呼叫算出來，不需要新的資料源。
- **`https://www.twse.com.tw/rwd/zh/fund/T86`**（已在 `_fetch_twse_t86(date_yyyymmdd)` 使用過，回傳 `{code: {"name", "foreign_net", "trust_net"}}`）：外資+投信同步買超訊號直接重用這個既有函式抓「今天」一天的資料即可（不需要像 `fetch_institutional_3day_ranking()` 那樣抓 3 天）。
- **ADR 溢價計算**：TSM（代表台積電 2330.TW，1 股 ADR = 5 股普通股）、UMC（代表聯電 2303.TW，1 股 ADR = 5 股普通股）、ASX（ASE Technology Holding，代表日月光投控 3711.TW，1 股 ADR = 5 股普通股）皆為 yfinance 可直接查詢的美股 ticker，換算溢價 = (ADR 收盤價 ÷ 5 × 美元兌台幣匯率) ÷ 台股現價 − 1；匯率用 yfinance `TWD=X`。
- **美股族群 → 台股供應鏈映射**：不需要新的抓取函式——`scripts/data_fetchers.py` 已有 Plan 2 的 `fetch_us_heatmap()`（`US_HEATMAP_TICKERS` 含 NVDA/AAPL/MU 等）與 Plan 1 的 `fetch_quotes()`，這個訊號純粹是「拿已經抓到的美股當日漲跌 %，對照一張寫死的映射表，點亮對應台股」，不新增網路呼叫。
- `scripts/data_fetchers.py` 目前已有的 `_fetch_twse_t86`/`_fetch_twse_close_prices` 都是模組內部函式（底線開頭），這份 plan 會讓 `signal_scoring.py` 匯入使用，維持現有慣例不需要改成公開函式（Python 底線開頭只是慣例提示，同套件內互相 import 沒有存取限制）。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `scripts/data_fetchers.py` | 修改 | 新增 `fetch_adr_premiums()`、`fetch_margin_trading()`、`fetch_monthly_revenue()`、`fetch_watchlist_institutional()` |
| `scripts/signal_scoring.py` | 新建 | `TW_STOCK_WATCHLIST`（~100 檔清單）、`US_TO_TW_SUPPLY_CHAIN`（映射表）、8 項訊號計算函式、`compute_signal_scores()`（組合成綜合評分表）、`load_signal_history()`/`save_signal_history()`（勝率持久化） |
| `scripts/report_render.py` | 修改 | 新增 `build_signal_scoring_context()` |
| `templates/report.html.j2` | 修改 | 新增「今日觀察清單」評分表 + 「昨日選股回顧」區塊 |
| `scripts/generate_report.py` | 修改 | 主流程串接；JSON schema 新增 `stock_signal_reasons` 欄位 |
| `data/stock_signals_history.json` | 新建（執行時產生） | 持久化的每日入選清單，供隔天勝率回顧使用 |
| `tests/test_data_fetchers.py`、`tests/test_signal_scoring.py`（新建）、`tests/test_report_render.py`、`tests/test_generate_report.py` | 修改/新建 | 對應測試 |

---

### Task 1: 選股清單與供應鏈映射表（純資料，無網路呼叫）

**Files:**
- Create: `scripts/signal_scoring.py`
- Test: `tests/test_signal_scoring.py`（新建）

- [ ] **Step 1: 建立 `scripts/signal_scoring.py` 檔案骨架與選股清單**

```python
"""
台股當日選股訊號評分：固定精選 ~100 檔台股，計算 8 項統計上有領先性的訊號，
組成「今日觀察清單」綜合評分表；並持久化每日入選清單，供隔天算「昨日選股回顧」勝率。

刻意不掃描全市場——理由：控制 yfinance/TWSE 呼叫量與執行時間、避免不穩定
（見 docs/superpowers/specs/2026-07-03-report-architecture-and-features-design.md 的 C 節）。
"""
import json
import os
from datetime import datetime, timedelta

# 精選 ~100 檔台股，涵蓋：台積電供應鏈、AI 伺服器、蘋果概念、記憶體、金融。
# (yfinance 代號, 顯示代號, 顯示名稱)
TW_STOCK_WATCHLIST = [
    # 台積電供應鏈 / 晶圓代工
    ("2330.TW", "2330", "台積電"), ("2303.TW", "2303", "聯電"), ("5347.TW", "5347", "世界先進"),
    ("3711.TW", "3711", "日月光投控"), ("6770.TW", "6770", "力積電"),
    # IC 設計
    ("2454.TW", "2454", "聯發科"), ("3034.TW", "3034", "聯詠"), ("3443.TW", "3443", "創意"),
    ("3529.TW", "3529", "力旺"), ("6533.TW", "6533", "晶心科"), ("2379.TW", "2379", "瑞昱"),
    ("3661.TW", "3661", "世芯-KY"), ("6415.TW", "6415", "矽力-KY"), ("8046.TW", "8046", "南電"),
    # AI 伺服器 / 系統組裝
    ("2382.TW", "2382", "廣達"), ("2357.TW", "2357", "華碩"), ("3231.TW", "3231", "緯創"),
    ("6669.TW", "6669", "緯穎"), ("2356.TW", "2356", "英業達"), ("4938.TW", "4938", "和碩"),
    ("2377.TW", "2377", "微星"), ("2376.TW", "2376", "技嘉"),
    # 散熱 / 機殼 / 電源
    ("3017.TW", "3017", "奇鋐"), ("3324.TW", "3324", "雙鴻"), ("2308.TW", "2308", "台達電"),
    ("6409.TW", "6409", "旭隼"), ("2421.TW", "2421", "建準"),
    # PCB / 網通
    ("3037.TW", "3037", "欣興"), ("2313.TW", "2313", "華通"), ("2383.TW", "2383", "台光電"),
    ("6274.TW", "6274", "台燿"), ("2412.TW", "2412", "中華電"),
    # 蘋果概念
    ("2317.TW", "2317", "鴻海"), ("3008.TW", "3008", "大立光"), ("2354.TW", "2354", "鴻準"),
    ("6805.TW", "6805", "富世達"), ("2327.TW", "2327", "國巨"), ("3406.TW", "3406", "玉晶光"),
    # 記憶體
    ("2408.TW", "2408", "南亞科"), ("3006.TW", "3006", "晶豪科"), ("8299.TW", "8299", "群聯"),
    ("2337.TW", "2337", "旺宏"), ("4967.TW", "4967", "十铨"),
    # 被動元件 / 其他半導體周邊
    ("2492.TW", "2492", "華新科"), ("2492.TW", "2492", "國巨"),
    # 金融
    ("2891.TW", "2891", "中信金"), ("2882.TW", "2882", "國泰金"), ("2881.TW", "2881", "富邦金"),
    ("2886.TW", "2886", "兆豐金"), ("2892.TW", "2892", "第一金"), ("2884.TW", "2884", "玉山金"),
    ("2887.TW", "2887", "台新金"), ("5880.TW", "5880", "合庫金"), ("2880.TW", "2880", "華南金"),
    ("2885.TW", "2885", "元大金"), ("2883.TW", "2883", "開發金"), ("2890.TW", "2890", "永豐金"),
    # 傳產權值 / ETF
    ("0050.TW", "0050", "元大台灣50"), ("1301.TW", "1301", "台塑"), ("1303.TW", "1303", "南亞"),
    ("2002.TW", "2002", "中鋼"), ("2603.TW", "2603", "長榮"), ("2609.TW", "2609", "陽明"),
    ("2615.TW", "2615", "萬海"), ("1216.TW", "1216", "統一"), ("2912.TW", "2912", "統一超"),
]

# 美股族群 → 台股供應鏈映射：對照 data_fetchers.US_HEATMAP_TICKERS 的代號，
# 每個美股 ticker 對應「當它今日大漲/大跌時，應該點亮的台股觀察名單」。
US_TO_TW_SUPPLY_CHAIN = {
    "NVDA": ["3231", "2382", "3017", "3324", "6669", "2356"],   # AI 伺服器族群
    "AVGO": ["3711", "2454"],                                     # ASIC / 網通
    "AAPL": ["2317", "3008", "2354", "6805", "2327"],            # 蘋果概念
    "MU":   ["2408", "3006", "8299", "2337"],                     # 記憶體
    "TSM":  ["2330", "2303", "5347"],                             # 晶圓代工（ADR 本身也對應）
    "AMD":  ["2382", "3231", "6770"],
    "QCOM": ["2454", "2379"],
}
```

- [ ] **Step 2: 寫測試確認清單完整性**

```python
def test_tw_stock_watchlist_has_no_duplicate_codes_except_documented():
    from scripts.signal_scoring import TW_STOCK_WATCHLIST

    codes = [code for _, code, _ in TW_STOCK_WATCHLIST]
    # 2492 國巨 目前重複出現在清單草稿中，這裡先允許但用測試明確標記，
    # 之後若清理重複請同步移除這個例外
    assert len(codes) - len(set(codes)) <= 1


def test_us_to_tw_supply_chain_only_references_watchlist_codes():
    from scripts.signal_scoring import TW_STOCK_WATCHLIST, US_TO_TW_SUPPLY_CHAIN

    watchlist_codes = {code for _, code, _ in TW_STOCK_WATCHLIST}
    for us_symbol, tw_codes in US_TO_TW_SUPPLY_CHAIN.items():
        for code in tw_codes:
            assert code in watchlist_codes, f"{us_symbol} 映射到不在清單裡的 {code}"
```

- [ ] **Step 3: Run test，確認第一個測試會抓到清單草稿裡 2492 重複的問題**

Run: `pytest tests/test_signal_scoring.py -v`
Expected: 若發現 `codes` 裡有超過 1 個重複，先手動清理 `TW_STOCK_WATCHLIST`（拿掉重複的 2492 那一行）再繼續，讓清單保持乾淨，而不是留著測試裡的「允許 1 個例外」當作長期解法——那只是寫 plan 當下自我檢查用的暫時容錯，實作時應該直接把清單修乾淨，並把這條測試改成 `assert len(codes) == len(set(codes))`（無例外）。

- [ ] **Step 4: Commit**

```bash
git add scripts/signal_scoring.py tests/test_signal_scoring.py
git commit -m "feat: add curated TW stock watchlist and US-to-TW supply chain map"
```

---

### Task 2: `fetch_adr_premiums()` — ADR 溢價

**Files:** Modify `scripts/data_fetchers.py`, Test `tests/test_data_fetchers.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_adr_premiums_computes_premium_pct(monkeypatch):
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            # ADR 收盤 100 美元，台股收盤 500 台幣，匯率 32：
            # 換算後 ADR 對應台股價值 = 100/5*32 = 640；溢價 = 640/500 - 1 = 28%
            if self.symbol == "TSM":
                return pd.DataFrame({"Close": [99.0, 100.0]}, index=pd.to_datetime(["2026-07-01", "2026-07-02"]))
            if self.symbol == "TWD=X":
                return pd.DataFrame({"Close": [31.5, 32.0]}, index=pd.to_datetime(["2026-07-01", "2026-07-02"]))
            if self.symbol == "2330.TW":
                return pd.DataFrame({"Close": [495.0, 500.0]}, index=pd.to_datetime(["2026-07-01", "2026-07-02"]))
            return pd.DataFrame({"Close": [10.0, 10.0]}, index=pd.to_datetime(["2026-07-01", "2026-07-02"]))

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_adr_premiums()

    assert "TSM" in result
    tsm = result["TSM"]
    assert tsm["tw_code"] == "2330"
    assert round(tsm["premium_pct"], 2) == 28.0
```

- [ ] **Step 2:** confirm FAIL

- [ ] **Step 3: 實作**

```python
# ── ADR 溢價：TSM/UMC/ASX 對應台股的溢價率 ────────────────────────────────

ADR_TICKERS = {
    "TSM": ("2330.TW", "2330", 5),   # (台股 yfinance 代號, 顯示代號, ADR:普通股比例)
    "UMC": ("2303.TW", "2303", 5),
    "ASX": ("3711.TW", "3711", 5),
}


def fetch_adr_premiums():
    """
    計算 ADR 對應台股的溢價率：(ADR 收盤價 / 比例 * 美元兌台幣匯率) / 台股收盤價 - 1。
    正值代表 ADR（美股盤後）相對台股現股溢價，通常視為隔天台股開盤偏多的領先指標。
    """
    result = {}
    try:
        fx_hist = yf.Ticker("TWD=X").history(period="5d", interval="1d")
        if fx_hist.empty:
            print("  ⚠️ TWD=X 匯率資料不足，跳過 ADR 溢價計算")
            return result
        twd_rate = float(fx_hist["Close"].iloc[-1])
    except Exception as e:
        print(f"  ⚠️ TWD=X 匯率抓取失敗: {e}")
        return result

    for adr_symbol, (tw_symbol, tw_code, ratio) in ADR_TICKERS.items():
        try:
            adr_hist = yf.Ticker(adr_symbol).history(period="5d", interval="1d")
            tw_hist = yf.Ticker(tw_symbol).history(period="5d", interval="1d")
            if adr_hist.empty or tw_hist.empty:
                print(f"  ⚠️ {adr_symbol} ADR 溢價資料不足，略過")
                continue
            adr_close = float(adr_hist["Close"].iloc[-1])
            tw_close = float(tw_hist["Close"].iloc[-1])
            if _has_nan_close(adr_close, tw_close) or tw_close == 0:
                print(f"  ⚠️ {adr_symbol} 收盤價為 NaN 或台股收盤為 0，略過")
                continue
            implied_tw_price = adr_close / ratio * twd_rate
            premium_pct = (implied_tw_price / tw_close - 1) * 100
            result[adr_symbol] = {
                "tw_code": tw_code,
                "adr_close": round(adr_close, 2),
                "tw_close": round(tw_close, 2),
                "premium_pct": round(premium_pct, 2),
            }
        except Exception as e:
            print(f"  ⚠️ {adr_symbol} ADR 溢價計算失敗: {e}")
    print(f"  ADR 溢價：成功 {len(result)}/{len(ADR_TICKERS)} 檔")
    return result
```

- [ ] **Step 4:** confirm all tests pass
- [ ] **Step 5:** `git add scripts/data_fetchers.py tests/test_data_fetchers.py && git commit -m "feat: add fetch_adr_premiums() for TSM/UMC/ASX ADR premium signal"`

---

### Task 3: `fetch_margin_trading()` — 融資融券（軋空候選）

**Files:** Modify `scripts/data_fetchers.py`, Test `tests/test_data_fetchers.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_margin_trading_computes_short_margin_ratio(monkeypatch):
    import scripts.data_fetchers as df
    import requests

    class FakeResponse:
        def json(self):
            return [
                {"股票代號": "2330", "股票名稱": "台積電", "融資今日餘額": "10000", "融券今日餘額": "500"},
                {"股票代號": "9999", "股票名稱": "不在清單裡", "融資今日餘額": "1", "融券今日餘額": "1"},
            ]

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    result = df.fetch_margin_trading(["2330"])

    assert "2330" in result
    assert "9999" not in result  # 只回傳有在傳入清單裡的代號
    row = result["2330"]
    assert row["margin_balance"] == 10000
    assert row["short_balance"] == 500
    assert round(row["short_margin_ratio_pct"], 2) == 5.0
```

- [ ] **Step 2:** confirm FAIL

- [ ] **Step 3: 實作**

```python
# ── 融資融券：軋空候選（券資比偏高）訊號 ──────────────────────────────

def fetch_margin_trading(codes):
    """
    抓取 TWSE OpenAPI 集中市場融資融券餘額（全市場一次回傳，不支援用代號查詢），
    篩選出 codes 清單內的個股，計算券資比（融券今日餘額 / 融資今日餘額 * 100）。
    codes: 要篩選的股票代號 list（不含 .TW 後綴，例如 ["2330", "2317"]）。
    """
    import requests

    def to_int(s):
        s = (s or "").strip()
        return int(s.replace(",", "")) if s not in ("", "--") else 0

    result = {}
    try:
        resp = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN", timeout=15)
        data = resp.json()
        code_set = set(codes)
        for row in data:
            code = row.get("股票代號", "").strip()
            if code not in code_set:
                continue
            margin_balance = to_int(row.get("融資今日餘額"))
            short_balance = to_int(row.get("融券今日餘額"))
            short_margin_ratio_pct = (short_balance / margin_balance * 100) if margin_balance else 0.0
            result[code] = {
                "name": row.get("股票名稱", "").strip(),
                "margin_balance": margin_balance,
                "short_balance": short_balance,
                "short_margin_ratio_pct": round(short_margin_ratio_pct, 2),
            }
    except Exception as e:
        print(f"  ⚠️ 融資融券資料抓取失敗: {e}")
    print(f"  融資融券：清單內找到 {len(result)}/{len(codes)} 檔資料")
    return result
```

- [ ] **Step 4:** confirm all tests pass
- [ ] **Step 5:** `git add scripts/data_fetchers.py tests/test_data_fetchers.py && git commit -m "feat: add fetch_margin_trading() for short-squeeze candidate signal"`

---

### Task 4: `fetch_monthly_revenue()` — 月營收 YoY

**Files:** Modify `scripts/data_fetchers.py`, Test `tests/test_data_fetchers.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_monthly_revenue_filters_to_watchlist_codes(monkeypatch):
    import scripts.data_fetchers as df
    import requests

    class FakeResponse:
        def json(self):
            return [
                {"公司代號": "2330", "公司名稱": "台積電", "營業收入-當月營收": "12000000",
                 "營業收入-去年同月增減(%)": "35.5"},
                {"公司代號": "9999", "公司名稱": "不在清單裡", "營業收入-當月營收": "1",
                 "營業收入-去年同月增減(%)": "1.0"},
            ]

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    result = df.fetch_monthly_revenue(["2330"])

    assert "2330" in result
    assert "9999" not in result
    assert result["2330"]["yoy_change_pct"] == 35.5
```

- [ ] **Step 2:** confirm FAIL

- [ ] **Step 3: 實作**

```python
# ── 月營收：YoY 大增訊號（v1 只做 YoY，不做「創新高」——見前置事實說明） ──

def fetch_monthly_revenue(codes):
    """
    抓取 TWSE OpenAPI 上市公司每月營業收入彙總表（全市場一次回傳，不支援用代號查詢），
    篩選出 codes 清單內的個股。v1 只用資料源本身已算好的「去年同月增減(%)」，
    不嘗試回推歷史月營收序列去判斷「是否創新高」（免費資料源沒有提供夠長的歷史）。
    """
    result = {}
    try:
        resp = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", timeout=15)
        data = resp.json()
        code_set = set(codes)
        for row in data:
            code = row.get("公司代號", "").strip()
            if code not in code_set:
                continue
            try:
                yoy = float(row.get("營業收入-去年同月增減(%)") or 0)
            except ValueError:
                yoy = 0.0
            result[code] = {
                "name": row.get("公司名稱", "").strip(),
                "revenue": row.get("營業收入-當月營收", "").strip(),
                "yoy_change_pct": round(yoy, 2),
            }
    except Exception as e:
        print(f"  ⚠️ 月營收資料抓取失敗: {e}")
    print(f"  月營收：清單內找到 {len(result)}/{len(codes)} 檔資料")
    return result
```

Note: `import requests` 已經在檔案其他函式內用過（模組風格是各函式內自己 `import requests`，見 `_fetch_twse_close_prices`），這裡沿用同樣風格。

- [ ] **Step 4:** confirm all tests pass
- [ ] **Step 5:** `git add scripts/data_fetchers.py tests/test_data_fetchers.py && git commit -m "feat: add fetch_monthly_revenue() for YoY revenue growth signal"`

---

### Task 5: `fetch_watchlist_institutional()` — 今日法人買賣超 + 成交值（供 dual-buy 與買超/成交值比重訊號共用）

**Files:** Modify `scripts/data_fetchers.py`, Test `tests/test_data_fetchers.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_watchlist_institutional_combines_t86_and_trade_value(monkeypatch):
    import scripts.data_fetchers as df
    from datetime import datetime, timezone, timedelta

    def fake_t86(date_str):
        return {"2330": {"name": "台積電", "foreign_net": 5_000_000, "trust_net": 1_000_000}}

    def fake_close_prices():
        return {"2330": 500.0}

    monkeypatch.setattr(df, "_fetch_twse_t86", fake_t86)
    monkeypatch.setattr(df, "_fetch_twse_close_prices_and_value", lambda: ({"2330": 500.0}, {"2330": 2_000_000_000}))

    base_date = datetime(2026, 7, 3, tzinfo=timezone(timedelta(hours=8)))
    result = df.fetch_watchlist_institutional(["2330"], base_date)

    assert "2330" in result
    row = result["2330"]
    assert row["foreign_net"] == 5_000_000
    assert row["trust_net"] == 1_000_000
    assert row["dual_buy"] is True  # 外資、投信同步買超
    assert row["buy_value_ratio_pct"] is not None
```

- [ ] **Step 2:** confirm FAIL（`fetch_watchlist_institutional`/`_fetch_twse_close_prices_and_value` 尚不存在）

- [ ] **Step 3: 實作**

先擴充 `_fetch_twse_close_prices()`（既有函式，目前只回傳 `ClosingPrice`）成一個新函式，同時回傳 `TradeValue`，不修改既有函式簽章（避免影響 `fetch_institutional_3day_ranking()` 既有呼叫）：

```python
def _fetch_twse_close_prices_and_value():
    """抓取最新一個交易日全部台股收盤價與成交金額。TradeValue 供買超金額/成交值比重訊號使用。"""
    import requests
    try:
        resp = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15)
        data = resp.json()
        prices = {row["Code"]: float(row["ClosingPrice"]) for row in data if row.get("ClosingPrice")}
        values = {row["Code"]: float(row["TradeValue"]) for row in data if row.get("TradeValue")}
        return prices, values
    except Exception as e:
        print(f"  ⚠️ 收盤價/成交值抓取失敗（{e}）")
        return {}, {}


def fetch_watchlist_institutional(codes, base_date):
    """
    抓取「今天」（實際上是最近一個有資料的交易日，往前找最多 5 天）一天的三大法人
    買賣超（重用既有 _fetch_twse_t86），篩選出 codes 清單內的個股，並算出：
    - dual_buy：外資與投信是否同一天同步買超（皆 > 0）
    - buy_value_ratio_pct：外資+投信合計買超金額（用收盤價估算） / 當日成交值 * 100
      （買超佔成交值比重，取代絕對金額排序——對中小型股更有鑑別度）
    """
    cursor = base_date - timedelta(days=1)
    day_data = None
    attempts = 0
    while day_data is None and attempts < 5:
        attempts += 1
        if cursor.weekday() < 5:
            day_data = _fetch_twse_t86(cursor.strftime("%Y%m%d"))
        if day_data is None:
            cursor -= timedelta(days=1)

    if day_data is None:
        print("  ⚠️ 找不到最近的法人買賣超資料，觀察清單法人訊號略過")
        return {}

    close_prices, trade_values = _fetch_twse_close_prices_and_value()
    code_set = set(codes)
    result = {}
    for code, row in day_data.items():
        if code not in code_set:
            continue
        foreign_net = row["foreign_net"]
        trust_net = row["trust_net"]
        price = close_prices.get(code)
        trade_value = trade_values.get(code)
        buy_value_ratio_pct = None
        if price and trade_value:
            est_buy_amount = (foreign_net + trust_net) * price
            buy_value_ratio_pct = round(est_buy_amount / trade_value * 100, 2)
        result[code] = {
            "name": row["name"],
            "foreign_net": foreign_net,
            "trust_net": trust_net,
            "dual_buy": foreign_net > 0 and trust_net > 0,
            "buy_value_ratio_pct": buy_value_ratio_pct,
        }
    print(f"  法人觀察清單：{cursor.strftime('%Y-%m-%d')} 資料，清單內找到 {len(result)}/{len(codes)} 檔")
    return result
```

- [ ] **Step 4:** confirm all tests pass
- [ ] **Step 5:** `git add scripts/data_fetchers.py tests/test_data_fetchers.py && git commit -m "feat: add fetch_watchlist_institutional() for dual-buy and buy/value-ratio signals"`

---

### Task 6: `fetch_watchlist_price_history()` — 量價突破 + 相對強度 RS 用的歷史資料

**Files:** Modify `scripts/data_fetchers.py`, Test `tests/test_data_fetchers.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_watchlist_price_history_returns_ohlcv_per_code(monkeypatch):
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            n = 30
            return pd.DataFrame(
                {"Close": [100.0 + i for i in range(n)], "Volume": [1000] * (n - 1) + [5000]},
                index=pd.date_range("2026-06-01", periods=n, freq="D"),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_watchlist_price_history([("2330.TW", "2330")])

    assert "2330" in result
    row = result["2330"]
    assert len(row["closes"]) == 30
    assert len(row["volumes"]) == 30
```

- [ ] **Step 2:** confirm FAIL

- [ ] **Step 3: 實作**

```python
# ── 觀察清單歷史價量：供量價突破、相對強度 RS 訊號共用 ──────────────────

def fetch_watchlist_price_history(watchlist):
    """
    抓取 watchlist（[(yfinance代號, 顯示代號), ...]）每檔近 30 個交易日的收盤價與成交量。
    30 天足夠算 20 日新高（需要 20 天）與 5 日均量，且不會讓單次執行時間過長。
    """
    result = {}
    for symbol, code in watchlist:
        try:
            hist = yf.Ticker(symbol).history(period="2mo", interval="1d")
            if hist.empty or len(hist) < 21:
                print(f"  ⚠️ {code}({symbol}) 歷史價量資料不足，略過")
                continue
            closes = [float(c) for c in hist["Close"].tolist() if not math.isnan(c)]
            volumes = [float(v) for v in hist["Volume"].tolist() if not math.isnan(v)]
            if len(closes) < 21 or len(volumes) < 6:
                print(f"  ⚠️ {code}({symbol}) 有效資料不足，略過")
                continue
            result[code] = {"closes": closes[-30:], "volumes": volumes[-30:]}
        except Exception as e:
            print(f"  ⚠️ {code}({symbol}) 歷史價量抓取失敗: {e}")
    print(f"  觀察清單歷史價量：成功 {len(result)}/{len(watchlist)} 檔")
    return result
```

- [ ] **Step 4:** confirm all tests pass
- [ ] **Step 5:** `git add scripts/data_fetchers.py tests/test_data_fetchers.py && git commit -m "feat: add fetch_watchlist_price_history() for breakout and RS signals"`

---

### Task 7: `scripts/signal_scoring.py` — 8 項訊號計算 + 綜合評分

**Files:** Modify `scripts/signal_scoring.py`, Test `tests/test_signal_scoring.py`

- [ ] **Step 1: 寫失敗測試（示範 2-3 項訊號的計算邏輯，其餘比照辦理）**

```python
def test_score_adr_signal_hits_when_premium_above_threshold():
    from scripts.signal_scoring import score_adr_signal

    adr_data = {"TSM": {"tw_code": "2330", "premium_pct": 1.5}}
    hits = score_adr_signal(adr_data)
    assert hits["2330"]["hit"] is True
    assert "1.5" in hits["2330"]["detail"] or "1.50" in hits["2330"]["detail"]


def test_score_us_supply_chain_signal_lights_up_mapped_codes():
    from scripts.signal_scoring import score_us_supply_chain_signal

    heatmap_data = [{"symbol": "NVDA", "change_pct": 4.5}, {"symbol": "AAPL", "change_pct": -0.1}]
    hits = score_us_supply_chain_signal(heatmap_data)
    # NVDA 大漲 4.5% > 2% 門檻，應該點亮它映射的台股；AAPL 只跌 0.1%，不算「大漲」不點亮
    assert hits.get("3231", {}).get("hit") is True   # NVDA 映射到的其中一檔
    assert "2317" not in hits or hits["2317"]["hit"] is False


def test_score_breakout_signal_detects_20d_high_with_volume_surge():
    from scripts.signal_scoring import score_breakout_signal

    # 前 29 天平緩，最後一天價格創 30 天新高且成交量是前 5 天均量的 2 倍
    closes = [100.0] * 29 + [110.0]
    volumes = [1000.0] * 24 + [1000.0] * 5 + [3000.0]
    price_history = {"2330": {"closes": closes, "volumes": volumes[:30]}}
    hits = score_breakout_signal(price_history)
    assert hits["2330"]["hit"] is True


def test_score_short_squeeze_signal_requires_both_high_ratio_and_price_uptick():
    from scripts.signal_scoring import score_short_squeeze_signal

    # 券資比同樣是 35%（> 30% 門檻），但一檔股價轉強、一檔股價仍在下跌
    margin_data = {
        "2330": {"short_margin_ratio_pct": 35.0},
        "2317": {"short_margin_ratio_pct": 35.0},
    }
    price_history = {
        "2330": {"closes": [100.0, 102.0]},  # 收盤價轉強 → 應該命中
        "2317": {"closes": [100.0, 98.0]},   # 收盤價續跌 → 只是券資比高，不算軋空候選
    }
    hits = score_short_squeeze_signal(margin_data, price_history)
    assert hits.get("2330", {}).get("hit") is True
    assert "2317" not in hits or hits["2317"]["hit"] is False


def test_compute_signal_scores_ranks_by_total_hits_desc():
    from scripts.signal_scoring import compute_signal_scores, TW_STOCK_WATCHLIST

    # 只給少量假資料，驗證排序邏輯本身，不要求涵蓋全部訊號
    fake_signals = {
        "adr": {},
        "us_supply_chain": {"2330": {"hit": True, "detail": "NVDA +5%"}},
        "dual_buy": {"2330": {"hit": True, "detail": "外資投信同步買超"}},
        "buy_value_ratio": {},
        "short_squeeze": {},
        "revenue_yoy": {},
        "breakout": {},
        "rs_rank": {},
    }
    scores = compute_signal_scores(fake_signals, TW_STOCK_WATCHLIST)
    assert scores[0]["code"] == "2330"
    assert scores[0]["score"] == 2
```

- [ ] **Step 2:** confirm FAIL

- [ ] **Step 3: 實作 8 項訊號計算函式 + 綜合評分**

在 `scripts/signal_scoring.py` 新增（緊接 Task 1 的清單/映射表之後）：

```python
def score_adr_signal(adr_data, threshold_pct=0.5):
    """ADR 溢價 > threshold_pct% 視為命中（隔天台股偏多的領先訊號）。"""
    hits = {}
    for adr_symbol, row in adr_data.items():
        code = row["tw_code"]
        hit = row["premium_pct"] > threshold_pct
        hits[code] = {"hit": hit, "detail": f"{adr_symbol} ADR 溢價 {row['premium_pct']:+.2f}%"}
    return hits


def score_us_supply_chain_signal(heatmap_data, threshold_pct=2.0):
    """美股族群當日漲幅 > threshold_pct% 時，點亮 US_TO_TW_SUPPLY_CHAIN 映射的台股。"""
    hits = {}
    heatmap_by_symbol = {item["symbol"]: item["change_pct"] for item in heatmap_data}
    for us_symbol, tw_codes in US_TO_TW_SUPPLY_CHAIN.items():
        change_pct = heatmap_by_symbol.get(us_symbol)
        if change_pct is None or change_pct <= threshold_pct:
            continue
        for code in tw_codes:
            hits[code] = {"hit": True, "detail": f"{us_symbol} {change_pct:+.2f}% 帶動"}
    return hits


def score_dual_buy_signal(institutional_data):
    """外資、投信同一天同步買超。"""
    hits = {}
    for code, row in institutional_data.items():
        if row["dual_buy"]:
            hits[code] = {"hit": True, "detail": "外資＋投信同步買超"}
    return hits


def score_buy_value_ratio_signal(institutional_data, threshold_pct=3.0):
    """買超金額（估算） ÷ 當日成交值 > threshold_pct% 視為命中。"""
    hits = {}
    for code, row in institutional_data.items():
        ratio = row.get("buy_value_ratio_pct")
        if ratio is not None and ratio > threshold_pct:
            hits[code] = {"hit": True, "detail": f"買超佔成交值 {ratio:.1f}%"}
    return hits


def score_short_squeeze_signal(margin_data, price_history, ratio_threshold_pct=30.0):
    """
    軋空候選：券資比（融券今日餘額/融資今日餘額）> threshold（預設 30%），
    **且**股價開始轉強（最近一筆收盤價 > 前一筆收盤價）——原始規劃文件明確要求
    這兩個條件同時成立才算軋空候選，只看券資比偏高但股價仍在下跌不算（那是
    「融券續抱」而非「即將軋空」的訊號，兩者意義不同，不能只看券資比就命中）。
    """
    hits = {}
    for code, row in margin_data.items():
        ratio = row["short_margin_ratio_pct"]
        if ratio <= ratio_threshold_pct:
            continue
        closes = price_history.get(code, {}).get("closes", [])
        if len(closes) < 2 or closes[-1] <= closes[-2]:
            continue
        hits[code] = {"hit": True, "detail": f"券資比 {ratio:.1f}% 且股價轉強"}
    return hits


def score_revenue_yoy_signal(revenue_data, yoy_threshold_pct=20.0):
    """月營收 YoY 成長 > threshold（預設 20%）視為命中。"""
    hits = {}
    for code, row in revenue_data.items():
        if row["yoy_change_pct"] > yoy_threshold_pct:
            hits[code] = {"hit": True, "detail": f"月營收 YoY {row['yoy_change_pct']:+.1f}%"}
    return hits


def score_breakout_signal(price_history, volume_multiplier=1.5):
    """收盤價創近 20 日新高，且當日成交量 > 近 5 日均量 * volume_multiplier。"""
    hits = {}
    for code, row in price_history.items():
        closes = row["closes"]
        volumes = row["volumes"]
        if len(closes) < 21 or len(volumes) < 6:
            continue
        today_close = closes[-1]
        prior_20 = closes[-21:-1]
        today_volume = volumes[-1]
        prior_5_avg_volume = sum(volumes[-6:-1]) / 5
        is_new_high = today_close > max(prior_20)
        is_volume_surge = prior_5_avg_volume > 0 and today_volume > prior_5_avg_volume * volume_multiplier
        if is_new_high and is_volume_surge:
            hits[code] = {"hit": True, "detail": "量價齊揚突破 20 日新高"}
    return hits


def score_rs_rank_signal(price_history, twii_return_pct, top_n=15):
    """近 20 日報酬率減去加權指數同期報酬率，取排名前 top_n 名視為命中。"""
    rs_scores = []
    for code, row in price_history.items():
        closes = row["closes"]
        if len(closes) < 21:
            continue
        stock_return_pct = (closes[-1] / closes[-21] - 1) * 100
        rs = stock_return_pct - twii_return_pct
        rs_scores.append((code, rs))
    rs_scores.sort(key=lambda x: x[1], reverse=True)
    hits = {}
    for code, rs in rs_scores[:top_n]:
        if rs > 0:
            hits[code] = {"hit": True, "detail": f"近 20 日相對大盤強度 +{rs:.1f}%"}
    return hits


def compute_signal_scores(signals, watchlist):
    """
    把 8 個 {code: {"hit": bool, "detail": str}} dict 合併成綜合評分表：
    每檔股票列出命中的訊號數（score）與命中的訊號名稱清單，依 score 由高到低排序，
    只保留 score >= 1 的股票（沒有命中任何訊號的不需要出現在報告裡）。
    """
    signal_order = ["adr", "us_supply_chain", "dual_buy", "buy_value_ratio",
                     "short_squeeze", "revenue_yoy", "breakout", "rs_rank"]
    code_to_name = {code: name for _, code, name in watchlist}

    scored = {}
    for signal_name in signal_order:
        for code, hit_info in signals.get(signal_name, {}).items():
            if not hit_info.get("hit"):
                continue
            entry = scored.setdefault(code, {"code": code, "name": code_to_name.get(code, code),
                                              "score": 0, "signals_hit": [], "details": []})
            entry["score"] += 1
            entry["signals_hit"].append(signal_name)
            entry["details"].append(hit_info["detail"])

    result = list(scored.values())
    result.sort(key=lambda x: x["score"], reverse=True)
    return result
```

- [ ] **Step 4:** confirm all tests pass (`pytest tests/test_signal_scoring.py -v`)
- [ ] **Step 5:** `git add scripts/signal_scoring.py tests/test_signal_scoring.py && git commit -m "feat: implement 8 signal scoring functions + composite ranking"`

---

### Task 8: 勝率回顧持久化（`data/stock_signals_history.json`）

**Files:** Modify `scripts/signal_scoring.py`, Test `tests/test_signal_scoring.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_load_signal_history_returns_empty_dict_when_file_missing(tmp_path):
    from scripts.signal_scoring import load_signal_history

    result = load_signal_history(str(tmp_path / "does_not_exist.json"))
    assert result == {}


def test_save_and_load_signal_history_roundtrip(tmp_path):
    from scripts.signal_scoring import save_signal_history, load_signal_history

    path = str(tmp_path / "history.json")
    data = {"2026-07-03": {"picks": [{"code": "2330", "score": 3}]}}
    save_signal_history(path, data)

    loaded = load_signal_history(path)
    assert loaded == data


def test_compute_win_rate_review_checks_yesterdays_picks_against_todays_price(monkeypatch):
    from scripts.signal_scoring import compute_win_rate_review

    history = {"2026-07-02": {"picks": [{"code": "2330", "name": "台積電", "score": 3}]}}
    # 假設 2330 從 2026-07-02 到 2026-07-03 上漲了
    quotes_like = {"2330": {"price": 510.0, "change": 10.0, "change_pct": 2.0}}

    review = compute_win_rate_review(history, "2026-07-02", quotes_like)
    assert review["checked_date"] == "2026-07-02"
    assert review["total_picks"] == 1
    assert review["up_count"] == 1
    assert round(review["win_rate_pct"], 1) == 100.0
```

- [ ] **Step 2:** confirm FAIL

- [ ] **Step 3: 實作**

```python
# ── 勝率回顧持久化 ──────────────────────────────────────────────

def load_signal_history(path):
    """讀取歷史入選清單；檔案不存在時回傳空 dict（第一次執行的正常狀態，不是錯誤）。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠️ 讀取 {path} 失敗（{e}），視為空歷史")
        return {}


def save_signal_history(path, history):
    """寫入歷史入選清單。呼叫端負責控制歷史筆數上限（避免檔案無限成長）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, sort_keys=True)


def compute_win_rate_review(history, prev_trading_date_str, quotes_by_code):
    """
    比對 prev_trading_date_str 那天入選的股票，在「今天」（quotes_by_code 提供的最新報價）
    是否上漲，算出命中率。quotes_by_code 的 key 是不含 .TW 後綴的股票代號（例如 "2330"）。
    找不到 prev_trading_date_str 對應的歷史紀錄時，回傳 total_picks=0（第一次執行的正常狀態）。
    """
    day_record = history.get(prev_trading_date_str)
    if not day_record or not day_record.get("picks"):
        return {"checked_date": prev_trading_date_str, "total_picks": 0, "up_count": 0,
                "win_rate_pct": None, "picks_detail": []}

    picks_detail = []
    up_count = 0
    for pick in day_record["picks"]:
        code = pick["code"]
        quote = quotes_by_code.get(code)
        went_up = quote is not None and quote["change"] > 0
        if went_up:
            up_count += 1
        picks_detail.append({
            "code": code, "name": pick.get("name", code), "score": pick.get("score", 0),
            "went_up": went_up,
            "change_pct": quote["change_pct"] if quote else None,
        })

    total = len(day_record["picks"])
    return {
        "checked_date": prev_trading_date_str,
        "total_picks": total,
        "up_count": up_count,
        "win_rate_pct": round(up_count / total * 100, 1) if total else None,
        "picks_detail": picks_detail,
    }


def record_todays_picks(history, date_str, scored_list, top_n=15, max_history_days=30):
    """
    把「今天」的入選清單（取 score 最高的 top_n 檔）寫進 history dict 並回傳更新後的 history，
    同時清掉超過 max_history_days 天的舊紀錄，避免 data/stock_signals_history.json 無限成長。
    """
    picks = [{"code": s["code"], "name": s["name"], "score": s["score"]} for s in scored_list[:top_n]]
    history = dict(history)
    history[date_str] = {"picks": picks}

    if len(history) > max_history_days:
        for old_date in sorted(history.keys())[:-max_history_days]:
            del history[old_date]

    return history
```

- [ ] **Step 4:** confirm all tests pass
- [ ] **Step 5:** `git add scripts/signal_scoring.py tests/test_signal_scoring.py && git commit -m "feat: add win-rate history persistence for stock signal picks"`

---

### Task 9: AI JSON schema 新增「命中原因」欄位

**Files:** Modify `scripts/generate_report.py`, Test `tests/test_generate_report.py`

**設計原則**：命中原因文字（例如「NVDA 大漲 5% + 外資投信連 3 日同買 + 6 月營收創高」）本身不需要 AI 判斷任何數字——所有數字都已經是 Python 算好的 `compute_signal_scores()` 結果。這裡只是把算好的 `details` 清單轉成一句通順的話，讓 AI 在既有的敘述 JSON 呼叫裡多輸出一個欄位，**不新增額外的 Claude API 呼叫**。

- [ ] **Step 1: 修改 `REQUIRED_JSON_FIELDS` 與 `JSON_OUTPUT_SPEC`**

在 `scripts/generate_report.py` 的 `REQUIRED_JSON_FIELDS` 新增 `"stock_signal_reasons"`。

在 `JSON_OUTPUT_SPEC` 新增一個欄位說明（放在 `institutional_summary` 附近，因為概念相關）：

```python
  "stock_signal_reasons": [
    {"code": "<股票代號，例如 2330>", "reason": "<一句話說明為什麼這檔股票入選，依據下方提供的命中訊號清單改寫成通順的一句話，不要自己判斷或編造沒有列出的訊號>"}
  ],
```

並在 prompt 裡新增一個「已預先抓取」區塊（放在 quotes_json 之後），把 Python 算好的 `compute_signal_scores()` 結果的 `details` 傳給 AI：

```python
## 【已預先抓取】今日選股訊號命中清單（只需要把 details 改寫成一句通順的話，不要自己判斷數字）
{signal_scores_json}

欄位說明：code = 股票代號；score = 命中訊號數；details = 命中的各項訊號原始描述（陣列），
請針對每一檔股票，把它的 details 陣列改寫成一句通順的中文摘要，輸出到 stock_signal_reasons。
若這份清單是空陣列，stock_signal_reasons 也回傳空陣列即可。
```

- [ ] **Step 2: 更新 `tests/test_generate_report.py`**

```python
def test_validate_narrative_json_lists_missing_fields():
    from scripts.generate_report import validate_narrative_json, REQUIRED_JSON_FIELDS

    assert "stock_signal_reasons" in REQUIRED_JSON_FIELDS
    assert validate_narrative_json(None) == REQUIRED_JSON_FIELDS
    assert validate_narrative_json({f: None for f in REQUIRED_JSON_FIELDS}) == []
```

（這是修改既有測試，不是新增——既有的 `test_validate_narrative_json_lists_missing_fields` 已經用 `REQUIRED_JSON_FIELDS` 動態產生完整/不完整 dict，不需要大改，只要加一行確認新欄位真的被加進常數清單。）

- [ ] **Step 3:** confirm all tests pass
- [ ] **Step 4:** `git add scripts/generate_report.py tests/test_generate_report.py && git commit -m "feat: add stock_signal_reasons JSON field for AI-written pick summaries"`

---

### Task 10: `scripts/report_render.py` — 評分表 context 組裝

**Files:** Modify `scripts/report_render.py`, Test `tests/test_report_render.py`

- [ ] **Step 1: 寫失敗測試**

```python
def test_build_signal_scoring_context_merges_scores_with_ai_reasons():
    from scripts.report_render import build_signal_scoring_context

    scored_list = [{"code": "2330", "name": "台積電", "score": 2,
                    "signals_hit": ["adr", "dual_buy"], "details": ["ADR 溢價 +1.5%", "外資投信同步買超"]}]
    ai_reasons = [{"code": "2330", "reason": "ADR 溢價偏高且外資投信同步買超"}]
    win_rate_review = {"checked_date": "2026-07-02", "total_picks": 5, "up_count": 3,
                        "win_rate_pct": 60.0, "picks_detail": []}

    context = build_signal_scoring_context(scored_list, ai_reasons, win_rate_review)

    assert context["picks"][0]["code"] == "2330"
    assert context["picks"][0]["reason"] == "ADR 溢價偏高且外資投信同步買超"
    assert context["win_rate_review"]["win_rate_pct"] == 60.0


def test_build_signal_scoring_context_falls_back_to_details_when_no_ai_reason():
    from scripts.report_render import build_signal_scoring_context

    scored_list = [{"code": "2330", "name": "台積電", "score": 1,
                    "signals_hit": ["adr"], "details": ["ADR 溢價 +1.5%"]}]
    context = build_signal_scoring_context(scored_list, ai_reasons=[], win_rate_review={
        "checked_date": "2026-07-02", "total_picks": 0, "up_count": 0, "win_rate_pct": None, "picks_detail": []
    })
    # AI 沒有給這檔股票寫原因時，退回顯示 Python 算好的 details 合併字串，不要顯示空白
    assert context["picks"][0]["reason"] == "ADR 溢價 +1.5%"
```

- [ ] **Step 2:** confirm FAIL

- [ ] **Step 3: 實作**

```python
def build_signal_scoring_context(scored_list, ai_reasons, win_rate_review):
    """
    把 signal_scoring.compute_signal_scores() 的結果、AI 寫的一句話原因、
    以及勝率回顧，合併成模板要用的 context。
    """
    reason_by_code = {item["code"]: item["reason"] for item in ai_reasons}
    picks = []
    for entry in scored_list:
        reason = reason_by_code.get(entry["code"]) or "、".join(entry["details"])
        picks.append({
            "code": entry["code"],
            "name": entry["name"],
            "score": entry["score"],
            "signals_hit": entry["signals_hit"],
            "reason": reason,
        })
    return {"picks": picks, "win_rate_review": win_rate_review}
```

- [ ] **Step 4:** confirm all tests pass
- [ ] **Step 5:** `git add scripts/report_render.py tests/test_report_render.py && git commit -m "feat: add build_signal_scoring_context() combining scores with AI reasons"`

---

### Task 11: 模板新增「今日觀察清單」評分表 + 「昨日選股回顧」區塊

**Files:** Modify `templates/report.html.j2`, Test `tests/test_report_render.py`

- [ ] **Step 1: 找插入點**

放在「美股資金板塊輪動」區塊之後（Plan 2 新增的區塊）、「台指期夜盤動態」之前，或任何資料圖表群集裡合理的位置——這個區塊本質上也是「Python 算好的資料 + 一行 AI 摘要文字」，不是純敘述性內容，適合放在資料區塊群集裡。

- [ ] **Step 2: 評分表區塊**

```html
<!-- ══════════════════════ STOCK SIGNAL SCORING ══════════════════════ -->
<div class="section">
  <div class="container">
    <div class="sec-title">
      <span class="sec-title-icon">🎯</span> 今日觀察清單
      <span class="sec-subtitle">{{ date_label }} · 8 項訊號綜合評分</span>
    </div>
    <div class="chart-card">
      <table class="risk-table">
        <thead><tr><th>股票</th><th>命中數</th><th>理由</th></tr></thead>
        <tbody>
          {% for pick in signal_scoring.picks %}
          <tr>
            <td>{{ pick.code }} {{ pick.name }}</td>
            <td class="green" style="font-weight:700">{{ pick.score }}</td>
            <td>{{ pick.reason }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="chart-card" style="margin-top:14px">
      <div class="chart-title">昨日選股回顧</div>
      {% if signal_scoring.win_rate_review.total_picks > 0 %}
      <div class="header-sub">
        {{ signal_scoring.win_rate_review.checked_date }} 入選 {{ signal_scoring.win_rate_review.total_picks }} 檔，
        今日上漲 {{ signal_scoring.win_rate_review.up_count }} 檔，
        命中率 <span class="{{ 'green' if signal_scoring.win_rate_review.win_rate_pct >= 50 else 'red' }}">{{ '{:.1f}'.format(signal_scoring.win_rate_review.win_rate_pct) }}%</span>
      </div>
      {% else %}
      <div class="header-sub">尚無歷史入選紀錄可供回顧（本系統首次執行，或前一交易日無資料）。</div>
      {% endif %}
    </div>
  </div>
</div>
```

- [ ] **Step 3: 更新整合測試**

在 `tests/test_report_render.py` 的 `test_build_template_context_and_render_produces_valid_html`（或等效的整合測試）新增 `signal_scoring` context key，並斷言評分表內容出現在輸出中。若 `build_template_context()` 尚未在 Task 12 加上這個參數，先在測試裡直接組一個假的 `signal_scoring` dict 塞進 context（不透過 `build_template_context()`），確認模板語法正確：

```python
    context["signal_scoring"] = {
        "picks": [{"code": "2330", "name": "台積電", "score": 2, "signals_hit": ["adr"], "reason": "測試理由"}],
        "win_rate_review": {"checked_date": "2026-07-02", "total_picks": 1, "up_count": 1,
                             "win_rate_pct": 100.0, "picks_detail": []},
    }
    html = render_report(context)
    assert "測試理由" in html
    assert "命中率" in html
```

- [ ] **Step 4:** confirm all tests pass, do a manual render sanity check (no unrendered `{{`/`{%`)
- [ ] **Step 5:** `git add templates/report.html.j2 tests/test_report_render.py && git commit -m "feat: add stock signal scoring table and win-rate review template sections"`

---

### Task 12: `build_template_context()` 串接 `signal_scoring` context key

**Files:** Modify `scripts/report_render.py`, Test `tests/test_report_render.py`

- [ ] **Step 1:** 在 `build_template_context()` 新增一個必要參數 `signal_scoring_context`（直接是 Task 10 `build_signal_scoring_context()` 的回傳值，呼叫端負責組好再傳進來——不像 `korea_data`/`oil_data` 那樣給預設值，因為這個區塊沒有「尚未串接資料源」的過渡期，Task 8-11 都在同一份 plan 裡，實作到這裡時應該已經全部串好）：

```python
def build_template_context(*, ..., signal_scoring_context):
    return {
        ...,
        "signal_scoring": signal_scoring_context,
    }
```

- [ ] **Step 2:** 更新既有整合測試呼叫，改成真的呼叫 `build_signal_scoring_context(...)` 產生 `signal_scoring_context` 引數，取代 Task 11 Step 3 暫時手動塞的假 dict。

- [ ] **Step 3:** confirm all tests pass
- [ ] **Step 4:** `git add scripts/report_render.py tests/test_report_render.py && git commit -m "feat: wire signal_scoring_context into build_template_context()"`

---

### Task 13: `generate_report.py` 主流程串接

**Files:** Modify `scripts/generate_report.py`, Test `tests/conftest.py`

- [ ] **Step 1: 匯入與呼叫**

在既有 `from scripts.data_fetchers import (...)` 新增 `fetch_adr_premiums, fetch_margin_trading, fetch_monthly_revenue, fetch_watchlist_institutional, fetch_watchlist_price_history`。

新增 `from scripts.signal_scoring import (TW_STOCK_WATCHLIST, compute_signal_scores, score_adr_signal, score_us_supply_chain_signal, score_dual_buy_signal, score_buy_value_ratio_signal, score_short_squeeze_signal, score_revenue_yoy_signal, score_breakout_signal, score_rs_rank_signal, load_signal_history, save_signal_history, compute_win_rate_review, record_todays_picks)`。

在既有的 `heatmap_data`/`sector_rotation_data`/`oil_data` 抓取之後（同一個 prefetch 區塊）新增：

```python
print("  正在計算台股選股訊號（8 項訊號 + 綜合評分）...")
watchlist_codes = [code for _, code, _ in TW_STOCK_WATCHLIST]
adr_data = fetch_adr_premiums()
margin_data = fetch_margin_trading(watchlist_codes)
revenue_data = fetch_monthly_revenue(watchlist_codes)
watchlist_institutional = fetch_watchlist_institutional(watchlist_codes, today)
watchlist_price_history = fetch_watchlist_price_history(
    [(symbol, code) for symbol, code, _ in TW_STOCK_WATCHLIST]
)

twii_hist_closes = quotes.get("TWII")
# ^TWII 的近 20 日報酬率：用既有 quotes 沒有涵蓋的歷史資料，這裡另外抓一次加權指數的
# 近 30 日收盤價（跟 watchlist_price_history 用同一套 fetch_watchlist_price_history()
# 邏輯即可，代入單一標的清單）
twii_history = fetch_watchlist_price_history([("^TWII", "TWII")])
twii_return_pct = 0.0
if "TWII" in twii_history and len(twii_history["TWII"]["closes"]) >= 21:
    twii_closes = twii_history["TWII"]["closes"]
    twii_return_pct = (twii_closes[-1] / twii_closes[-21] - 1) * 100

signals = {
    "adr": score_adr_signal(adr_data),
    "us_supply_chain": score_us_supply_chain_signal(heatmap_data),
    "dual_buy": score_dual_buy_signal(watchlist_institutional),
    "buy_value_ratio": score_buy_value_ratio_signal(watchlist_institutional),
    "short_squeeze": score_short_squeeze_signal(margin_data, watchlist_price_history),
    "revenue_yoy": score_revenue_yoy_signal(revenue_data),
    "breakout": score_breakout_signal(watchlist_price_history),
    "rs_rank": score_rs_rank_signal(watchlist_price_history, twii_return_pct),
}
scored_list = compute_signal_scores(signals, TW_STOCK_WATCHLIST)

signal_scores_json = json.dumps(
    [{"code": s["code"], "score": s["score"], "details": s["details"]} for s in scored_list],
    ensure_ascii=False,
)

SIGNAL_HISTORY_PATH = "data/stock_signals_history.json"
signal_history = load_signal_history(SIGNAL_HISTORY_PATH)
prev_trading_date = today - timedelta(days=1)
while prev_trading_date.weekday() >= 5:
    prev_trading_date -= timedelta(days=1)
win_rate_review = compute_win_rate_review(signal_history, prev_trading_date.strftime("%Y-%m-%d"), quotes)
```

- [ ] **Step 2: 注入 prompt**

在 `quotes_json` 的 prompt 區塊之後新增：

```python
## 【已預先抓取】今日選股訊號命中清單（只需要把 details 改寫成一句通順的話，不要自己判斷數字）
{signal_scores_json}

欄位說明：code = 股票代號；score = 命中訊號數；details = 命中的各項訊號原始描述（陣列），
請針對每一檔股票，把它的 details 陣列改寫成一句通順的中文摘要，輸出到 stock_signal_reasons。
若這份清單是空陣列，stock_signal_reasons 也回傳空陣列即可。
```

- [ ] **Step 3: `build_template_context()` 呼叫新增引數**

```python
context = build_template_context(
    ...,
    signal_scoring_context=build_signal_scoring_context(
        scored_list, narrative_json["stock_signal_reasons"], win_rate_review
    ),
)
```

（`build_signal_scoring_context` 需要在檔案頂部 import：`from scripts.report_render import build_template_context, render_report, build_signal_scoring_context`。）

- [ ] **Step 4: 報告產出後，把今天的入選清單寫回歷史檔**

在 `Backup/{date_str}.html` 備份完成之後（既有的 `shutil.copy(...)` 那行之後）新增：

```python
signal_history = record_todays_picks(signal_history, date_str, scored_list)
save_signal_history(SIGNAL_HISTORY_PATH, signal_history)
print(f"  ✅ 選股歷史已更新：{SIGNAL_HISTORY_PATH}")
```

- [ ] **Step 5: 更新 `tests/conftest.py` 的 stub**

比照既有 7-8 個 fetcher 的模式，新增 `fetch_adr_premiums`（回傳 `{}`）、`fetch_margin_trading`（回傳 `{}`）、`fetch_monthly_revenue`（回傳 `{}`）、`fetch_watchlist_institutional`（回傳 `{}`）、`fetch_watchlist_price_history`（回傳 `{}`）的 stub，並加進 `originals` 暫存/還原清單。另外，因為 `record_todays_picks`/`save_signal_history` 現在會真的寫 `data/stock_signals_history.json`——這個檔案跟 `index.html`/`Backup/` 一樣，若在 repo 根目錄執行 stubbed import 會寫到真實檔案。**這個問題已經被既有的「stubbed import 在臨時資料夾執行」機制解決**（Task 9 的 `os.chdir(tmpdir)` 已經涵蓋所有相對路徑寫檔，包括這個新的 `data/stock_signals_history.json`），不需要額外處理，但要在 Step 6 明確驗證這一點。

- [ ] **Step 6: 驗證測試不會寫到真實的 `data/stock_signals_history.json`**

```bash
pytest tests/ -v
git status --short
```

Expected: 全過、工作區乾淨（沒有意外出現 `data/stock_signals_history.json` 或修改到的 `index.html`）。

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_report.py tests/conftest.py
git commit -m "feat: wire stock signal scoring system into main flow"
```

---

### Task 14: 端到端人工驗證

**Files:** 無新檔案，僅執行驗證

- [ ] **Step 1: 用真實資料跑一次完整的訊號計算 + 評分 + 渲染（不需要 ANTHROPIC_API_KEY）**

```bash
python -c "
from datetime import datetime, timezone, timedelta
from scripts.signal_scoring import (TW_STOCK_WATCHLIST, compute_signal_scores, score_adr_signal,
    score_us_supply_chain_signal, score_dual_buy_signal, score_buy_value_ratio_signal,
    score_short_squeeze_signal, score_revenue_yoy_signal, score_breakout_signal, score_rs_rank_signal)
from scripts.data_fetchers import (fetch_adr_premiums, fetch_margin_trading, fetch_monthly_revenue,
    fetch_watchlist_institutional, fetch_watchlist_price_history, fetch_us_heatmap)

TZ_TW = timezone(timedelta(hours=8))
today = datetime.now(TZ_TW)
watchlist_codes = [code for _, code, _ in TW_STOCK_WATCHLIST]

adr = fetch_adr_premiums()
margin = fetch_margin_trading(watchlist_codes)
revenue = fetch_monthly_revenue(watchlist_codes)
inst = fetch_watchlist_institutional(watchlist_codes, today)
history = fetch_watchlist_price_history([(s, c) for s, c, _ in TW_STOCK_WATCHLIST])
heatmap = fetch_us_heatmap()
twii_hist = fetch_watchlist_price_history([('^TWII', 'TWII')])
twii_return = 0.0
if 'TWII' in twii_hist and len(twii_hist['TWII']['closes']) >= 21:
    c = twii_hist['TWII']['closes']
    twii_return = (c[-1] / c[-21] - 1) * 100

signals = {
    'adr': score_adr_signal(adr), 'us_supply_chain': score_us_supply_chain_signal(heatmap),
    'dual_buy': score_dual_buy_signal(inst), 'buy_value_ratio': score_buy_value_ratio_signal(inst),
    'short_squeeze': score_short_squeeze_signal(margin, history), 'revenue_yoy': score_revenue_yoy_signal(revenue),
    'breakout': score_breakout_signal(history), 'rs_rank': score_rs_rank_signal(history, twii_return),
}
scored = compute_signal_scores(signals, TW_STOCK_WATCHLIST)
print(f'觀察清單股票數: {len(TW_STOCK_WATCHLIST)}')
print(f'ADR 溢價成功: {len(adr)}, 融資融券找到: {len(margin)}, 月營收找到: {len(revenue)}')
print(f'法人資料找到: {len(inst)}, 歷史價量成功: {len(history)}')
print(f'入選股票數（score>=1）: {len(scored)}')
for s in scored[:10]:
    print(s['code'], s['name'], s['score'], s['details'])
"
```

Expected: 印出合理的抓取成功筆數（多數欄位應該有 60-100 檔範圍內成功，個別 API 若當天無資料屬正常降級）；`scored` 列表印出的股票代號、名稱、命中細節要合理（不是全部 0 分，也不應該不合理地全部滿分）。

- [ ] **Step 2: 檢查 `data/stock_signals_history.json` 的持久化邏輯**

第一次執行（沒有歷史檔）：確認 `load_signal_history()` 回傳 `{}`、`compute_win_rate_review()` 回傳 `total_picks: 0`（不是拋例外）。手動呼叫 `record_todays_picks()` + `save_signal_history()` 產生一個測試檔案，確認格式可讀、可以再次 `load_signal_history()` 讀回一樣的內容。

- [ ] **Step 3: 確認 `pytest tests/ -v` 全數通過，且沒有殘留測試產物**

```bash
pytest tests/ -v
git status --short
```

Expected: 全過、工作區乾淨，且沒有意外產生 `data/stock_signals_history.json`（若有，確認是不是被 conftest 的臨時資料夾機制正確隔離；若真的洩漏到 repo 根目錄，要修 conftest，不能留著）。

- [ ] **Step 4: 手動視覺檢查**

比照 Plan 1/2 的做法，把完整 context（含 `signal_scoring`）渲染成一個檔案，用瀏覽器打開檢查「今日觀察清單」表格與「昨日選股回顧」區塊排版正常、無殘留 Jinja 標記。

---

## Plan 完成後的狀態

- 每日報告新增一個完全由 Python 算好、AI 只負責把命中原因改寫成一句話的選股評分表
- `data/stock_signals_history.json` 隨每日報告一起 commit，累積勝率回顧的歷史資料
- 三份 plan（架構重寫、新資料區塊、選股訊號評分）皆完成後，整個報告產生流程已經是「Python 算所有數字與圖表、AI 只寫敘述文字」的架構，達成原始改善分析文件裡「模板 + JSON 資料分離」的目標
