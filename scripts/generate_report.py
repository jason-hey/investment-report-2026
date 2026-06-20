"""
Daily Investment Report Generator
每天自動呼叫 Claude API + web_search（伺服器端工具），生成 HTML 報告並備份舊報告
使用串流模式（SDK 要求：max_tokens 較大時必須用 streaming，避免長時間請求被中斷）
"""
import anthropic
import os
import re
import shutil
from datetime import datetime, timezone, timedelta

# ── 美股假日判斷：前一交易日為假日則跳過報告 ────────────────────────────────

def is_prev_us_day_holiday(base_date):
    """
    若前一個美股交易日（跳過週末）是假日，回傳 True。
    失敗時保守回傳 False（繼續執行）。
    """
    try:
        import exchange_calendars as xcals
        nyse = xcals.get_calendar("XNYS")
        prev = base_date - timedelta(days=1)
        while prev.weekday() >= 5:          # 跳過週六(5)、週日(6)
            prev -= timedelta(days=1)
        return not nyse.is_session(prev.strftime("%Y-%m-%d"))
    except Exception as e:
        print(f"  ⚠️ 假日判斷失敗（{e}），繼續執行")
        return False


# ── 財報日曆：用 yfinance 抓取結構化資料，避免 AI web_search 誤判 ──────────

EARNINGS_WATCH = [
    # 個人持倉
    "NVDA", "AVGO", "ORCL", "LLY",
    # 大型科技
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA", "AMD",
    # 半導體
    "MU", "QCOM", "INTC", "TSM", "MRVL", "AMAT", "LRCX", "KLAC",
    # 其他重要
    "FDX", "NKE", "ACN", "JPM", "GS", "MS", "WMT", "COST",
]


def fetch_earnings_calendar(base_date, days_ahead=14):
    """用 yfinance 抓未來 days_ahead 天內的財報日期，回傳排序好的 list。"""
    try:
        import yfinance as yf
    except ImportError:
        print("  ⚠️ yfinance 未安裝，跳過財報 API 抓取")
        return []

    end_date = base_date + timedelta(days=days_ahead)
    results = []

    for symbol in EARNINGS_WATCH:
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if not cal:
                continue

            dates = cal.get("Earnings Date", [])
            if not isinstance(dates, list):
                dates = [dates]

            for ed in dates:
                # 統一轉成 date 物件
                if hasattr(ed, "date"):
                    ed = ed.date()
                elif isinstance(ed, str):
                    ed = datetime.strptime(ed[:10], "%Y-%m-%d").date()
                else:
                    continue

                if base_date.date() <= ed <= end_date.date():
                    info = ticker.info or {}
                    results.append({
                        "date":   ed.strftime("%Y-%m-%d"),
                        "symbol": symbol,
                        "name":   info.get("longName", symbol),
                        "market": "美股",
                    })
                    break  # 只取最近一筆
        except Exception as e:
            print(f"  ⚠️ {symbol} 財報查詢失敗: {e}")

    results.sort(key=lambda x: x["date"])
    return results


def format_earnings_for_prompt(earnings):
    """將財報清單轉成 prompt 用的文字表格。"""
    if not earnings:
        return "（查無資料，請自行搜尋）"
    lines = ["日期        | 代號  | 公司名稱                     | 市場"]
    lines.append("-" * 60)
    for e in earnings:
        lines.append(f"{e['date']} | {e['symbol']:<5} | {e['name']:<28} | {e['market']}")
    return "\n".join(lines)


# ── 本益比趨勢：用 yfinance 抓取歷史 P/E，注入 Chart.js 圖表 ─────────────────

PE_TICKERS = {
    "tw": [("2330.TW", "台積電")],
    "us": [("SPY", "S&P 500"), ("NVDA", "NVIDIA"), ("LLY", "Eli Lilly")],
}


def fetch_pe_history(symbol, display_name):
    """
    用 current trailingPE + 歷史收盤價計算每月 P/E 趨勢。
    回傳 3Y 月資料 list，格式 [{"date":"2023-06","pe":18.5}, ...]
    """
    try:
        import yfinance as yf
    except ImportError:
        return []

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        trailing_pe = info.get("trailingPE")
        current_price = info.get("regularMarketPrice") or info.get("currentPrice")

        if not trailing_pe or not current_price or trailing_pe <= 0 or current_price <= 0:
            print(f"  ⚠️ {display_name} 無 P/E 資料，跳過")
            return []

        implied_eps = current_price / trailing_pe

        hist = ticker.history(period="3y", interval="1mo")
        if hist.empty:
            return []

        results = []
        for dt, row in hist.iterrows():
            pe = row["Close"] / implied_eps
            if 0 < pe < 1000:
                results.append({"date": dt.strftime("%Y-%m"), "pe": round(pe, 1)})

        return results
    except Exception as e:
        print(f"  ⚠️ {display_name} P/E 抓取失敗: {e}")
        return []


def fetch_all_pe_data():
    """抓取所有追蹤標的的 P/E 歷史，回傳 JSON 可序列化的 dict。"""
    import json
    result = {}
    for market, tickers in PE_TICKERS.items():
        result[market] = []
        for symbol, name in tickers:
            data_3y = fetch_pe_history(symbol, name)
            data_1y = data_3y[-12:] if len(data_3y) >= 12 else data_3y
            if data_3y:
                result[market].append({
                    "symbol": symbol,
                    "name": name,
                    "data_3y": data_3y,
                    "data_1y": data_1y,
                })
                print(f"  P/E {name}: {len(data_3y)} 個月資料")
    return result

TZ_TW = timezone(timedelta(hours=8))
today = datetime.now(TZ_TW)

if os.environ.get("DATE_OVERRIDE"):
    today = datetime.strptime(os.environ["DATE_OVERRIDE"], "%Y-%m-%d").replace(tzinfo=TZ_TW)

date_str   = today.strftime("%Y-%m-%d")
date_label = today.strftime("%Y.%m.%d")
weekday_cn = ["週一","週二","週三","週四","週五","週六","週日"][today.weekday()]

print(f"[{date_str}] 檢查美股假日...")
if is_prev_us_day_holiday(today):
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    print(f"  前一美股交易日 {prev.strftime('%Y-%m-%d')} 為假日，跳過本次報告生成。")
    exit(0)

print("  正在用 yfinance 抓取未來 2 週財報日曆...")
earnings_data = fetch_earnings_calendar(today)
earnings_table = format_earnings_for_prompt(earnings_data)
print(f"  財報日曆：找到 {len(earnings_data)} 筆")

print("  正在用 yfinance 抓取本益比趨勢（1Y / 3Y）...")
import json as _json
pe_data = fetch_all_pe_data()
pe_json = _json.dumps(pe_data, ensure_ascii=False)

PROMPT = f"""
今天是 {date_label}（{weekday_cn}），台灣台中。
請為我生成一份完整的「每日投資情報 HTML 網頁」。

## 【已預先抓取】未來 2 週財報日曆（直接使用，勿再搜尋）
以下資料來自 Yahoo Finance API，請直接用於財報速覽區塊，不需要再搜尋財報日期：

{earnings_table}

## 【已預先抓取】本益比趨勢資料（直接用於圖表，勿再搜尋）
以下 JSON 包含台股與美股各標的的月度 P/E 歷史（1Y / 3Y），請直接用於本益比趨勢圖區塊：

{pe_json}

欄位說明：data_3y = 近 3 年月資料；data_1y = 近 1 年月資料。pe 值為基於當前 trailing EPS 的歷史估算。

## 必須完成的搜尋任務（依序執行，至少 8 次搜尋）
1. 今日/昨日美股收盤：S&P 500、Nasdaq、Dow 漲跌幅與主要個股
2. 台股今日行情：加權指數、台積電（2330）、鴻海（2317）、聯發科（2454）
3. 台股三大法人動向：外資/投信/自營商買賣超
4. 今日最重要的 AI/半導體新聞（NVDA/TSMC/AVGO/MRVL）
5. 地緣政治：伊朗局勢最新進展、油價動態
6. 總體經濟：Fed 動態、美債殖利率、PCE/CPI 最新數據、CME FedWatch 降息機率
7. SpaceX SPCX 等重大 IPO 進度
8. 台指期夜盤最新走勢：當日夜盤開盤價、最新價、漲跌點數、成交量、與日盤收盤的差距

## HTML 設計規格
- 深色主題（背景 #04040d，IBM Plex Mono + Inter 字體）
- 文字色階規則（嚴格遵守）：
  - 主要文字、標題、指標名稱、數值：`color: #f0f2fc`（近白）
  - 次要說明文字、日期、副標題、跑馬燈股票代號、單位、來源：`color: #c8d0ec`（明亮灰白，不可更暗）
  - 禁止在任何可讀文字上使用 `#8890c0` 或更暗的顏色；低亮度色（如 `#8890c0`）僅可用於純裝飾性佔位元素
- 頂部跑馬燈（即時數據）
- 標題區（badges + 日期 + 4 條關鍵 pill）
- 英雄橫幅（2 欄，最重要的 2 個事件）
- 每日必看 5 大預警指標模組（VIX/HY利差/10Y殖利率/AI龍頭線型/台股槓桿）
- 數據驗證區（✓ 已確認 / ⚠ 預估）
- KPI 指標看板（4 格）
- 視覺圖表區（Chart.js 4.4.1 + datalabels 2.2.0）
- 台指期夜盤動態區塊：
  - 顯示夜盤最新報價、漲跌點數與百分比、成交量
  - 與日盤收盤差距（用顏色標示漲跌：漲綠跌紅）
  - 夜盤交易時段說明（15:00–05:00 台灣時間）
  - 資料來源標示（搜尋到的資料時間）
- 本益比趨勢圖區塊（使用上方已提供的 pe_data JSON）：
  - 兩個 Tab：「台股」和「美股」
  - 每個 Tab 內有「1Y」和「3Y」切換按鈕
  - Chart.js 折線圖，深色主題，格線淡化
  - 台股 Tab：顯示 pe_data.tw 各標的（多條線，每條一個顏色）
  - 美股 Tab：顯示 pe_data.us 各標的（多條線，每條一個顏色）
  - 若某標的資料為空，則不渲染該線
  - 圖表標題標明「本益比（P/E）歷史趨勢 — 基於當前 EPS 估算」
- 未來 2 週財報速覽（Filter 按鈕：全部/美股/台股/★持倉）
- 財經新聞中心（Tab：4 個主題）
- 風險矩陣表格
- 投資主題機會（5 張卡片）
- 大師策略總結（3 欄）
- Footer（資料來源）

## 個人持倉背景
台積電(2330)、鴻海(2317)、聯發科(2454)、SMH、NVDA、AVGO、ORCL、LLY、0050、IAUM(黃金)

## 輸出格式
輸出完整的 HTML，用 ```html ... ``` 包裹，包含所有 CSS 和 JavaScript。
不要解釋，直接輸出 HTML。
"""

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

print(f"[{date_str}] 開始生成報告...")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 64000
TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}]

messages = [{"role": "user", "content": PROMPT}]


def call_claude(messages):
    """用串流模式呼叫 API，回傳最終完整訊息物件"""
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=TOOLS,
        messages=messages
    ) as stream:
        for _ in stream.text_stream:
            pass
        return stream.get_final_message()


response = call_claude(messages)
html_content = None

for iteration in range(5):
    print(f"  迭代 {iteration+1}: stop_reason={response.stop_reason}")

    if response.stop_reason == "end_turn":
        for block in response.content:
            if hasattr(block, "text"):
                m = re.search(r"```html\s*([\s\S]*?)```", block.text)
                if m:
                    html_content = m.group(1).strip()
                elif "<html" in block.text.lower():
                    html_content = block.text.strip()
        break

    elif response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        response = call_claude(messages)
        continue

    elif response.stop_reason == "max_tokens":
        print(f"  ⚠️ 達到 max_tokens 上限，嘗試從已產生內容中萃取 HTML...")
        for block in response.content:
            if hasattr(block, "text"):
                print(f"  已產生文字長度: {len(block.text)}")
                m = re.search(r"```html\s*([\s\S]*?)```", block.text)
                if m:
                    html_content = m.group(1).strip()
                elif "<html" in block.text.lower():
                    # 輸出被截斷，補上缺少的結尾標籤讓瀏覽器能正常渲染
                    partial = block.text.strip()
                    if not partial.endswith("</html>"):
                        partial += "\n</body></html>"
                    html_content = partial
        break

    else:
        print(f"  ⚠️ 非預期 stop_reason: {response.stop_reason}")
        for block in response.content:
            if hasattr(block, "text"):
                print(f"  已產生文字長度: {len(block.text)}")
        break

if not html_content:
    raise RuntimeError(f"未能從 Claude 取得 HTML 內容（最終 stop_reason={response.stop_reason}）")

archive_dir = "archive"
os.makedirs(archive_dir, exist_ok=True)
if os.path.exists("index.html"):
    shutil.copy("index.html", f"{archive_dir}/{date_str}.html")
    print(f"  已備份至 archive/{date_str}.html")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

backup_dir = "Backup"
os.makedirs(backup_dir, exist_ok=True)
shutil.copy("index.html", f"{backup_dir}/{date_str}.html")

print(f"  ✅ 報告已寫入 index.html（{len(html_content):,} bytes）")
print(f"  ✅ 已備份至 Backup/{date_str}.html")
