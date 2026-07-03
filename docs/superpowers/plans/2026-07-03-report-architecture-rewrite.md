# 報告架構重寫（模板 + JSON 資料分離）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「AI 每天生成整份 100KB+ HTML」改成「Python 用 Jinja2 模板 + 預抓資料算好的圖表/表格，AI 只負責回傳一份 JSON 敘述性內容」，同時把 `scripts/generate_report.py` 拆成 `data_fetchers.py` / `report_render.py` / `generate_report.py` 三個檔案。

**Architecture:** 新增 `scripts/data_fetchers.py`（所有 yfinance/TWSE 預抓函式，含新增的即時報價抓取 `fetch_quotes`）與 `scripts/report_render.py`（Jinja2 渲染邏輯）。`templates/report.html.j2` 取代「AI 生成整份 HTML」，CSS/JS 骨架照抄現有 `Backup/2026-07-03.html`，把逐日變動的內容改成 Jinja2 變數/迴圈。`scripts/generate_report.py` 縮減為協調者：抓資料 → 呼叫 Claude 取得敘述 JSON → 呼叫 render → 驗證 → 寫檔。

**Tech Stack:** Python 3.11、Jinja2（新增依賴）、yfinance、anthropic SDK、pytest（新增測試框架，此專案目前無測試）。

**這份 plan 是三份 plan 中的第一份**（依 spec `docs/superpowers/specs/2026-07-03-report-architecture-and-features-design.md` 的 A 節 + 已修正的 D 節）。B（新資料區塊）與 C（選股訊號評分）會在這份 plan 完成、驗證過一次完整報告產出後，各自成為獨立 plan，因為它們都要接在這裡新建的模板機制上。

---

## 前置事實（寫 plan 前已查證，實作時不需重新確認）

- 現有 `scripts/generate_report.py`（698 行）已有的抓取函式：`fetch_earnings_calendar`、`fetch_all_pe_data`（含 `fetch_pe_history`）、`fetch_all_fear_index`（含 `fetch_fear_index_history`）、`fetch_institutional_3day_ranking`（含 `_fetch_twse_t86`、`_fetch_twse_close_prices`）、`is_prev_us_day_holiday`/`is_prev_tw_day_holiday`、`load_market_analysis_prompt`。
- 通知摘要機制**已存在且不需重做**：`generate_report.py` 目前從 AI 輸出的 HTML 用 `<!--SUMMARY ... SUMMARY-->` 註解 regex 抓兩三行摘要（第 685–697 行），寫進 `GITHUB_OUTPUT` 的 `summary` 輸出變數；`.github/workflows/daily-update.yml` 的 Telegram（62–77 行）、LINE（86–100 行）、Email（`send_email.py` 19–26 行）三個通知都已經讀這個 `summary` 並接在訊息最前面。本次只需把「摘要來源」從 regex 改成直接讀 AI 回傳 JSON 的 `daily_brief` 欄位，`GITHUB_OUTPUT` 寫入與 workflow 端完全不動。
- `Backup/2026-07-03.html`（1789 行）是目前唯一格式正確、內容完整的最新報告，做為模板的具體藍本。關鍵行號：
  - 1–30：`<head>`、Google Fonts、Chart.js CDN、`:root` CSS 變數（原樣照抄，不需參數化）
  - 444–450：ticker 跑馬燈容器
  - 477–501：hero 兩張卡片（今日重大事件 #1 / #2）
  - 513：五項預警指標 grid 容器
  - 571–612：KPI 儀表板兩排共 8 張卡片
  - 764：VIX 圖表 canvas
  - 784–799：P/E 圖表兩個 tab 切換
  - 882–991：法人連三日排行兩個 tab 面板（外資／投信，各自買超/賣超兩欄表格）
  - 1035：財報速覽表格
  - 1073–1180：新聞中心四個 tab 面板（AI/半導體、總體經濟、地緣政治、IPO）
  - 1297–1340：五張主題卡片
  - 1355–1381：三張策略卡片
  - 1419 起 `<script>`：ticker 資料陣列 + `innerHTML` 組字串（1420–1450）、VIX 圖表資料與 Chart.js 設定（1452–1545）、P/E 圖表資料與 `buildPEChart()`（1547–1671）
- Chart.js 繪圖邏輯（VIX、P/E 圖表的 `new Chart(...)` 設定、顏色判斷、tooltip 樣式）本身不需要重寫——它們現在就是讀一個 JS 陣列/物件常數（`vixRaw`、`peData`）畫圖。重寫後這兩個常數改成 Jinja2 `{{ ... | tojson }}` 直接注入預抓資料，繪圖 JS 逐字保留。
- `validate_html()`（698 行檔案的第 655–665 行）與四項檢查（最小長度、`</html>` 結尾、`<table`/`<canvas`/`<script` 存在）保留不動，只是改成檢查「Jinja2 渲染後的最終 HTML」而不是「AI 直接輸出的 HTML」。

---

## File Structure

| 檔案 | 動作 | 職責 |
|---|---|---|
| `requirements.txt` | 修改 | 新增 `jinja2==3.1.6`、`pytest==8.3.4` |
| `scripts/data_fetchers.py` | 新建 | 搬移現有全部 `fetch_*`/`is_prev_*_holiday`/`load_market_analysis_prompt` 函式；新增 `fetch_quotes()` |
| `scripts/report_render.py` | 新建 | `build_template_context()`（把預抓資料轉成模板變數）、`render_report(context)`（Jinja2 渲染） |
| `templates/report.html.j2` | 新建 | 從 `Backup/2026-07-03.html` 改寫，CSS/JS 骨架照抄，逐日內容改 Jinja2 變數/迴圈 |
| `scripts/generate_report.py` | 大幅修改 | 縮減為協調：import fetchers → 組 prompt（JSON schema）→ 呼叫 Claude → 解析 JSON → `render_report()` → `validate_html()` → 寫檔 → 通知摘要輸出 |
| `tests/test_data_fetchers.py` | 新建 | `fetch_quotes()`、既有函式搬移後的 import/行為測試 |
| `tests/test_report_render.py` | 新建 | 模板渲染測試（給定假資料，渲染出的 HTML 含預期標籤/數值） |
| `tests/test_generate_report.py` | 新建 | JSON 解析、`validate_html`、通知摘要輸出的單元測試 |

---

### Task 1: 新增測試框架與 Jinja2 依賴

**Files:**
- Modify: `requirements.txt`
- Create: `tests/__init__.py`（空檔案，讓 pytest 能找到套件）

- [ ] **Step 1: 修改 `requirements.txt`**

```text
anthropic==0.116.0
requests==2.34.2
yfinance==1.5.1
exchange-calendars==4.13.2
jinja2==3.1.6
pytest==8.3.4
```

- [ ] **Step 2: 建立空的 `tests/__init__.py`**

```python
```

- [ ] **Step 3: 安裝依賴並確認 pytest 可執行**

Run: `pip install -r requirements.txt && pytest --version`
Expected: 印出 pytest 版本號，無錯誤

- [ ] **Step 4: Commit**

```bash
git add requirements.txt tests/__init__.py
git commit -m "chore: add jinja2 + pytest dependencies for report architecture rewrite"
```

---

### Task 2: 搬移既有抓取函式到 `scripts/data_fetchers.py`

**Files:**
- Create: `scripts/data_fetchers.py`
- Modify: `scripts/generate_report.py`（刪除已搬移的函式定義，改為 import）
- Test: `tests/test_data_fetchers.py`

現有 `generate_report.py` 第 12–370 行（`is_prev_us_day_holiday` 到 `fetch_all_fear_index` 為止，含 `fetch_institutional_3day_ranking` 與 `load_market_analysis_prompt`）整段搬到新檔案，函式簽章、內部邏輯完全不變（純檔案搬移，不重構邏輯）。

- [ ] **Step 1: 建立 `scripts/data_fetchers.py`，貼入原檔案第 1–370 行的全部函式**

把 `scripts/generate_report.py` 現有第 1–370 行（`import` 區到 `fetch_all_fear_index` 結尾）整段剪下，貼到新檔案 `scripts/data_fetchers.py`，檔頭改成：

```python
"""
每日報告用的所有資料預抓函式：yfinance（財報日曆／P/E／VIX／即時報價）、
TWSE OpenAPI（法人連三日買賣超）、假日判斷、市場分析 prompt 讀取。
"""
import requests
from datetime import datetime, timedelta
```

（原本檔案內 `import anthropic`、`import os`、`import re`、`import shutil` 這幾個在搬移的函式範圍內用不到，不要帶過來；`import json` 也不需要，各函式內部已有各自的 `import yfinance as yf` / `import exchange_calendars as xcals` / `import requests`。）

- [ ] **Step 2: 確認搬移後檔案內容**

檔案應包含以下函式（依原順序）：`_is_prev_day_holiday`、`is_prev_us_day_holiday`、`is_prev_tw_day_holiday`、`EARNINGS_WATCH`、`fetch_earnings_calendar`、`format_earnings_for_prompt`、`PE_TICKERS`、`fetch_pe_history`、`fetch_all_pe_data`、`_fetch_twse_t86`、`_fetch_twse_close_prices`、`fetch_institutional_3day_ranking`、`load_market_analysis_prompt`、`FEAR_INDEX_TICKERS`、`fetch_fear_index_history`、`fetch_all_fear_index`。

Run: `python -c "import scripts.data_fetchers as df; print([n for n in dir(df) if not n.startswith('_')])"`
Expected: 印出上述函式/常數名稱（不含底線開頭的私有函式），無 ImportError

- [ ] **Step 3: 更新 `scripts/generate_report.py`，刪除搬移的函式定義，改為 import**

刪除原檔案第 1–370 行，改成：

```python
"""
Daily Investment Report Generator
每天自動呼叫 Claude API + web_search（伺服器端工具），生成 HTML 報告並備份舊報告
使用串流模式（SDK 要求：max_tokens 較大時必須用 streaming，避免長時間請求被中斷）
"""
import anthropic
import json
import os
import shutil
from datetime import datetime, timezone, timedelta

from scripts.data_fetchers import (
    is_prev_us_day_holiday,
    is_prev_tw_day_holiday,
    fetch_earnings_calendar,
    format_earnings_for_prompt,
    fetch_all_pe_data,
    fetch_institutional_3day_ranking,
    load_market_analysis_prompt,
    fetch_all_fear_index,
)
```

- [ ] **Step 4: 寫測試確認搬移後兩個模組都能正常 import 且互不衝突**

`tests/test_data_fetchers.py`:

```python
def test_data_fetchers_module_importable():
    import scripts.data_fetchers as df
    assert callable(df.fetch_earnings_calendar)
    assert callable(df.fetch_all_pe_data)
    assert callable(df.fetch_institutional_3day_ranking)
    assert callable(df.fetch_all_fear_index)
    assert callable(df.is_prev_us_day_holiday)
    assert callable(df.is_prev_tw_day_holiday)
    assert callable(df.load_market_analysis_prompt)
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_data_fetchers.py -v`
Expected: `test_data_fetchers_module_importable` PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/data_fetchers.py scripts/generate_report.py tests/test_data_fetchers.py
git commit -m "refactor: extract data fetchers into scripts/data_fetchers.py"
```

---

### Task 3: 新增 `fetch_quotes()`（即時報價，取代 AI 手key 的 ticker/KPI 數字）

**Files:**
- Modify: `scripts/data_fetchers.py`
- Test: `tests/test_data_fetchers.py`

目前 ticker 跑馬燈、KPI 儀表板的數字都是 AI 用 web_search 找到後手動寫死在 HTML 裡。新增 `fetch_quotes()`，用 yfinance 一次抓取固定清單的最新收盤價與日漲跌，取代這些手key數字。

固定清單（涵蓋現有 ticker 跑馬燈 + KPI 卡片需要的全部標的）：

```python
QUOTE_TICKERS = {
    "TWII":  ("^TWII", "加權指數"),
    "2330":  ("2330.TW", "台積電"),
    "2317":  ("2317.TW", "鴻海"),
    "2454":  ("2454.TW", "聯發科"),
    "0050":  ("0050.TW", "0050"),
    "SPX":   ("^GSPC", "S&P 500"),
    "NASDAQ":("^IXIC", "Nasdaq"),
    "DOW":   ("^DJI", "Dow"),
    "NVDA":  ("NVDA", "NVIDIA"),
    "AVGO":  ("AVGO", "Broadcom"),
    "LLY":   ("LLY", "Eli Lilly"),
    "ORCL":  ("ORCL", "Oracle"),
    "SMH":   ("SMH", "SMH ETF"),
    "IAUM":  ("IAUM", "IAUM 黃金"),
    "VIX":   ("^VIX", "VIX"),
    "US10Y": ("^TNX", "10Y 美債殖利率"),
    "WTI":   ("CL=F", "WTI 原油"),
}
```

- [ ] **Step 1: 寫失敗測試**

`tests/test_data_fetchers.py`（append）:

```python
def test_fetch_quotes_returns_price_and_change_for_each_ticker(monkeypatch):
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            # 兩個交易日：昨收 100，今收 105（漲 5%）
            return pd.DataFrame(
                {"Close": [100.0, 105.0]},
                index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_quotes()

    assert set(result.keys()) == set(df.QUOTE_TICKERS.keys())
    twii = result["TWII"]
    assert twii["symbol"] == "^TWII"
    assert twii["name"] == "加權指數"
    assert twii["price"] == 105.0
    assert twii["change"] == 5.0
    assert round(twii["change_pct"], 2) == 5.0
```

- [ ] **Step 2: Run test 確認失敗**

Run: `pytest tests/test_data_fetchers.py::test_fetch_quotes_returns_price_and_change_for_each_ticker -v`
Expected: FAIL，`AttributeError: module 'scripts.data_fetchers' has no attribute 'fetch_quotes'` 或 `QUOTE_TICKERS`

- [ ] **Step 3: 實作 `fetch_quotes()`**

在 `scripts/data_fetchers.py` 檔尾新增：

```python
# ── 即時報價：ticker 跑馬燈 / KPI 儀表板用，取代 AI 手key 數字 ──────────────

QUOTE_TICKERS = {
    "TWII":  ("^TWII", "加權指數"),
    "2330":  ("2330.TW", "台積電"),
    "2317":  ("2317.TW", "鴻海"),
    "2454":  ("2454.TW", "聯發科"),
    "0050":  ("0050.TW", "0050"),
    "SPX":   ("^GSPC", "S&P 500"),
    "NASDAQ":("^IXIC", "Nasdaq"),
    "DOW":   ("^DJI", "Dow"),
    "NVDA":  ("NVDA", "NVIDIA"),
    "AVGO":  ("AVGO", "Broadcom"),
    "LLY":   ("LLY", "Eli Lilly"),
    "ORCL":  ("ORCL", "Oracle"),
    "SMH":   ("SMH", "SMH ETF"),
    "IAUM":  ("IAUM", "IAUM 黃金"),
    "VIX":   ("^VIX", "VIX"),
    "US10Y": ("^TNX", "10Y 美債殖利率"),
    "WTI":   ("CL=F", "WTI 原油"),
}


def fetch_quotes():
    """
    抓取 QUOTE_TICKERS 全部標的最新收盤價與日漲跌（%）。
    單一標的失敗不影響其他標的；該標的從結果中省略，由呼叫端決定如何顯示缺值。
    """
    import yfinance as yf

    result = {}
    for key, (symbol, name) in QUOTE_TICKERS.items():
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
    print(f"  即時報價：成功 {len(result)}/{len(QUOTE_TICKERS)} 檔")
    return result
```

（測試用 `monkeypatch.setattr(df.yf, "Ticker", FakeTicker)`，因此 `import yfinance as yf` 需要放在模組層級而不是函式內——修改成模組頂部 `import yfinance as yf`，並把既有函式內重複的 `import yfinance as yf` 行都可以保留不動，Python 允許重複 import，不衝突。）

在檔案最上方（`import requests` 旁）加一行：

```python
import yfinance as yf
```

- [ ] **Step 4: Run test 確認通過**

Run: `pytest tests/test_data_fetchers.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/data_fetchers.py tests/test_data_fetchers.py
git commit -m "feat: add fetch_quotes() for Python-computed ticker/KPI numbers"
```

---

### Task 4: 建立 `templates/report.html.j2` — CSS/JS 骨架 + ticker/KPI/警示區塊參數化

**Files:**
- Create: `templates/report.html.j2`
- Test: `tests/test_report_render.py`

- [ ] **Step 1: 複製藍本檔案**

```bash
mkdir -p templates
cp "Backup/2026-07-03.html" templates/report.html.j2
```

- [ ] **Step 2: 修改 `<head>` 區塊（第 1–9 行），標題改參數化**

把：
```html
<title>每日投資情報 — 2026.07.03 週五</title>
```
改成：
```html
<title>每日投資情報 — {{ date_label }} {{ weekday_cn }}</title>
```
其餘 `<head>` 內容（Google Fonts、Chart.js CDN、`:root` CSS 變數，第 3–30 行）完全不動。

- [ ] **Step 3: 台股休市 badge 參數化**

找到 `.header-badges` 附近的 badge 區塊（搜尋 `badge-live`），確認現有結構後在 badge 清單後面加入條件式假日提示：

```html
<div class="header-badges">
  <span class="badge badge-live">LIVE</span>
  <span class="badge badge-tw">台股</span>
  <span class="badge badge-us">美股</span>
  {% if tw_holiday_note %}
  <span class="badge badge-holiday">台股休市</span>
  {% endif %}
</div>
```

- [ ] **Step 4: Ticker 跑馬燈資料參數化（原第 1421–1439 行）**

原本的 JS 陣列常數：

```js
const tickerData = [
  { sym:'加權指數', price:'46,744', chg:'+274', pct:'+0.58%', up:true },
  ...
];
```

改成：

```js
const tickerData = {{ ticker_data | tojson }};
```

其餘第 1440–1450 行（`innerHTML` 組字串邏輯）完全不動。

`ticker_data` 由 `scripts/report_render.py` 的 `build_template_context()` 從 `fetch_quotes()` 結果組出，格式（每個元素對應一檔）：

```python
{"sym": "加權指數", "price": "46,744", "chg": "+274", "pct": "+0.58%", "up": True}
```

- [ ] **Step 5: KPI 儀表板參數化（原第 571–612 行，兩排共 8 張卡片）**

把整個兩個 `<div class="kpi-grid">...</div>` 區塊改成一個迴圈：

```html
<div class="kpi-grid">
  {% for kpi in kpi_cards[:4] %}
  <div class="kpi-card">
    <div class="kpi-label">{{ kpi.label }}</div>
    <div class="kpi-val {{ kpi.val_class }}">{{ kpi.val }}</div>
    <div class="kpi-sub"><span class="kpi-change {{ kpi.change_class }}">{{ kpi.change_text }}</span>{% if kpi.extra %} · {{ kpi.extra }}{% endif %}</div>
  </div>
  {% endfor %}
</div>
<div class="kpi-grid" style="margin-top:12px">
  {% for kpi in kpi_cards[4:8] %}
  <div class="kpi-card">
    <div class="kpi-label">{{ kpi.label }}</div>
    <div class="kpi-val {{ kpi.val_class }}">{{ kpi.val }}</div>
    <div class="kpi-sub"><span class="kpi-change {{ kpi.change_class }}">{{ kpi.change_text }}</span>{% if kpi.extra %} · {{ kpi.extra }}{% endif %}</div>
  </div>
  {% endfor %}
</div>
```

`kpi_cards` 是 8 個 dict 的 list，由 `report_render.py` 從 `fetch_quotes()` 結果建構，順序固定：加權指數、台積電、S&P 500、WTI 原油、聯發科、鴻海、IAUM 黃金、10Y 美債殖利率。`val_class`/`change_class` 依漲跌決定 `"green"`/`"red"`/`""`（持平）。

- [ ] **Step 6: 建立 `scripts/report_render.py`，實作 `build_template_context()` 的 ticker/KPI 部分**

```python
"""Jinja2 模板渲染：把預抓資料 + AI 敘述 JSON 組成模板變數，渲染出最終 HTML。"""
from jinja2 import Environment, FileSystemLoader


def _fmt_change(change, change_pct):
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:g} ({sign}{change_pct:.2f}%)"


def _val_class(change):
    if change > 0:
        return "green"
    if change < 0:
        return "red"
    return ""


def build_ticker_data(quotes):
    """把 fetch_quotes() 結果轉成 ticker 跑馬燈用的 list[dict]。"""
    order = ["TWII", "2330", "2317", "2454", "0050", "SPX", "NVDA", "AVGO",
             "LLY", "ORCL", "SMH", "IAUM", "VIX", "US10Y", "WTI"]
    items = []
    for key in order:
        q = quotes.get(key)
        if not q:
            continue
        items.append({
            "sym": q["name"],
            "price": f'{q["price"]:,g}',
            "chg": f'{"+" if q["change"] >= 0 else ""}{q["change"]:g}',
            "pct": f'{"+" if q["change_pct"] >= 0 else ""}{q["change_pct"]:.2f}%',
            "up": q["change"] >= 0,
        })
    return items


def build_kpi_cards(quotes):
    """固定 8 張卡片：加權指數/台積電/S&P500/WTI/聯發科/鴻海/IAUM/10Y殖利率。"""
    layout = [
        ("TWII", "台股加權指數"),
        ("2330", "台積電（2330）"),
        ("SPX", "S&P 500"),
        ("WTI", "原油（WTI）"),
        ("2454", "聯發科（2454）"),
        ("2317", "鴻海（2317）"),
        ("IAUM", "黃金（IAUM）"),
        ("US10Y", "10Y 美債殖利率"),
    ]
    cards = []
    for key, label in layout:
        q = quotes.get(key)
        if not q:
            cards.append({"label": label, "val": "N/A", "val_class": "",
                          "change_class": "", "change_text": "資料缺失", "extra": None})
            continue
        cards.append({
            "label": label,
            "val": f'{q["price"]:,g}',
            "val_class": _val_class(q["change"]),
            "change_class": _val_class(q["change"]),
            "change_text": _fmt_change(q["change"], q["change_pct"]),
            "extra": None,
        })
    return cards


def render_report(context):
    """用 templates/report.html.j2 渲染最終 HTML 字串。"""
    env = Environment(loader=FileSystemLoader("templates"), autoescape=False)
    template = env.get_template("report.html.j2")
    return template.render(**context)
```

（`autoescape=False`：這份模板輸出的是已經信任的內部資料（自家 API 抓的數字、Claude 回傳的敘述文字），不是使用者輸入，維持現行「AI 直接輸出 HTML」相同的信任等級；不需要 HTML escape。）

- [ ] **Step 7: 寫測試驗證 ticker/KPI 資料組裝邏輯**

`tests/test_report_render.py`:

```python
def test_build_ticker_data_formats_quotes():
    from scripts.report_render import build_ticker_data

    quotes = {
        "TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": 274.0, "change_pct": 0.59},
        "2330": {"symbol": "2330.TW", "name": "台積電", "price": 2400.0, "change": -5.0, "change_pct": -0.21},
    }
    result = {
        item["sym"]: item
        for item in __import__("scripts.report_render", fromlist=["build_ticker_data"]).build_ticker_data(quotes)
    }
    assert result["加權指數"]["up"] is True
    assert result["加權指數"]["pct"] == "+0.59%"
    assert result["台積電"]["up"] is False
    assert result["台積電"]["pct"] == "-0.21%"


def test_build_kpi_cards_marks_missing_quote_as_na():
    from scripts.report_render import build_kpi_cards

    cards = build_kpi_cards({})
    assert len(cards) == 8
    assert all(c["val"] == "N/A" for c in cards)


def test_render_report_produces_html_with_ticker_and_kpi_data(tmp_path, monkeypatch):
    from scripts.report_render import render_report
    monkeypatch.chdir(tmp_path.parent.parent)  # 確保相對路徑 templates/ 找得到（專案根目錄執行 pytest 時可省略）

    context = {
        "date_label": "2026.07.03", "weekday_cn": "週五", "tw_holiday_note": "",
        "ticker_data": [{"sym": "加權指數", "price": "46,744", "chg": "+274", "pct": "+0.59%", "up": True}],
        "kpi_cards": [{"label": "台股加權指數", "val": "46,744", "val_class": "green",
                        "change_class": "green", "change_text": "+274 (+0.59%)", "extra": None}] * 8,
    }
    html = render_report(context)
    assert "46,744" in html
    assert "</html>" in html.lower()
```

（這個測試只驗證 Task 4 已完成的變數；後續 Task 會補上其餘變數，屆時這個測試的 `context` 需要同步擴充，在 Task 8 統一處理成完整 context fixture。）

- [ ] **Step 8: Run test**

Run: `pytest tests/test_report_render.py -v`
Expected: 三個測試全部 PASS（此時模板只有 Task 4 這一步修改過的 ticker/KPI 區塊是 Jinja2 變數，其餘區塊仍是原始寫死內容，不影響這裡的驗證）

- [ ] **Step 9: Commit**

```bash
git add templates/report.html.j2 scripts/report_render.py tests/test_report_render.py
git commit -m "feat: parameterize ticker marquee + KPI dashboard in Jinja2 template"
```

---

### Task 5: 參數化 VIX 圖表與 P/E 圖表資料（原第 1452–1671 行）

**Files:**
- Modify: `templates/report.html.j2`
- Modify: `scripts/report_render.py`
- Test: `tests/test_report_render.py`

繪圖邏輯（`new Chart(...)` 設定、顏色分段、`buildPEChart()`）完全不改，只把資料常數改成模板注入。

- [ ] **Step 1: VIX 圖表資料參數化**

原本：
```js
const vixRaw = [{"date":"2026-01-02","value":14.51}, ...];
```
改成：
```js
const vixRaw = {{ vix_history | tojson }};
```
其餘 VIX 圖表程式碼（第 1455–1545 行：`vixLabels`、`vixValues`、顏色判斷、`new Chart(vixCtx, {...})`、警戒線 `afterDraw` plugin）逐字保留不動。

- [ ] **Step 2: P/E 圖表資料參數化**

原本：
```js
const peData = {
  tw: [{ symbol:'2330.TW', name:'台積電', color:'#4f8ef7', trailing_3y:[...], ... }],
  us: [ ... ]
};
```
改成：
```js
const peData = {{ pe_data | tojson }};
```
其餘 `buildPEChart()`、`switchPEMarket()`、`switchPEPeriod()`（第 1571–1671 行）逐字保留。

- [ ] **Step 3: 在 `scripts/report_render.py` 補上這兩個 context key 的組裝函式**

```python
PE_COLORS = {"2330.TW": "#4f8ef7", "SPY": "#00d4ff", "NVDA": "#00e676", "LLY": "#ffa726"}


def build_vix_history(fear_data):
    """fear_data 來自 data_fetchers.fetch_all_fear_index()，取 us.history。"""
    return fear_data.get("us", {}).get("history", [])


def build_pe_data(pe_data):
    """把 data_fetchers.fetch_all_pe_data() 的輸出加上圖表顏色，其餘欄位原樣保留。"""
    result = {}
    for market, items in pe_data.items():
        result[market] = []
        for item in items:
            result[market].append({**item, "color": PE_COLORS.get(item["symbol"], "#c8d0ec")})
    return result
```

- [ ] **Step 4: 寫測試**

`tests/test_report_render.py`（append）:

```python
def test_build_vix_history_extracts_us_history():
    from scripts.report_render import build_vix_history

    fear_data = {"us": {"symbol": "^VIX", "name": "美股 VIX 恐懼指數",
                        "history": [{"date": "2026-07-01", "value": 16.5}]}}
    assert build_vix_history(fear_data) == [{"date": "2026-07-01", "value": 16.5}]


def test_build_pe_data_adds_chart_color():
    from scripts.report_render import build_pe_data

    pe_data = {"tw": [{"symbol": "2330.TW", "name": "台積電", "trailing_3y": [],
                       "trailing_1y": [], "current_trailing_pe": 33.4, "current_forward_pe": 19.6}]}
    result = build_pe_data(pe_data)
    assert result["tw"][0]["color"] == "#4f8ef7"
    assert result["tw"][0]["current_trailing_pe"] == 33.4
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_report_render.py -v`
Expected: 新增的兩個測試 PASS

- [ ] **Step 6: Commit**

```bash
git add templates/report.html.j2 scripts/report_render.py tests/test_report_render.py
git commit -m "feat: parameterize VIX and P/E chart data injection"
```

---

### Task 6: 參數化法人連三日排行表格與財報速覽表格

**Files:**
- Modify: `templates/report.html.j2`
- Modify: `scripts/report_render.py`
- Test: `tests/test_report_render.py`

- [ ] **Step 1: 法人排行表格參數化（原第 882–991 行結構，外資/投信兩個 tab，各自買超/賣超兩欄）**

找到外資 tab 面板（`id="inst-foreign"`）內買超表格的 `<tbody>`，改成迴圈（賣超欄位同樣手法，這裡示範買超欄）：

```html
<tbody>
  {% for row in institutional.foreign_buy_top10 %}
  <tr>
    <td>{{ loop.index }}</td>
    <td>{{ row.code }}</td>
    <td>{{ row.name }}</td>
    <td class="green">{{ "{:,}".format(row.est_amount_ntd) if row.est_amount_ntd else "—" }}</td>
    <td class="green">{{ row.lots_3d }}</td>
  </tr>
  {% endfor %}
</tbody>
```

投信 tab（`id="inst-trust"`）的買超/賣超表格改用 `institutional.trust_buy_top10` / `institutional.trust_sell_top10`；外資賣超表格改用 `institutional.foreign_sell_top10`。四張表格都是同一種迴圈結構，欄位對應 `fetch_institutional_3day_ranking()` 回傳的 dict 鍵：`code`、`name`、`lots_3d`、`est_amount_ntd`。

在表格區塊上方（顯示資料截止日期處）加入：
```html
<div class="header-sub">資料截止：{{ institutional.as_of_dates[-1] if institutional.as_of_dates else "—" }}（TWSE OpenAPI，估算金額）</div>
```

- [ ] **Step 2: 財報速覽表格參數化（原第 1035 行 `<table id="earningsTable">`）**

```html
<tbody>
  {% for e in earnings %}
  <tr data-market="{{ '台股' if e.market == '台股' else '美股' }}">
    <td>{{ e.date }}</td>
    <td>{{ e.symbol }}</td>
    <td>{{ e.name }}</td>
    <td>{{ e.market }}</td>
  </tr>
  {% endfor %}
</tbody>
```

（既有 Filter 按鈕的 JS 邏輯若是用 `data-market` 屬性篩選，維持原本 class/data 屬性名稱不變；若原本用其他篩選邏輯，實作時先讀原檔案 `earningsTable` 附近的 JS 篩選函式，比照其讀取的屬性名稱命名，不要另創一套。）

- [ ] **Step 3: 在 `scripts/report_render.py` 新增這兩個區塊的 context 組裝**

```python
def build_institutional_context(institutional_data):
    """institutional_data 為 None 時（假日等原因預抓失敗）回傳空排行，模板顯示 0 筆。"""
    if not institutional_data:
        return {"as_of_dates": [], "foreign_buy_top10": [], "foreign_sell_top10": [],
                "trust_buy_top10": [], "trust_sell_top10": []}
    return institutional_data


def build_earnings_context(earnings_list):
    return earnings_list  # 已是 list[dict]，欄位與模板需要的一致，不需轉換
```

- [ ] **Step 4: 寫測試**

`tests/test_report_render.py`（append）:

```python
def test_build_institutional_context_handles_none():
    from scripts.report_render import build_institutional_context

    result = build_institutional_context(None)
    assert result["foreign_buy_top10"] == []
    assert result["as_of_dates"] == []


def test_build_institutional_context_passes_through_data():
    from scripts.report_render import build_institutional_context

    data = {"as_of_dates": ["2026-07-01"], "foreign_buy_top10": [{"code": "2330", "name": "台積電",
             "lots_3d": 100.0, "est_amount_ntd": 24000000}],
             "foreign_sell_top10": [], "trust_buy_top10": [], "trust_sell_top10": []}
    assert build_institutional_context(data) == data
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_report_render.py -v`
Expected: 新增測試 PASS

- [ ] **Step 6: Commit**

```bash
git add templates/report.html.j2 scripts/report_render.py tests/test_report_render.py
git commit -m "feat: parameterize institutional ranking and earnings tables"
```

---

### Task 7: 定義 AI 敘述 JSON Schema，改寫 Claude prompt

**Files:**
- Modify: `scripts/generate_report.py`
- Test: `tests/test_generate_report.py`

這是把「AI 輸出完整 HTML」改成「AI 只輸出 JSON」的核心步驟。

- [ ] **Step 1: 在 `scripts/generate_report.py` 定義 JSON schema 常數（供 prompt 說明與後續解析驗證共用欄位名稱）**

```python
REQUIRED_JSON_FIELDS = [
    "daily_brief", "hero_events", "warning_indicators", "night_session",
    "news", "theme_cards", "strategy_cards", "risk_matrix_rows",
    "market_deep_dive_html", "lly_foundayo",
]
```

- [ ] **Step 2: 改寫 PROMPT，移除「輸出完整 HTML」的要求，改為要求輸出上述 JSON**

把原本第 499–581 行（`## HTML 設計規格` 到檔尾 `## 輸出格式`）整段替換成：

```python
JSON_OUTPUT_SPEC = """
## 輸出格式（重要：只輸出 JSON，不要輸出 HTML）
根據上方已提供的數字資料與你完成的搜尋任務，輸出一份 JSON（用 ```json ... ``` 包裹），結構如下：

{
  "daily_brief": "3 行、每行純文字不加符號，總長度 150 字以內：第一行大盤漲跌重點；第二行今日最重要新聞或事件；第三行對持倉組合最需要注意的一點。3 行用 \\n 分隔存成同一個字串。",
  "hero_events": [
    {"flag": "🇺🇸", "label": "今日重大事件 #1 — <一句話標題>", "theme": "green 或 amber 或 red",
     "headline": "<完整標題句>", "body": "<完整段落敘述，含資料來源標註>"},
    {"flag": "🇹🇼", "label": "今日重大事件 #2 — <一句話標題>", "theme": "green 或 amber 或 red",
     "headline": "<完整標題句>", "body": "<完整段落敘述，含資料來源標註>"}
  ],
  "warning_indicators": {
    "vix": {"status": "green/amber/red", "note": "<一句話判讀，VIX 數值已由系統提供，不需重複列出>"},
    "hy_spread": {"status": "green/amber/red", "value_text": "<搜尋到的 HY 利差數值文字>", "note": "<一句話判讀>"},
    "us10y": {"status": "green/amber/red", "note": "<一句話判讀，10Y 殖利率數值已由系統提供>"},
    "ai_leaders": {"status": "green/amber/red", "note": "<AI 龍頭股線型判讀，如 NVDA/AVGO 近期走勢>"},
    "tw_leverage": {"status": "green/amber/red", "value_text": "<搜尋到的台股融資餘額數值文字>", "note": "<一句話判讀>"}
  },
  "night_session": {"price": "<夜盤最新價>", "change_pts": "<漲跌點數>", "change_pct": "<漲跌%>",
                     "volume": "<成交量>", "vs_day_close_note": "<與日盤收盤比較的一句話>",
                     "source_note": "<資料來源與時間>"},
  "news": {
    "ai_semi": [{"title": "...", "summary": "...", "source": "...", "date": "YYYY-MM-DD"}],
    "macro": [ /* 同上結構 */ ],
    "geo": [ /* 同上結構 */ ],
    "ipo": [ /* 同上結構 */ ]
  },
  "theme_cards": [
    {"icon": "🤖", "title": "<主題名稱>", "body": "<兩三句話說明>", "tickers": ["NVDA", "AVGO"]}
    /* 共 5 張，涵蓋：AI 算力基礎建設、台灣半導體供應鏈、口服 GLP-1、AI 電力/資料中心、黃金/實物資產 */
  ],
  "strategy_cards": [
    {"name": "🔬 巴菲特框架 — 安全邊際", "quote": "<一句名言>", "points": ["<觀點1>", "<觀點2>", "<觀點3>"]}
    /* 共 3 張：巴菲特框架、動能策略、防禦配置 */
  ],
  "risk_matrix_rows": [
    {"risk": "<風險名稱>", "likelihood": "高/中/低", "impact": "高/中/低", "mitigation": "<因應方式>"}
  ],
  "market_deep_dive_html": "<完整執行下方三地市場深度分析規格後，直接輸出這個區塊的 HTML 片段（不含外層 <html>/<body>，只要這個區塊本身的 div 結構），沿用你過去產出這個區塊時的既有格式規則（信心等級標籤、洗盤vs出貨表格等）>",
  "lly_foundayo": {"weekly_trx": [{"week": "W1", "trx": 1390}], "wow_pct": [{"week": "W2", "pct": 12.3}],
                    "commentary": "<敘述>", "stage_note": "<若無 TRx 數據時的商業化階段說明>"}
}

所有欄位都必須存在，即使某個新聞分類搜尋不到內容也要回傳空陣列 `[]`，不可省略欄位本身。
不要輸出 JSON 以外的任何文字、不要用 Markdown 標題，直接輸出 ```json 區塊。
"""
```

把原本 prompt 組合處（`PROMPT = f"""..."""`）中 `## HTML 設計規格` 那一整段換成 `{JSON_OUTPUT_SPEC}`，其餘「已預先抓取」區塊與「必須完成的搜尋任務」區塊維持不動（這些是抓資料/搜尋指示，與輸出格式無關）。

- [ ] **Step 3: 改寫回應解析邏輯（原第 607–652 行的 `for iteration in range(5)` 迴圈）**

把 `html_content = None` 改成 `narrative_json = None`，把兩處 `re.search(r"```html\s*([\s\S]*?)```", ...)` 改成抓 JSON fence：

```python
def extract_json_block(text):
    m = re.search(r"```json\s*([\s\S]*?)```", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"  ⚠️ JSON 解析失敗: {e}")
        return None
```

在 `end_turn` 與 `max_tokens` 兩個分支裡，把原本抓 HTML 的邏輯換成：

```python
for block in response.content:
    if hasattr(block, "text"):
        parsed = extract_json_block(block.text)
        if parsed:
            narrative_json = parsed
```

`max_tokens` 分支不再需要「補結尾標籤」的邏輯（那是為了讓截斷的 HTML 能解析，JSON 截斷了本來就無法 `json.loads`，直接讓 `narrative_json` 維持 `None`，走到後面驗證階段時自然視為失敗）。

- [ ] **Step 4: 新增 JSON 完整性驗證，取代原本針對 HTML 字串的檢查**

```python
def validate_narrative_json(data):
    """回傳缺少的必要欄位清單；空清單代表通過。"""
    if data is None:
        return REQUIRED_JSON_FIELDS  # 全部視為缺失
    return [field for field in REQUIRED_JSON_FIELDS if field not in data]
```

呼叫端邏輯：

```python
if not narrative_json:
    raise RuntimeError(f"未能從 Claude 取得 JSON 內容（最終 stop_reason={response.stop_reason}）")

missing_fields = validate_narrative_json(narrative_json)
if missing_fields:
    raise RuntimeError(f"AI 回傳 JSON 缺少必要欄位，中止發布：{missing_fields}")
```

- [ ] **Step 5: 寫測試**

`tests/test_generate_report.py`:

```python
import json


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


def test_validate_narrative_json_lists_missing_fields():
    from scripts.generate_report import validate_narrative_json, REQUIRED_JSON_FIELDS

    assert validate_narrative_json(None) == REQUIRED_JSON_FIELDS
    assert validate_narrative_json({f: None for f in REQUIRED_JSON_FIELDS}) == []
    partial = {f: None for f in REQUIRED_JSON_FIELDS if f != "daily_brief"}
    assert validate_narrative_json(partial) == ["daily_brief"]
```

- [ ] **Step 6: Run test**

Run: `pytest tests/test_generate_report.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_report.py tests/test_generate_report.py
git commit -m "feat: switch Claude prompt/response from full HTML to structured JSON"
```

---

### Task 8: 參數化剩餘敘述性區塊（hero/警示/新聞/主題卡/策略卡/風險矩陣/深度分析/LLY），組完整 context

**Files:**
- Modify: `templates/report.html.j2`
- Modify: `scripts/report_render.py`
- Test: `tests/test_report_render.py`

- [ ] **Step 1: Hero 卡片參數化（原第 477–501 行）**

```html
<div class="hero-grid">
  {% for hero in hero_events %}
  <div class="hero-card theme-{{ hero.theme }}">
    <div class="hero-label">{{ hero.flag }} {{ hero.label }}</div>
    <div class="hero-headline">{{ hero.headline }}</div>
    <div class="hero-body">{{ hero.body }}</div>
  </div>
  {% endfor %}
</div>
```

（原本 hero 卡片內還有一排數字小卡如 Dow/S&P/Nasdaq/VIX，這些數字現在已經由 Task 4 的 `kpi_cards`/`ticker_data` 涵蓋，不在 hero 卡片內重複顯示，改由 `hero.body` 段落文字帶到——若日後發現版面上仍想要這排小卡，可在 `hero_events` 的 dict 裡加一個 `numbers` 欄位並在此迴圈內再巢狀一層，但這不是本次必要項目，先以簡化版本為準。）

- [ ] **Step 2: 五項預警指標參數化（原第 513 行起 `.warning-grid`）**

```html
<div class="warning-grid">
  <div class="warning-card status-{{ warning_indicators.vix.status }}">
    <div class="warning-title">VIX 恐慌指數</div>
    <div class="warning-value">{{ quotes.VIX.price if quotes.VIX else "N/A" }}</div>
    <div class="warning-note">{{ warning_indicators.vix.note }}</div>
  </div>
  <div class="warning-card status-{{ warning_indicators.hy_spread.status }}">
    <div class="warning-title">高收益債利差</div>
    <div class="warning-value">{{ warning_indicators.hy_spread.value_text }}</div>
    <div class="warning-note">{{ warning_indicators.hy_spread.note }}</div>
  </div>
  <div class="warning-card status-{{ warning_indicators.us10y.status }}">
    <div class="warning-title">10Y 美債殖利率</div>
    <div class="warning-value">{{ quotes.US10Y.price if quotes.US10Y else "N/A" }}%</div>
    <div class="warning-note">{{ warning_indicators.us10y.note }}</div>
  </div>
  <div class="warning-card status-{{ warning_indicators.ai_leaders.status }}">
    <div class="warning-title">AI 龍頭線型</div>
    <div class="warning-note">{{ warning_indicators.ai_leaders.note }}</div>
  </div>
  <div class="warning-card status-{{ warning_indicators.tw_leverage.status }}">
    <div class="warning-title">台股融資餘額</div>
    <div class="warning-value">{{ warning_indicators.tw_leverage.value_text }}</div>
    <div class="warning-note">{{ warning_indicators.tw_leverage.note }}</div>
  </div>
</div>
```

（`status-{{ ... }}` 對應的 CSS class 若原本沒有，實作時檢查原檔案 `.warning-grid` 附近有沒有既有的顏色 class 命名慣例——如果有現成的（例如 `.warning-green`/`.warning-red`），直接沿用那個命名而不是新創 `status-*`，維持與現有 CSS 一致；若原本是 AI 每天手刻不同 class 名稱、沒有固定命名，才新增這組 `.status-green`/`.status-amber`/`.status-red` CSS 規則到 `<style>` 區塊。）

- [ ] **Step 3: 台指期夜盤區塊參數化**

```html
<div class="header-sub">
  最新價 {{ night_session.price }}　
  漲跌 {{ night_session.change_pts }} ({{ night_session.change_pct }})　
  成交量 {{ night_session.volume }}
</div>
<div class="hero-body">{{ night_session.vs_day_close_note }}</div>
<div class="header-sub">{{ night_session.source_note }}</div>
```

- [ ] **Step 4: 新聞中心四個 tab 面板參數化（原第 1073–1180 行）**

四個面板（`news-ai`、`news-macro`、`news-geo`、`news-ipo`）結構相同，各自迴圈：

```html
<div id="news-ai" class="news-panel active">
  {% for item in news.ai_semi %}
  <div class="news-item">
    <div class="news-title">{{ item.title }}</div>
    <div class="news-summary">{{ item.summary }}</div>
    <div class="news-meta">{{ item.source }} · {{ item.date }}</div>
  </div>
  {% endfor %}
</div>
<div id="news-macro" class="news-panel">
  {% for item in news.macro %}
  <div class="news-item">
    <div class="news-title">{{ item.title }}</div>
    <div class="news-summary">{{ item.summary }}</div>
    <div class="news-meta">{{ item.source }} · {{ item.date }}</div>
  </div>
  {% endfor %}
</div>
<div id="news-geo" class="news-panel">
  {% for item in news.geo %}
  <div class="news-item">
    <div class="news-title">{{ item.title }}</div>
    <div class="news-summary">{{ item.summary }}</div>
    <div class="news-meta">{{ item.source }} · {{ item.date }}</div>
  </div>
  {% endfor %}
</div>
<div id="news-ipo" class="news-panel">
  {% for item in news.ipo %}
  <div class="news-item">
    <div class="news-title">{{ item.title }}</div>
    <div class="news-summary">{{ item.summary }}</div>
    <div class="news-meta">{{ item.source }} · {{ item.date }}</div>
  </div>
  {% endfor %}
</div>
```

（`news-item`/`news-title`/`news-summary`/`news-meta` 這幾個 class 名稱是本次新建立的，因為原本新聞區塊是 AI 每天手刻不同排版；實作前先讀原檔案第 1073–1180 行實際用了什麼 class，若已有一致的命名就沿用，若沒有就用上面這組，並在 `<style>` 補上對應的簡單樣式（沿用 `.hero-body`/`.header-sub` 現有的文字顏色規則，不要用比 `--text-secondary` 更暗的顏色，這是專案既有的色階規則）。

- [ ] **Step 5: 主題卡片參數化（原第 1297–1340 行，5 張）**

```html
<div class="theme-grid">
  {% for card in theme_cards %}
  <div class="theme-card">
    <div class="theme-card-icon">{{ card.icon }}</div>
    <div class="theme-card-title">{{ card.title }}</div>
    <div class="theme-card-body">{{ card.body }}</div>
    <div class="theme-card-tickers">
      {% for ticker in card.tickers %}<span class="badge">{{ ticker }}</span>{% endfor %}
    </div>
  </div>
  {% endfor %}
</div>
```

（外層容器 class 名稱 `theme-grid` 需對照原檔案第 1297 行前面實際的容器 class；若原本沒有專屬容器 class 只是連續 5 個 `.theme-card` 平鋪在某個既有 `.container`/`.section` 下，直接把迴圈放在原本的位置，不用另外包一層。）

- [ ] **Step 6: 策略卡片參數化（原第 1355–1381 行，3 張）**

```html
<div class="strategy-grid">
  {% for card in strategy_cards %}
  <div class="strategy-card">
    <div class="strategy-name">{{ card.name }}</div>
    <div class="strategy-quote">{{ card.quote }}</div>
    <ul class="strategy-points">
      {% for point in card.points %}<li>{{ point }}</li>{% endfor %}
    </ul>
  </div>
  {% endfor %}
</div>
```

- [ ] **Step 7: 風險矩陣參數化**

找到風險矩陣表格（`## HTML 設計規格` 原描述「風險矩陣表格」，在策略總結之前；實作時搜尋原檔案中風險矩陣對應的 `<table>`），`<tbody>` 改成：

```html
<tbody>
  {% for row in risk_matrix_rows %}
  <tr>
    <td>{{ row.risk }}</td>
    <td>{{ row.likelihood }}</td>
    <td>{{ row.impact }}</td>
    <td>{{ row.mitigation }}</td>
  </tr>
  {% endfor %}
</tbody>
```

- [ ] **Step 8: 三地市場深度分析區塊與 LLY Foundayo 區塊參數化**

三地市場深度分析（現有做法是整段交給 AI 自由發揮成一個 HTML 區塊，本次不強行拆成結構化欄位——維持這個彈性，直接把 AI JSON 的 `market_deep_dive_html` 字串原樣插入）：

```html
<div class="section" id="market-deep-dive">
  {{ market_deep_dive_html | safe }}
</div>
```

（這是模板中唯一使用 `| safe` 直接插入 AI 產生的 HTML 片段而非個別欄位的地方，原因：這個區塊的內部結構本來就複雜多變（信心等級標籤、七維度表格），比照現行做法「相信 AI 輸出」，不強行拆解成更細的 Jinja2 變數，作用範圍與風險等同於改動前的現狀，沒有新增風險。）

LLY Foundayo 圖表資料參數化（原第 1673 行起）：

```js
const llyWeeklyTrx = {{ lly_foundayo.weekly_trx | tojson }};
const llyWowPct = {{ lly_foundayo.wow_pct | tojson }};
```

（原本繪圖 JS 若是直接手刻資料陣列後接繪圖邏輯，找到資料陣列宣告那幾行替換掉，後面 `new Chart(...)` 的邏輯不動。）文字說明部分：

```html
<div class="hero-body">{{ lly_foundayo.commentary }}</div>
{% if not lly_foundayo.weekly_trx %}
<div class="hero-body">{{ lly_foundayo.stage_note }}</div>
{% endif %}
```

- [ ] **Step 9: 在 `scripts/report_render.py` 新增 `build_template_context()`，整合本任務與前面所有 Task 的組裝函式成一個總入口**

```python
def build_template_context(*, date_label, weekday_cn, tw_holiday_note,
                            quotes, fear_data, pe_data, institutional_data,
                            earnings_list, narrative_json):
    """把所有預抓資料 + AI 敘述 JSON 組成 render_report() 需要的完整 context dict。"""
    return {
        "date_label": date_label,
        "weekday_cn": weekday_cn,
        "tw_holiday_note": tw_holiday_note,
        "quotes": quotes,
        "ticker_data": build_ticker_data(quotes),
        "kpi_cards": build_kpi_cards(quotes),
        "vix_history": build_vix_history(fear_data),
        "pe_data": build_pe_data(pe_data),
        "institutional": build_institutional_context(institutional_data),
        "earnings": build_earnings_context(earnings_list),
        "hero_events": narrative_json["hero_events"],
        "warning_indicators": narrative_json["warning_indicators"],
        "night_session": narrative_json["night_session"],
        "news": narrative_json["news"],
        "theme_cards": narrative_json["theme_cards"],
        "strategy_cards": narrative_json["strategy_cards"],
        "risk_matrix_rows": narrative_json["risk_matrix_rows"],
        "market_deep_dive_html": narrative_json["market_deep_dive_html"],
        "lly_foundayo": narrative_json["lly_foundayo"],
    }
```

- [ ] **Step 10: 寫整合測試，驗證完整 context 渲染出通過既有驗證規則的 HTML**

`tests/test_report_render.py`（append，這是本檔案最重要的一個測試，取代 Task 4 Step 7 那個暫時性的部分測試）：

```python
def _fake_narrative_json():
    return {
        "daily_brief": "line1\nline2\nline3",
        "hero_events": [
            {"flag": "🇺🇸", "label": "事件1", "theme": "green", "headline": "H1", "body": "B1"},
            {"flag": "🇹🇼", "label": "事件2", "theme": "amber", "headline": "H2", "body": "B2"},
        ],
        "warning_indicators": {
            "vix": {"status": "amber", "note": "note1"},
            "hy_spread": {"status": "green", "value_text": "3.2%", "note": "note2"},
            "us10y": {"status": "amber", "note": "note3"},
            "ai_leaders": {"status": "green", "note": "note4"},
            "tw_leverage": {"status": "red", "value_text": "2800億", "note": "note5"},
        },
        "night_session": {"price": "46,880", "change_pts": "+136", "change_pct": "+0.29%",
                          "volume": "12000", "vs_day_close_note": "note", "source_note": "src"},
        "news": {"ai_semi": [{"title": "t", "summary": "s", "source": "src", "date": "2026-07-03"}],
                 "macro": [], "geo": [], "ipo": []},
        "theme_cards": [{"icon": "🤖", "title": "t", "body": "b", "tickers": ["NVDA"]}] * 5,
        "strategy_cards": [{"name": "n", "quote": "q", "points": ["p1", "p2"]}] * 3,
        "risk_matrix_rows": [{"risk": "r", "likelihood": "高", "impact": "高", "mitigation": "m"}],
        "market_deep_dive_html": "<div>深度分析內容</div>",
        "lly_foundayo": {"weekly_trx": [{"week": "W1", "trx": 1390}],
                         "wow_pct": [{"week": "W2", "pct": 12.3}],
                         "commentary": "c", "stage_note": ""},
    }


def test_build_template_context_and_render_produces_valid_html():
    from scripts.report_render import build_template_context, render_report

    quotes = {"TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": 274.0, "change_pct": 0.59}}
    context = build_template_context(
        date_label="2026.07.03", weekday_cn="週五", tw_holiday_note="",
        quotes=quotes,
        fear_data={"us": {"symbol": "^VIX", "name": "VIX", "history": [{"date": "2026-07-01", "value": 16.5}]}},
        pe_data={"tw": [], "us": []},
        institutional_data=None,
        earnings_list=[{"date": "2026-07-10", "symbol": "NVDA", "name": "NVIDIA", "market": "美股"}],
        narrative_json=_fake_narrative_json(),
    )
    html = render_report(context)

    from scripts.generate_report import validate_html
    assert validate_html(html) == []
```

- [ ] **Step 11: Run test**

Run: `pytest tests/test_report_render.py -v`
Expected: 全部 PASS，尤其 `test_build_template_context_and_render_produces_valid_html` 要通過（代表模板已經完整可渲染，且輸出符合現行 `validate_html` 規則）

- [ ] **Step 12: 手動視覺檢查**

```bash
python -c "
from scripts.report_render import build_template_context, render_report
from tests.test_report_render import _fake_narrative_json
ctx = build_template_context(date_label='2026.07.03', weekday_cn='週五', tw_holiday_note='',
    quotes={}, fear_data={}, pe_data={'tw': [], 'us': []}, institutional_data=None,
    earnings_list=[], narrative_json=_fake_narrative_json())
open('/tmp/preview.html', 'w', encoding='utf-8').write(render_report(ctx))
"
```

用瀏覽器打開產生的 `/tmp/preview.html`，確認版面沒有明顯破版（CSS 沒跑掉、圖表區域至少有 canvas 佔位、卡片排版正常）。這一步是視覺 sanity check，不是自動化測試，過了才進下一步。

- [ ] **Step 13: Commit**

```bash
git add templates/report.html.j2 scripts/report_render.py tests/test_report_render.py
git commit -m "feat: parameterize remaining narrative sections and wire full template context"
```

---

### Task 9: 重寫 `generate_report.py` 主流程，接上 render + 驗證 + 通知摘要

**Files:**
- Modify: `scripts/generate_report.py`
- Test: `tests/test_generate_report.py`

- [ ] **Step 1: 改寫主流程（原第 373–698 行）**

保留原本的日期判斷、假日判斷、`Backup/{date}.html` 存在性檢查（第 373–406 行邏輯不變，只是呼叫的函式現在來自 `scripts.data_fetchers`）。資料預抓區塊（原 408–427 行）新增 `fetch_quotes()` 呼叫：

```python
print("  正在用 yfinance 抓取即時報價（ticker/KPI 用）...")
from scripts.data_fetchers import fetch_quotes
quotes = fetch_quotes()
```

呼叫 Claude、解析 JSON（沿用 Task 7 的 `extract_json_block`/`validate_narrative_json`）之後，新增渲染步驟：

```python
from scripts.report_render import build_template_context, render_report

context = build_template_context(
    date_label=date_label, weekday_cn=weekday_cn, tw_holiday_note=tw_holiday_note,
    quotes=quotes, fear_data=fear_data, pe_data=pe_data,
    institutional_data=institutional_data, earnings_list=earnings_data,
    narrative_json=narrative_json,
)
html_content = render_report(context)
```

- [ ] **Step 2: `validate_html()` 維持不動（第 655–665 行邏輯完全保留），但驗證對象現在是 `render_report()` 的輸出**

不需要修改 `validate_html` 函式本身，只需確認呼叫順序是「render 完再 validate」。

- [ ] **Step 3: 通知摘要輸出改用 JSON 的 `daily_brief` 欄位，取代原本的 regex**

刪除原第 685–686 行：
```python
summary_match = re.search(r"<!--SUMMARY\s*([\s\S]*?)SUMMARY-->", html_content)
summary_text = summary_match.group(1).strip() if summary_match else ""
```
改成：
```python
summary_text = narrative_json.get("daily_brief", "").strip()
```
其餘（第 687–697 行：印出摘要、寫入 `GITHUB_OUTPUT`）完全不變。

- [ ] **Step 4: 寫測試驗證 `daily_brief` 正確流向 `GITHUB_OUTPUT`**

`tests/test_generate_report.py`（append）:

```python
def test_summary_text_uses_daily_brief_field():
    narrative_json = {"daily_brief": "第一行\n第二行\n第三行"}
    summary_text = narrative_json.get("daily_brief", "").strip()
    assert summary_text == "第一行\n第二行\n第三行"


def test_summary_text_empty_when_daily_brief_missing():
    narrative_json = {}
    summary_text = narrative_json.get("daily_brief", "").strip()
    assert summary_text == ""
```

（這兩個測試很薄，因為邏輯本身就是一行 `.get()`；真正的把關在 Task 7 的 `validate_narrative_json` 已經確保 `daily_brief` 一定存在，這裡只是回歸測試避免未來重構時改壞。）

- [ ] **Step 5: Run test**

Run: `pytest tests/ -v`
Expected: 全部測試 PASS（含前面所有 Task 累積的測試）

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_report.py tests/test_generate_report.py
git commit -m "feat: wire render pipeline into main flow, read daily_brief from JSON"
```

---

### Task 10: 端到端人工驗證（真實跑一次，含真實 Claude API 呼叫）

**Files:** 無新檔案，僅執行驗證

- [ ] **Step 1: 本機設定環境變數並試跑歷史日期**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
DATE_OVERRIDE=2026-06-16 python scripts/generate_report.py
```

Expected: 印出各階段抓取進度、`✅ 報告驗證通過`、`✅ 報告已寫入 index.html`，無 `RuntimeError`

- [ ] **Step 2: 瀏覽器打開產生的 `index.html`，檢查：**
  - 版面與 CSS 跟 `Backup/2026-07-03.html` 視覺上一致（同一套深色主題、卡片排版）
  - Ticker 跑馬燈跑得動、KPI 儀表板數字非空
  - VIX / P/E 圖表能正常畫出來（不是空白 canvas）
  - 法人排行、財報速覽表格有資料或至少顯示「0 筆」而非壞掉
  - 新聞四個 tab、主題卡片、策略卡片文字通順、無 JSON 殘留符號（例如沒有把 `\n` 字面印出來）

- [ ] **Step 3: 再跑一次台股休市的歷史日期，確認 holiday badge 與提示文字正常**

```bash
DATE_OVERRIDE=2026-02-28 python scripts/generate_report.py
```

（2026-02-28 為示意日期，實作時選一個實際落在台股國定假日後的日期；可用 `python -c "from scripts.data_fetchers import is_prev_tw_day_holiday; from datetime import datetime,timezone,timedelta; print(is_prev_tw_day_holiday(datetime(2026,2,28,tzinfo=timezone(timedelta(hours=8)))))"` 先確認該日期确实会觸發 `tw_holiday_note`）

Expected: 報告正常產出，且台股相關數字標註為「最近一個交易日」資料

- [ ] **Step 4: 確認 `pytest tests/ -v` 全數通過，且沒有殘留 `Backup/2026-06-16.html`、`Backup/2026-02-28.html` 這類測試用產物被誤 commit**

```bash
pytest tests/ -v
git status
```

Expected: 測試全過；`git status` 顯示乾淨或只有預期中的檔案異動（測試跑出來的 `Backup/*.html` 屬於本地驗證產物，不要 commit，用 `git clean` 前先確認不是需要保留的東西，或直接手動刪除這兩個測試用的 Backup 檔案）

- [ ] **Step 5: 清理測試產物，不 commit**

```bash
rm -f Backup/2026-06-16.html Backup/2026-02-28.html
git checkout -- index.html   # 還原成合併前的 index.html，避免測試跑的內容被誤認為要發布的版本
```

（此步驟只清本機工作區，不涉及任何 git 歷史或已 push 的內容。）

---

## Plan 完成後的狀態

- `scripts/generate_report.py` 大幅縮短，只剩協調邏輯
- 每日報告的版面由 `templates/report.html.j2` 固定控制，AI 只回傳 JSON
- 通知摘要機制沿用現有 workflow，不需改 `.github/workflows/daily-update.yml` 或 `scripts/send_email.py`
- 下一份 plan（新資料區塊：韓國股市/美股熱力圖/美股資金板塊/油價走勢）會在 `templates/report.html.j2` 追加新區塊、在 `scripts/data_fetchers.py` 追加新抓取函式、在 `scripts/report_render.py` 追加對應 context 組裝，架構與本 plan 建立的模式一致
