# 新資料區塊（韓國股市 / 美股熱力圖 / 美股資金板塊輪動 / 油價走勢）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在架構重寫（Plan 1）完成後的新架構上，新增 4 個純 Python 計算、不經過 AI 的資料區塊：韓國股市、美股熱力圖、美股資金板塊輪動、油價走勢圖。

**Architecture:** 延續 Plan 1 建立的模式——`scripts/data_fetchers.py` 新增抓取函式（全部用 yfinance，免費、無需 API key）、`scripts/report_render.py` 新增 context 組裝函式、`templates/report.html.j2` 新增對應區塊、`scripts/generate_report.py` 主流程串接。這 4 個區塊完全不需要 AI 輸出任何 JSON 欄位——所有數字與圖表都是 Python 算好直接餵給模板，跟現有的 ticker 跑馬燈、KPI 儀表板、VIX/P-E 圖表走同一套模式。

**Tech Stack:** Python 3.11、yfinance（既有依賴）、Jinja2（既有依賴）、Chart.js（既有，模板已載入）。

**前置條件：** 這份 plan 建立在 Plan 1（`docs/superpowers/plans/2026-07-03-report-architecture-rewrite.md`）已完成並合併的基礎上。以下所有檔案引用都假設 Plan 1 的最終狀態已經存在：`scripts/data_fetchers.py`（含 `fetch_quotes`、`fetch_all_fear_index` 等）、`scripts/report_render.py`（含 `build_template_context`、`build_vix_history` 等）、`templates/report.html.j2`（含 VIX 圖表區塊，作為油價圖表的參考藍本）。

---

## 前置事實（寫 plan 前已查證）

- `scripts/data_fetchers.py` 現有的 `fetch_all_fear_index()`／`fetch_fear_index_history(symbol, display_name, period="6mo")` 是油價走勢抓取的直接參考藍本：同樣的「抓近 6 個月日線收盤價，回傳 `[{"date":"YYYY-MM-DD","value":數值}]`」模式，換成 WTI（`CL=F`）與 Brent（`BZ=F`）兩個 ticker 即可，不需要新寫法。
- `templates/report.html.j2` 現有 VIX 圖表區塊（`<canvas id="vixChart">`、`const vixRaw = {{ vix_history | tojson }}`、`new Chart(vixCtx, {...})`）是油價圖表的直接參考藍本，包含顏色分段、警戒線 `afterDraw` plugin 等技巧，油價圖表可以簡化版本沿用（不需要警戒線，兩條線分別是 WTI/Brent 即可，類似 P/E 圖表的多線做法）。
- `scripts/report_render.py` 的 `build_template_context()` 是所有 context 組裝的單一入口，新增的 4 個區塊都要在這裡新增對應的 key。
- `scripts/generate_report.py` 主流程目前的資料預抓順序（financial calendar → P/E → VIX → institutional → quotes）就是新抓取函式要插入的地方，緊接在 `fetch_quotes()` 之後。
- 這 4 個區塊都不需要修改 `REQUIRED_JSON_FIELDS`／`JSON_OUTPUT_SPEC`（不需要 AI 產生任何新欄位），也不需要修改 prompt 的搜尋任務清單——這是與 Plan 1 的 Task 7/8 完全正交的一組新增，不會有欄位衝突風險。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `scripts/data_fetchers.py` | 修改 | 新增 `fetch_korea_market()`、`fetch_us_heatmap()`、`fetch_sector_rotation()`、`fetch_oil_prices()` |
| `scripts/report_render.py` | 修改 | 新增 `build_korea_context()`、`build_heatmap_context()`、`build_sector_rotation_context()`、`build_oil_context()`；`build_template_context()` 增加對應 context key |
| `templates/report.html.j2` | 修改 | 新增 4 個區塊（韓國股市卡片、美股熱力圖格狀圖、產業輪動表格、油價走勢圖） |
| `scripts/generate_report.py` | 修改 | 主流程新增 4 個抓取呼叫，傳入 `build_template_context()` |
| `tests/test_data_fetchers.py` | 修改 | 新增抓取函式測試 |
| `tests/test_report_render.py` | 修改 | 新增 context 組裝測試 + 更新完整 render 整合測試 |

---

### Task 1: 新增 `fetch_korea_market()`

**Files:**
- Modify: `scripts/data_fetchers.py`
- Test: `tests/test_data_fetchers.py`

韓國股市區塊：KOSPI 指數 + 三星電子 + SK 海力士，當日漲跌。

- [ ] **Step 1: 寫失敗測試**

`tests/test_data_fetchers.py`（append）:

```python
def test_fetch_korea_market_returns_index_and_two_stocks(monkeypatch):
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            return pd.DataFrame(
                {"Close": [100.0, 103.0]},
                index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_korea_market()

    assert set(result.keys()) == {"KOSPI", "SAMSUNG", "SK_HYNIX"}
    kospi = result["KOSPI"]
    assert kospi["symbol"] == "^KS11"
    assert kospi["name"] == "KOSPI 指數"
    assert kospi["price"] == 103.0
    assert kospi["change"] == 3.0
    assert round(kospi["change_pct"], 2) == 3.0
```

- [ ] **Step 2: Run test 確認失敗**

Run: `pytest tests/test_data_fetchers.py::test_fetch_korea_market_returns_index_and_two_stocks -v`
Expected: FAIL，`AttributeError: module 'scripts.data_fetchers' has no attribute 'fetch_korea_market'`

- [ ] **Step 3: 實作 `fetch_korea_market()`**

在 `scripts/data_fetchers.py` 檔尾新增（沿用 `fetch_quotes()` 已驗證過的抓取邏輯與 `_norm_zero`-style 寫法，但這裡是獨立的小清單，不需要共用 `QUOTE_TICKERS`）：

```python
# ── 韓國股市：KOSPI 指數 + 三星電子 + SK 海力士 ────────────────────────────

KOREA_TICKERS = {
    "KOSPI":    ("^KS11", "KOSPI 指數"),
    "SAMSUNG":  ("005930.KS", "三星電子"),
    "SK_HYNIX": ("000660.KS", "SK 海力士"),
}


def fetch_korea_market():
    """抓取韓國股市指數與兩檔龍頭股的最新收盤價與日漲跌。做法與 fetch_quotes() 相同。"""
    result = {}
    for key, (symbol, name) in KOREA_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if hist.empty or len(hist) < 2:
                print(f"  ⚠️ {name}({symbol}) 報價資料不足，略過")
                continue
            prev_close = float(hist["Close"].iloc[-2])
            last_close = float(hist["Close"].iloc[-1])
            change = last_close - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0.0
            result[key] = {
                "symbol": symbol,
                "name": name,
                "price": round(last_close, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
            }
        except Exception as e:
            print(f"  ⚠️ {name}({symbol}) 報價抓取失敗: {e}")
    print(f"  韓股：成功 {len(result)}/{len(KOREA_TICKERS)} 檔")
    return result
```

- [ ] **Step 4: Run test 確認通過**

Run: `pytest tests/test_data_fetchers.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/data_fetchers.py tests/test_data_fetchers.py
git commit -m "feat: add fetch_korea_market() for KOSPI + Samsung + SK Hynix"
```

---

### Task 2: 新增 `fetch_us_heatmap()`

**Files:**
- Modify: `scripts/data_fetchers.py`
- Test: `tests/test_data_fetchers.py`

固定 ~40 檔美股清單，抓當日漲跌 %，供熱力圖著色用。

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_us_heatmap_returns_change_pct_for_each_symbol(monkeypatch):
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            return pd.DataFrame(
                {"Close": [100.0, 95.0]},
                index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_us_heatmap()

    assert len(result) == len(df.US_HEATMAP_TICKERS)
    first = result[0]
    assert set(first.keys()) == {"symbol", "change_pct"}
    assert first["change_pct"] == -5.0
```

- [ ] **Step 2: Run test 確認失敗**

Run: `pytest tests/test_data_fetchers.py::test_fetch_us_heatmap_returns_change_pct_for_each_symbol -v`
Expected: FAIL（`fetch_us_heatmap`／`US_HEATMAP_TICKERS` 不存在）

- [ ] **Step 3: 實作 `fetch_us_heatmap()`**

```python
# ── 美股熱力圖：固定清單依當日漲跌 % 著色 ──────────────────────────────

US_HEATMAP_TICKERS = [
    # 大型科技
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NFLX", "CRM",
    # 半導體 / AI
    "NVDA", "AVGO", "AMD", "TSM", "MU", "QCOM", "INTC", "MRVL", "AMAT", "LRCX",
    # 雲端 / 軟體
    "ORCL", "ADBE", "NOW", "PANW", "SNOW",
    # 金融
    "JPM", "GS", "MS", "BAC", "V", "MA",
    # 醫療 / 消費
    "LLY", "UNH", "JNJ", "WMT", "COST", "NKE", "MCD",
    # 工業 / 能源
    "XOM", "CVX", "BA", "CAT",
    # 通訊
    "T", "VZ",
]


def fetch_us_heatmap():
    """抓取固定美股清單的當日漲跌 %，回傳 list[{"symbol","change_pct"}]，供熱力圖著色。
    單一標的失敗會從結果省略；模板端只需處理「筆數可能少於清單長度」即可，不需要佔位。"""
    result = []
    for symbol in US_HEATMAP_TICKERS:
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if hist.empty or len(hist) < 2:
                print(f"  ⚠️ {symbol} 熱力圖資料不足，略過")
                continue
            prev_close = float(hist["Close"].iloc[-2])
            last_close = float(hist["Close"].iloc[-1])
            change_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0
            result.append({"symbol": symbol, "change_pct": round(change_pct, 2)})
        except Exception as e:
            print(f"  ⚠️ {symbol} 熱力圖抓取失敗: {e}")
    print(f"  美股熱力圖：成功 {len(result)}/{len(US_HEATMAP_TICKERS)} 檔")
    return result
```

- [ ] **Step 4: Run test 確認通過**

Run: `pytest tests/test_data_fetchers.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/data_fetchers.py tests/test_data_fetchers.py
git commit -m "feat: add fetch_us_heatmap() for ~40-stock daily change heatmap"
```

---

### Task 3: 新增 `fetch_sector_rotation()`

**Files:**
- Modify: `scripts/data_fetchers.py`
- Test: `tests/test_data_fetchers.py`

11 檔 SPDR 產業 ETF，當日 + 一週表現，作為資金輪動代理指標。

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_sector_rotation_returns_1d_and_1w_change(monkeypatch):
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            # 6 個交易日收盤價：用來算「今日」（最後兩天）與「一週」（首尾）漲跌
            return pd.DataFrame(
                {"Close": [100.0, 101.0, 102.0, 103.0, 104.0, 106.0]},
                index=pd.to_datetime(["2026-06-26", "2026-06-29", "2026-06-30",
                                       "2026-07-01", "2026-07-02", "2026-07-03"]),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_sector_rotation()

    assert len(result) == len(df.SECTOR_ETF_TICKERS)
    first = result[0]
    assert set(first.keys()) == {"symbol", "name", "change_pct_1d", "change_pct_1w"}
    assert round(first["change_pct_1d"], 2) == round((106.0 - 104.0) / 104.0 * 100, 2)
    assert round(first["change_pct_1w"], 2) == round((106.0 - 100.0) / 100.0 * 100, 2)
```

- [ ] **Step 2: Run test 確認失敗**

Run: `pytest tests/test_data_fetchers.py::test_fetch_sector_rotation_returns_1d_and_1w_change -v`

- [ ] **Step 3: 實作 `fetch_sector_rotation()`**

```python
# ── 美股資金板塊輪動：11 檔 SPDR 產業 ETF 當日 + 一週表現 ──────────────────

SECTOR_ETF_TICKERS = [
    ("XLK", "科技"), ("XLF", "金融"), ("XLE", "能源"), ("XLV", "醫療"),
    ("XLY", "非必需消費"), ("XLP", "必需消費"), ("XLI", "工業"),
    ("XLB", "原物料"), ("XLRE", "房地產"), ("XLU", "公用事業"), ("XLC", "通訊服務"),
]


def fetch_sector_rotation():
    """抓取 11 檔 SPDR 產業 ETF 近 1-2 週日線，算出當日與一週漲跌 %。
    period="2wk" 抓夠一週交易日（含假日緩衝）；用第一筆與最後一筆算一週漲跌，
    最後兩筆算當日漲跌。"""
    result = []
    for symbol, name in SECTOR_ETF_TICKERS:
        try:
            hist = yf.Ticker(symbol).history(period="2wk", interval="1d")
            if hist.empty or len(hist) < 2:
                print(f"  ⚠️ {name}({symbol}) 板塊輪動資料不足，略過")
                continue
            closes = hist["Close"]
            last = float(closes.iloc[-1])
            prev_day = float(closes.iloc[-2])
            week_ago = float(closes.iloc[0])
            change_pct_1d = (last - prev_day) / prev_day * 100 if prev_day else 0.0
            change_pct_1w = (last - week_ago) / week_ago * 100 if week_ago else 0.0
            result.append({
                "symbol": symbol,
                "name": name,
                "change_pct_1d": round(change_pct_1d, 2),
                "change_pct_1w": round(change_pct_1w, 2),
            })
        except Exception as e:
            print(f"  ⚠️ {name}({symbol}) 板塊輪動抓取失敗: {e}")
    print(f"  產業輪動：成功 {len(result)}/{len(SECTOR_ETF_TICKERS)} 檔")
    return result
```

- [ ] **Step 4: Run test 確認通過**

Run: `pytest tests/test_data_fetchers.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/data_fetchers.py tests/test_data_fetchers.py
git commit -m "feat: add fetch_sector_rotation() for 11 SPDR sector ETFs"
```

---

### Task 4: 新增 `fetch_oil_prices()`

**Files:**
- Modify: `scripts/data_fetchers.py`
- Test: `tests/test_data_fetchers.py`

WTI + Brent 近 6 個月走勢，格式與 `fetch_all_fear_index()` 完全對應（供模板沿用 VIX 圖表的繪圖模式）。

- [ ] **Step 1: 寫失敗測試**

```python
def test_fetch_oil_prices_returns_wti_and_brent_history(monkeypatch):
    import scripts.data_fetchers as df

    def fake_history(symbol, display_name, period="6mo"):
        return [{"date": "2026-07-01", "value": 68.5}, {"date": "2026-07-02", "value": 69.1}]

    monkeypatch.setattr(df, "fetch_fear_index_history", fake_history)
    result = df.fetch_oil_prices()

    assert result["wti"]["symbol"] == "CL=F"
    assert result["wti"]["name"] == "WTI 原油"
    assert result["wti"]["history"] == [{"date": "2026-07-01", "value": 68.5}, {"date": "2026-07-02", "value": 69.1}]
    assert result["brent"]["symbol"] == "BZ=F"
    assert result["brent"]["name"] == "Brent 原油"
```

- [ ] **Step 2: Run test 確認失敗**

Run: `pytest tests/test_data_fetchers.py::test_fetch_oil_prices_returns_wti_and_brent_history -v`

- [ ] **Step 3: 實作 `fetch_oil_prices()`**

直接重用既有的 `fetch_fear_index_history(symbol, display_name, period="6mo")`（Plan 1 之前就已存在，簽章不變）：

```python
# ── 油價走勢：WTI + Brent 近 6 個月日資料，格式比照 fetch_all_fear_index() ──

OIL_TICKERS = {
    "wti": ("CL=F", "WTI 原油"),
    "brent": ("BZ=F", "Brent 原油"),
}


def fetch_oil_prices():
    """抓取 WTI 與 Brent 近 6 個月日收盤價，格式與 fetch_all_fear_index() 一致
    （皆為 fetch_fear_index_history() 的產物），模板端可沿用同一套繪圖邏輯。"""
    result = {}
    for key, (symbol, name) in OIL_TICKERS.items():
        result[key] = {
            "symbol": symbol,
            "name": name,
            "history": fetch_fear_index_history(symbol, name),
        }
    return result
```

- [ ] **Step 4: Run test 確認通過**

Run: `pytest tests/test_data_fetchers.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/data_fetchers.py tests/test_data_fetchers.py
git commit -m "feat: add fetch_oil_prices() for WTI + Brent history"
```

---

### Task 5: `scripts/report_render.py` — 4 個 context 組裝函式

**Files:**
- Modify: `scripts/report_render.py`
- Test: `tests/test_report_render.py`

- [ ] **Step 1: 寫失敗測試**

`tests/test_report_render.py`（append）:

```python
def test_build_korea_context_passes_through_data():
    from scripts.report_render import build_korea_context

    data = {"KOSPI": {"symbol": "^KS11", "name": "KOSPI 指數", "price": 3100.0, "change": 25.0, "change_pct": 0.81}}
    assert build_korea_context(data) == data


def test_build_heatmap_context_adds_color_class():
    from scripts.report_render import build_heatmap_context

    data = [
        {"symbol": "AAPL", "change_pct": 3.5},
        {"symbol": "TSLA", "change_pct": -2.1},
        {"symbol": "MSFT", "change_pct": 0.05},
    ]
    result = build_heatmap_context(data)
    by_symbol = {item["symbol"]: item for item in result}
    assert by_symbol["AAPL"]["color_class"] == "heat-strong-up"
    assert by_symbol["TSLA"]["color_class"] == "heat-down"
    assert by_symbol["MSFT"]["color_class"] == "heat-flat"


def test_build_sector_rotation_context_sorts_by_1d_change_desc():
    from scripts.report_render import build_sector_rotation_context

    data = [
        {"symbol": "XLE", "name": "能源", "change_pct_1d": -1.2, "change_pct_1w": 2.0},
        {"symbol": "XLK", "name": "科技", "change_pct_1d": 2.5, "change_pct_1w": 5.0},
    ]
    result = build_sector_rotation_context(data)
    assert [item["symbol"] for item in result] == ["XLK", "XLE"]


def test_build_oil_context_passes_through_data():
    from scripts.report_render import build_oil_context

    data = {"wti": {"symbol": "CL=F", "name": "WTI 原油", "history": [{"date": "2026-07-01", "value": 68.5}]},
            "brent": {"symbol": "BZ=F", "name": "Brent 原油", "history": []}}
    assert build_oil_context(data) == data
```

- [ ] **Step 2: Run test 確認失敗**

Run: `pytest tests/test_report_render.py -v`（新增的 4 個測試應該 FAIL，函式不存在）

- [ ] **Step 3: 實作 4 個函式**

在 `scripts/report_render.py`（`build_earnings_context` 之後、`build_template_context` 之前）新增：

```python
def build_korea_context(korea_data):
    """korea_data 來自 data_fetchers.fetch_korea_market()，原樣傳遞（欄位已符合模板需求）。"""
    return korea_data


def _heatmap_color_class(change_pct):
    """依漲跌 % 分 5 級著色，門檻取一般美股熱力圖常見的 ±0.5% / ±2% 分界。"""
    if change_pct >= 2:
        return "heat-strong-up"
    if change_pct >= 0.5:
        return "heat-up"
    if change_pct <= -2:
        return "heat-strong-down"
    if change_pct <= -0.5:
        return "heat-down"
    return "heat-flat"


def build_heatmap_context(heatmap_data):
    """幫每檔股票加上依漲跌 % 決定的 CSS 著色class。"""
    return [{**item, "color_class": _heatmap_color_class(item["change_pct"])} for item in heatmap_data]


def build_sector_rotation_context(sector_data):
    """依當日漲跌% 由高到低排序，資金輪動表格由強到弱呈現。"""
    return sorted(sector_data, key=lambda item: item["change_pct_1d"], reverse=True)


def build_oil_context(oil_data):
    """oil_data 來自 data_fetchers.fetch_oil_prices()，原樣傳遞。"""
    return oil_data
```

- [ ] **Step 4: Run test 確認通過**

Run: `pytest tests/test_report_render.py -v`

- [ ] **Step 5: Commit**

```bash
git add scripts/report_render.py tests/test_report_render.py
git commit -m "feat: add context builders for Korea/heatmap/sector-rotation/oil sections"
```

---

### Task 6: `build_template_context()` 串接 4 個新 context key + 完整整合測試

**先做這個再做 Task 7（模板編輯）**：`build_template_context()` 是唯一入口，若先改模板讓它引用 `korea`/`heatmap`/`sector_rotation`/`oil` 這幾個 context key，而 `build_template_context()` 還沒供應這些 key，Jinja2 對 `{{ korea.KOSPI... }}` 這種在 Undefined 物件上鏈式存取兩層以上屬性的寫法會直接拋 `UndefinedError`（Plan 1 Task 9 已踩過這個坑）——會讓既有的 `test_build_template_context_and_render_produces_valid_html` 整合測試在 Task 6 跟 Task 7 之間出現一個必然失敗的中間狀態。先做這個任務，模板還沒引用這些 key 之前，新增的 context key 不會被使用但也不會造成任何問題（Jinja2 忽略沒被引用的 context 變數）。

**Files:**
- Modify: `scripts/report_render.py`
- Test: `tests/test_report_render.py`

- [ ] **Step 1: 修改 `build_template_context()` 簽章與回傳值**

在 `scripts/report_render.py` 的 `build_template_context()` 新增 4 個關鍵字參數與對應 context key：

```python
def build_template_context(*, date_label, weekday_cn, tw_holiday_note,
                            quotes, fear_data, pe_data, institutional_data,
                            earnings_list, narrative_json,
                            korea_data, heatmap_data, sector_rotation_data, oil_data):
    """把所有預抓資料 + AI 敘述 JSON 組成 render_report() 需要的完整 context dict。"""
    return {
        # ...既有內容全部保留...
        "korea": build_korea_context(korea_data),
        "heatmap": build_heatmap_context(heatmap_data),
        "sector_rotation": build_sector_rotation_context(sector_rotation_data),
        "oil": build_oil_context(oil_data),
    }
```

（新增的 4 個參數用關鍵字參數方式加在既有參數列表尾端，維持向後相容的呼叫慣例；實作時把新的 4 行加進既有 `return {...}` dict 內，其餘既有 key 不動。）

- [ ] **Step 2: 更新既有整合測試，補上新 context key**

在 `tests/test_report_render.py` 的 `test_build_template_context_and_render_produces_valid_html` 呼叫 `build_template_context(...)` 的地方，新增：

```python
        korea_data={"KOSPI": {"symbol": "^KS11", "name": "KOSPI 指數", "price": 3100.0, "change": 25.0, "change_pct": 0.81}},
        heatmap_data=[{"symbol": "AAPL", "change_pct": 1.5}],
        sector_rotation_data=[{"symbol": "XLK", "name": "科技", "change_pct_1d": 1.2, "change_pct_1w": 3.0}],
        oil_data={"wti": {"symbol": "CL=F", "name": "WTI 原油", "history": [{"date": "2026-07-01", "value": 68.5}]},
                  "brent": {"symbol": "BZ=F", "name": "Brent 原油", "history": [{"date": "2026-07-01", "value": 72.0}]}},
```

並新增斷言確認這 4 個區塊的內容出現在渲染輸出中（此時模板還沒有對應區塊，這些字串不會出現在輸出裡——先把斷言加上但保持註解狀態，Task 7 做完模板後再取消註解）：

```python
    # Task 7（模板新增區塊）完成後再取消下面這幾行的註解：
    # assert "KOSPI 指數" in html
    # assert "AAPL" in html
    # assert "XLK" in html
    # assert "68.5" in html
```

- [ ] **Step 3: Run test 確認通過**

Run: `pytest tests/test_report_render.py -v`
Expected: 全部 PASS（新的 4 個 context key 已經傳入但模板還沒使用，不影響既有渲染結果）

- [ ] **Step 4: Commit**

```bash
git add scripts/report_render.py tests/test_report_render.py
git commit -m "feat: wire Korea/heatmap/sector-rotation/oil into build_template_context()"
```

---

### Task 7: 模板新增 4 個區塊

**Files:**
- Modify: `templates/report.html.j2`
- Test: `tests/test_report_render.py`

- [ ] **Step 1: 找到既有 VIX 圖表區塊的確切位置**

Run: `grep -n 'VIX CHART\|vixChart\|P/E CHART' templates/report.html.j2`

以現有 VIX 圖表區塊（`<!-- ══ VIX CHART ══ -->` 到其後 `</div></div>` 結束）與 P/E 圖表區塊之間或之後的位置，作為插入點——4 個新區塊依序插入在 P/E 圖表區塊之後、台指期夜盤區塊之前（用 `grep -n 'FUTURES\|夜盤動態'` 找到確切行號）。若實際檔案裡這幾個區塊的順序或名稱與描述不同，以檔案實際內容為準，選一個資料圖表類區塊集中的位置插入，維持「所有純數字/圖表區塊放在一起、敘述性區塊放在另一群」的既有分區邏輯。

- [ ] **Step 2: 韓國股市卡片區塊**

```html
<!-- ══════════════════════ KOREA MARKET ══════════════════════ -->
<div class="section">
  <div class="container">
    <div class="sec-title">
      <span class="sec-title-icon">🇰🇷</span> 韓國股市
      <span class="sec-subtitle">{{ date_label }}</span>
    </div>
    <div class="kpi-grid">
      {% for key in ["KOSPI", "SAMSUNG", "SK_HYNIX"] %}
      {% if korea.get(key) %}
      {% set item = korea[key] %}
      <div class="kpi-card">
        <div class="kpi-label">{{ item.name }}</div>
        <div class="kpi-val {{ 'green' if item.change >= 0 else 'red' }}">{{ '{:,g}'.format(item.price) }}</div>
        <div class="kpi-sub"><span class="kpi-change {{ 'green' if item.change >= 0 else 'red' }}">{{ '{:+,g}'.format(item.change) }} ({{ '{:+.2f}'.format(item.change_pct) }}%)</span></div>
      </div>
      {% endif %}
      {% endfor %}
    </div>
  </div>
</div>
```

- [ ] **Step 3: 美股熱力圖區塊（新增 CSS + HTML）**

先在 `<style>` 區塊新增熱力圖格子樣式（放在既有 `.kpi-card`/`.theme-card` 等卡片樣式附近）：

```css
.heatmap-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(90px, 1fr)); gap:6px; }
.heatmap-cell { border-radius:6px; padding:10px 6px; text-align:center; font-family:'IBM Plex Mono',monospace; }
.heatmap-symbol { font-size:12px; font-weight:700; color:var(--text-primary); }
.heatmap-pct { font-size:11px; margin-top:2px; }
.heat-strong-up { background:rgba(0,230,118,0.35); }
.heat-up { background:rgba(0,230,118,0.15); }
.heat-flat { background:var(--bg3); }
.heat-down { background:rgba(255,61,113,0.15); }
.heat-strong-down { background:rgba(255,61,113,0.35); }
```

HTML 區塊：

```html
<!-- ══════════════════════ US HEATMAP ══════════════════════ -->
<div class="section">
  <div class="container">
    <div class="sec-title">
      <span class="sec-title-icon">🗺️</span> 美股熱力圖
      <span class="sec-subtitle">{{ date_label }} 當日漲跌</span>
    </div>
    <div class="heatmap-grid">
      {% for item in heatmap %}
      <div class="heatmap-cell {{ item.color_class }}">
        <div class="heatmap-symbol">{{ item.symbol }}</div>
        <div class="heatmap-pct">{{ '{:+.2f}'.format(item.change_pct) }}%</div>
      </div>
      {% endfor %}
    </div>
  </div>
</div>
```

- [ ] **Step 4: 美股資金板塊輪動區塊**

```html
<!-- ══════════════════════ SECTOR ROTATION ══════════════════════ -->
<div class="section">
  <div class="container">
    <div class="sec-title">
      <span class="sec-title-icon">🔄</span> 美股資金板塊輪動
      <span class="sec-subtitle">11 檔 SPDR 產業 ETF · 依當日表現排序</span>
    </div>
    <div class="chart-card">
      <table class="risk-table">
        <thead><tr><th>產業</th><th>代號</th><th>當日</th><th>一週</th></tr></thead>
        <tbody>
          {% for item in sector_rotation %}
          <tr>
            <td>{{ item.name }}</td>
            <td>{{ item.symbol }}</td>
            <td class="{{ 'green' if item.change_pct_1d >= 0 else 'red' }}">{{ '{:+.2f}'.format(item.change_pct_1d) }}%</td>
            <td class="{{ 'green' if item.change_pct_1w >= 0 else 'red' }}">{{ '{:+.2f}'.format(item.change_pct_1w) }}%</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
```

（`class="green"`/`"red"` 沿用模板既有的文字顏色 class，同一份 CSS 已經在其他區塊定義過，不需要重新定義。實作前用 `grep -n '^\.green\b\|^\.red\b' templates/report.html.j2` 確認這兩個 class 確實存在且語意相符——如果既有定義是用在別的地方且視覺不合適，改用 `style="color:var(--accent-green)"`/`style="color:var(--accent-red)"` 內嵌樣式代替，不要修改既有 class 定義。）

- [ ] **Step 5: 油價走勢圖區塊（比照 VIX 圖表做法）**

HTML（沿用 VIX 圖表的 `<canvas>` + 圖例結構，但畫兩條線）：

```html
<!-- ══════════════════════ OIL CHART ══════════════════════ -->
<div class="section">
  <div class="container">
    <div class="sec-title">
      <span class="sec-title-icon">🛢️</span> 油價走勢 — 近 6 個月
      <span class="sec-subtitle">{{ oil.wti.history[0].date if oil.wti.history else "—" }} ～ {{ oil.wti.history[-1].date if oil.wti.history else "—" }}</span>
    </div>
    <div class="chart-card">
      <div class="chart-title">WTI / Brent 原油價格（美元/桶）</div>
      <canvas id="oilChart" height="90"></canvas>
    </div>
  </div>
</div>
```

JS（放在既有 VIX 圖表 `<script>` 邏輯附近，`buildPEChart()` 之後、LLY 圖表之前皆可）：

```js
// ─── OIL CHART ───
const oilWtiRaw = {{ oil.wti.history | tojson }};
const oilBrentRaw = {{ oil.brent.history | tojson }};
const oilLabels = oilWtiRaw.map(d => { const p = d.date.split('-'); return `${p[1]}/${p[2]}`; });
const oilCtx = document.getElementById('oilChart').getContext('2d');
new Chart(oilCtx, {
  type: 'line',
  data: {
    labels: oilLabels,
    datasets: [
      {
        label: 'WTI', data: oilWtiRaw.map(d => d.value),
        borderColor: '#ffa726', backgroundColor: 'transparent',
        borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 4, tension: 0.3,
      },
      {
        label: 'Brent', data: oilBrentRaw.map(d => d.value),
        borderColor: '#00d4ff', backgroundColor: 'transparent',
        borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 4, tension: 0.3,
      }
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: true,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: true, labels: { color: '#c8d0ec', font: { family: 'IBM Plex Mono', size: 10 } } },
      datalabels: { display: false },
      tooltip: {
        backgroundColor: 'rgba(4,4,13,0.92)', titleColor: '#c8d0ec', bodyColor: '#f0f2fc',
        borderColor: '#2a2a4a', borderWidth: 1,
      }
    },
    scales: {
      x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#c8d0ec', maxTicksLimit: 12, font: { family: 'IBM Plex Mono', size: 10 } }, border: { color: 'rgba(255,255,255,0.08)' } },
      y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#c8d0ec', font: { family: 'IBM Plex Mono', size: 10 } }, border: { color: 'rgba(255,255,255,0.08)' } }
    }
  }
});
```

（`oilBrentRaw` 假設與 `oilWtiRaw` 日期一一對應，因為兩者都用同一個 `fetch_fear_index_history` 邏輯、同一個 `period="6mo"` 抓取，實際交易日曆應該一致；若某天其中一個標的缺資料導致長度不一致，Chart.js 對過短的 `data` 陣列會自動以 `null` 補齊繪圖區，不會報錯，属可接受的降級行為，不需要額外處理。）

- [ ] **Step 6: 取消 Task 6 留下的註解斷言，確認整合測試通過**

回到 `tests/test_report_render.py` 的 `test_build_template_context_and_render_produces_valid_html`，把 Task 6 Step 2 加的註解斷言取消註解：

```python
    assert "KOSPI 指數" in html
    assert "AAPL" in html
    assert "XLK" in html
    assert "68.5" in html
```

Run: `pytest tests/test_report_render.py -v`
Expected: 全部 PASS，這 4 個新斷言現在應該真的通過（模板區塊 + context 都已經就緒）

- [ ] **Step 7: Commit**

```bash
git add templates/report.html.j2 tests/test_report_render.py
git commit -m "feat: add Korea market, US heatmap, sector rotation, and oil price template sections"
```

---

### Task 8: `generate_report.py` 主流程串接 4 個新抓取呼叫

**Files:**
- Modify: `scripts/generate_report.py`
- Test: `tests/conftest.py`（更新 stub）

- [ ] **Step 1: 匯入與呼叫**

在 `from scripts.data_fetchers import (...)` 的 import 清單新增 `fetch_korea_market`、`fetch_us_heatmap`、`fetch_sector_rotation`、`fetch_oil_prices`。

在 `fetch_quotes()` 呼叫之後（同一個 prefetch 區塊內）新增：

```python
print("  正在用 yfinance 抓取韓國股市...")
korea_data = fetch_korea_market()

print("  正在用 yfinance 抓取美股熱力圖資料...")
heatmap_data = fetch_us_heatmap()

print("  正在用 yfinance 抓取美股產業輪動資料...")
sector_rotation_data = fetch_sector_rotation()

print("  正在用 yfinance 抓取油價走勢...")
oil_data = fetch_oil_prices()
```

這 4 個區塊全部是「Python 算好、不經過 AI」的資料，**不需要**注入 prompt（跟 quotes 不同——quotes 需要給 AI 參考來寫 daily_brief/hero_events 等敘述，但韓股/熱力圖/板塊輪動/油價目前的設計沒有對應的 AI 敘述文字要求，純粹是模板直接渲染的獨立區塊）。

- [ ] **Step 2: 更新 `build_template_context()` 呼叫**

在既有的 `build_template_context(...)` 呼叫新增這 4 個引數：

```python
context = build_template_context(
    date_label=date_label,
    weekday_cn=weekday_cn,
    tw_holiday_note=tw_holiday_note,
    quotes=quotes,
    fear_data=fear_data,
    pe_data=pe_data,
    institutional_data=institutional_data,
    earnings_list=earnings_data,
    narrative_json=narrative_json,
    korea_data=korea_data,
    heatmap_data=heatmap_data,
    sector_rotation_data=sector_rotation_data,
    oil_data=oil_data,
)
```

- [ ] **Step 3: 更新 `tests/conftest.py` 的 stub**

`_stub_and_import_generate_report()` 裡的 `originals` dict 與後續替換/還原邏輯，新增 `fetch_korea_market`、`fetch_us_heatmap`、`fetch_sector_rotation`、`fetch_oil_prices` 四個函式的暫存與假實作（比照既有 `fetch_all_fear_index` 的模式，回傳最小但合法的假資料，避免真的打 yfinance）：

```python
data_fetchers.fetch_korea_market = lambda *_a, **_k: {}
data_fetchers.fetch_us_heatmap = lambda *_a, **_k: []
data_fetchers.fetch_sector_rotation = lambda *_a, **_k: []
data_fetchers.fetch_oil_prices = lambda *_a, **_k: {
    "wti": {"symbol": "CL=F", "name": "WTI 原油", "history": []},
    "brent": {"symbol": "BZ=F", "name": "Brent 原油", "history": []},
}
```

同時要加進 `originals` dict（暫存＋還原清單）與 `finally` 區塊的還原邏輯，比照現有 7 個函式的寫法。

- [ ] **Step 4: Run 全部測試**

Run: `pytest tests/ -v`
Expected: 全部 PASS（此時測試總數應該比 Plan 1 結束時多這份 plan 新增的測試筆數）

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_report.py tests/conftest.py
git commit -m "feat: wire Korea/heatmap/sector-rotation/oil fetchers into main flow"
```

---

### Task 9: 端到端人工驗證

**Files:** 無新檔案，僅執行驗證

- [ ] **Step 1: 用真實資料跑一次完整 context 組裝 + 渲染（不需要 ANTHROPIC_API_KEY，繞過 Claude 呼叫）**

```bash
python -c "
from scripts.data_fetchers import fetch_korea_market, fetch_us_heatmap, fetch_sector_rotation, fetch_oil_prices, fetch_quotes, fetch_all_pe_data, fetch_all_fear_index
from scripts.report_render import build_template_context, render_report
from tests.test_report_render import _fake_narrative_json

korea = fetch_korea_market()
heatmap = fetch_us_heatmap()
sector = fetch_sector_rotation()
oil = fetch_oil_prices()
quotes = fetch_quotes()
pe = fetch_all_pe_data()
fear = fetch_all_fear_index()

ctx = build_template_context(
    date_label='2026.07.04', weekday_cn='週六', tw_holiday_note='',
    quotes=quotes, fear_data=fear, pe_data=pe, institutional_data=None,
    earnings_list=[], narrative_json=_fake_narrative_json(),
    korea_data=korea, heatmap_data=heatmap, sector_rotation_data=sector, oil_data=oil,
)
html = render_report(ctx)
open('/tmp/preview_plan2.html', 'w', encoding='utf-8').write(html)
print(f'rendered {len(html)} bytes')
print(f'korea: {len(korea)} entries, heatmap: {len(heatmap)} entries, sector: {len(sector)} entries')
"
```

Expected: 印出合理的抓取筆數（韓股 2-3 檔、熱力圖 30+ 檔、產業輪動 11 檔）、渲染成功、無例外。

- [ ] **Step 2: 檢查輸出**

用瀏覽器打開 `/tmp/preview_plan2.html`（或用 grep 檢查沒有殘留 `{{`/`{%` 標記），確認：
- 韓國股市 3 張卡片正常顯示（KOSPI/三星/SK海力士）
- 熱力圖格子依漲跌著色，顏色符合預期（大漲深綠、大跌深紅、持平灰色）
- 產業輪動表格依當日漲跌排序，11 檔都出現
- 油價走勢圖能畫出兩條線（WTI/Brent）

- [ ] **Step 3: 確認 `pytest tests/ -v` 全數通過，且沒有殘留測試產物**

```bash
pytest tests/ -v
git status --short
```

Expected: 全過、工作區乾淨。

---

## Plan 完成後的狀態

- `templates/report.html.j2` 新增 4 個純資料驅動區塊，皆不經過 AI，降低幻覺風險與 token 成本
- `scripts/data_fetchers.py`／`scripts/report_render.py` 延續 Plan 1 建立的「fetch_* → build_*_context → build_template_context」三層模式，之後若要再加新的純數字區塊，照抄這個模式即可
- 下一份 plan（台股選股訊號評分系統）會是量體最大的一份，因為需要新的持久化狀態（`data/stock_signals_history.json`）與較多的 TWSE OpenAPI 資料集探索
