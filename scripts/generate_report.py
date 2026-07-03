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

def _is_prev_day_holiday(base_date, calendar_code):
    """
    若前一個交易日（跳過週末）在指定市場行事曆上不是開盤日，回傳 True。
    失敗時保守回傳 False（繼續執行）。
    """
    try:
        import exchange_calendars as xcals
        cal = xcals.get_calendar(calendar_code)
        prev = base_date - timedelta(days=1)
        while prev.weekday() >= 5:          # 跳過週六(5)、週日(6)
            prev -= timedelta(days=1)
        return not cal.is_session(prev.strftime("%Y-%m-%d"))
    except Exception as e:
        print(f"  ⚠️ {calendar_code} 假日判斷失敗（{e}），繼續執行")
        return False


def is_prev_us_day_holiday(base_date):
    return _is_prev_day_holiday(base_date, "XNYS")


def is_prev_tw_day_holiday(base_date):
    return _is_prev_day_holiday(base_date, "XTAI")


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
    用季度財報的 Diluted/Basic EPS 計算各期「真實」TTM（近四季）EPS，
    再除以對應期間的歷史股價，得到真實 Trailing P/E 趨勢。
    （舊做法是用「目前 trailingPE 反推固定 EPS」去除歷史股價，等於假設 EPS 三年不變，
    對 EPS 成長快的公司如 NVDA 會嚴重失真——這裡改用逐季真實 TTM EPS。）
    同時抓取 forwardPE 當前值。
    回傳 dict: {
        "trailing_3y": [{"date":"2023-06","pe":18.5}, ...],
        "forward_pe": 25.3 or None
    }
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"trailing_3y": [], "forward_pe": None}

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        forward_pe = info.get("forwardPE")
        forward_pe = round(forward_pe, 1) if forward_pe and forward_pe > 0 else None

        q_income = ticker.quarterly_income_stmt
        eps_row_name = next(
            (name for name in ("Diluted EPS", "Basic EPS")
             if q_income is not None and not q_income.empty and name in q_income.index),
            None
        )
        if eps_row_name is None:
            print(f"  ⚠️ {display_name} 無季度 EPS 資料，跳過歷史趨勢")
            return {"trailing_3y": [], "forward_pe": forward_pe}

        eps_by_quarter = q_income.loc[eps_row_name].dropna().sort_index()
        if len(eps_by_quarter) < 4:
            print(f"  ⚠️ {display_name} 季度 EPS 資料不足 4 季，無法計算 TTM，跳過歷史趨勢")
            return {"trailing_3y": [], "forward_pe": forward_pe}

        # 每一季的 TTM EPS = 該季 + 前 3 季合計；依公布日期由舊到新排序
        ttm_points = []
        for i in range(3, len(eps_by_quarter)):
            ttm_eps = float(eps_by_quarter.iloc[i - 3:i + 1].sum())
            if ttm_eps > 0:
                ttm_points.append((eps_by_quarter.index[i].date(), ttm_eps))

        if not ttm_points:
            print(f"  ⚠️ {display_name} TTM EPS 皆為負值，跳過歷史趨勢")
            return {"trailing_3y": [], "forward_pe": forward_pe}

        hist = ticker.history(period="3y", interval="1mo")
        trailing_3y = []
        if not hist.empty:
            for dt, row in hist.iterrows():
                month_date = dt.date()
                # 找出這個月之前「最近一次公布」的 TTM EPS（財報公布前不套用未公布的數字）
                applicable_eps = None
                for report_date, ttm_eps in ttm_points:
                    if report_date <= month_date:
                        applicable_eps = ttm_eps
                    else:
                        break
                if applicable_eps:
                    pe = row["Close"] / applicable_eps
                    if 0 < pe < 1000:
                        trailing_3y.append({"date": dt.strftime("%Y-%m"), "pe": round(pe, 1)})

        return {"trailing_3y": trailing_3y, "forward_pe": forward_pe}
    except Exception as e:
        print(f"  ⚠️ {display_name} P/E 抓取失敗: {e}")
        return {"trailing_3y": [], "forward_pe": None}


def fetch_all_pe_data():
    """抓取所有追蹤標的的 Trailing P/E 歷史與 Forward P/E 當前值。"""
    result = {}
    for market, tickers in PE_TICKERS.items():
        result[market] = []
        for symbol, name in tickers:
            pe_data = fetch_pe_history(symbol, name)
            trailing_3y = pe_data["trailing_3y"]
            forward_pe = pe_data["forward_pe"]
            trailing_1y = trailing_3y[-12:] if len(trailing_3y) >= 12 else trailing_3y
            current_trailing = trailing_3y[-1]["pe"] if trailing_3y else None
            if trailing_3y or forward_pe:
                result[market].append({
                    "symbol": symbol,
                    "name": name,
                    "trailing_3y": trailing_3y,
                    "trailing_1y": trailing_1y,
                    "current_trailing_pe": current_trailing,
                    "current_forward_pe": forward_pe,
                })
                print(f"  P/E {name}: Trailing={current_trailing} Forward={forward_pe} ({len(trailing_3y)}個月趨勢)")
    return result


# ── 法人連三日買賣超排行：用 TWSE OpenAPI 預抓，避免 AI 網路搜尋出精確數字時幻覺 ──

def _fetch_twse_t86(date_yyyymmdd):
    """抓取指定日期的台股三大法人買賣超日報（每檔個股，股數）。查無資料（假日）回傳 None。"""
    import requests
    resp = requests.get(
        "https://www.twse.com.tw/rwd/zh/fund/T86",
        params={"date": date_yyyymmdd, "selectType": "ALL", "response": "json"},
        timeout=15,
    )
    data = resp.json()
    if data.get("stat") != "OK":
        return None

    fields = data["fields"]
    idx = {name: i for i, name in enumerate(fields)}

    def to_int(s):
        s = (s or "").strip()
        return int(s.replace(",", "")) if s not in ("", "--") else 0

    rows = {}
    for row in data["data"]:
        code = row[idx["證券代號"]].strip()
        rows[code] = {
            "name": row[idx["證券名稱"]].strip(),
            "foreign_net": to_int(row[idx["外陸資買賣超股數(不含外資自營商)"]]) + to_int(row[idx["外資自營商買賣超股數"]]),
            "trust_net": to_int(row[idx["投信買賣超股數"]]),
        }
    return rows


def _fetch_twse_close_prices():
    """抓取最新一個交易日全部台股收盤價，用來估算法人買賣超金額（估算值，非逐日精確金額）。"""
    import requests
    try:
        resp = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15)
        return {row["Code"]: float(row["ClosingPrice"]) for row in resp.json() if row.get("ClosingPrice")}
    except Exception as e:
        print(f"  ⚠️ 收盤價抓取失敗（{e}），法人排行將不含估算金額")
        return {}


def fetch_institutional_3day_ranking(base_date):
    """
    用 TWSE OpenAPI 抓取最近 3 個交易日的三大法人（外資／投信）買賣超日報，
    找出「連三日同向買賣超」（3 天方向一致）個股，依 3 日合計張數排名前 10。
    金額用最新收盤價估算（非逐日精確金額，僅供參考）。
    任何一步失敗都回傳 None，由呼叫端退回讓 AI 自行搜尋。
    """
    try:
        trading_days = []
        cursor = base_date - timedelta(days=1)
        attempts = 0
        while len(trading_days) < 3 and attempts < 10:
            attempts += 1
            if cursor.weekday() < 5:
                day_data = _fetch_twse_t86(cursor.strftime("%Y%m%d"))
                if day_data:
                    trading_days.append((cursor.strftime("%Y-%m-%d"), day_data))
            cursor -= timedelta(days=1)

        if len(trading_days) < 3:
            print(f"  ⚠️ 僅取得 {len(trading_days)} 個交易日的法人資料，跳過連三日排行預抓（改由 AI 搜尋）")
            return None

        trading_days.sort(key=lambda x: x[0])  # 由舊到新
        dates = [d for d, _ in trading_days]
        common_codes = set(trading_days[0][1]) & set(trading_days[1][1]) & set(trading_days[2][1])
        close_prices = _fetch_twse_close_prices()

        def rank_for(field):
            results = []
            for code in common_codes:
                nets = [day_data[code][field] for _, day_data in trading_days]
                if all(n > 0 for n in nets) or all(n < 0 for n in nets):
                    total_shares = sum(nets)
                    price = close_prices.get(code)
                    results.append({
                        "code": code,
                        "name": trading_days[-1][1][code]["name"],
                        "lots_3d": round(total_shares / 1000, 1),
                        "est_amount_ntd": round(total_shares * price) if price else None,
                    })
            buys = sorted([r for r in results if r["lots_3d"] > 0], key=lambda r: -r["lots_3d"])[:10]
            sells = sorted([r for r in results if r["lots_3d"] < 0], key=lambda r: r["lots_3d"])[:10]
            return buys, sells

        foreign_buy, foreign_sell = rank_for("foreign_net")
        trust_buy, trust_sell = rank_for("trust_net")
        print(f"  法人連三日排行：外資買{len(foreign_buy)}/賣{len(foreign_sell)}，投信買{len(trust_buy)}/賣{len(trust_sell)}（{dates[0]}~{dates[-1]}）")

        return {
            "as_of_dates": dates,
            "foreign_buy_top10": foreign_buy,
            "foreign_sell_top10": foreign_sell,
            "trust_buy_top10": trust_buy,
            "trust_sell_top10": trust_sell,
        }
    except Exception as e:
        print(f"  ⚠️ 法人連三日排行預抓失敗（{e}），改由 AI 搜尋")
        return None


# ── 三地市場分析 Prompt：讀取獨立 prompt 檔並注入主 prompt ──────────────────

def load_market_analysis_prompt(date_str, weekday_cn):
    """讀取 doc/Prompt/daily_market_analysis_prompt.md，去除檔頭使用說明，代入今日日期。"""
    path = "doc/Prompt/daily_market_analysis_prompt.md"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"  ⚠️ 找不到 {path}，跳過三地市場深度分析區塊")
        return None

    parts = content.split("---\n\n", 1)
    body = parts[1] if len(parts) > 1 else content
    return body.replace("{{TODAY}}", f"{date_str}，{weekday_cn}")


# ── 恐懼指數：VIX（美股）近 6 個月日資料 ──────────────────────

FEAR_INDEX_TICKERS = {
    "us": ("^VIX",  "美股 VIX 恐懼指數"),
}


def fetch_fear_index_history(symbol, display_name, period="6mo"):
    """抓取近 period 的每日收盤值，回傳 [{"date":"2026-01-02","value":18.5}, ...]"""
    try:
        import yfinance as yf
        hist = yf.Ticker(symbol).history(period=period, interval="1d")
        if hist.empty:
            return []
        results = [
            {"date": dt.strftime("%Y-%m-%d"), "value": round(row["Close"], 2)}
            for dt, row in hist.iterrows()
        ]
        print(f"  恐懼指數 {display_name}: {len(results)} 天資料")
        return results
    except Exception as e:
        print(f"  ⚠️ {display_name} 抓取失敗: {e}")
        return []


def fetch_all_fear_index():
    """回傳美股恐懼指數歷史，格式供 JSON 注入。"""
    result = {}
    for key, (symbol, name) in FEAR_INDEX_TICKERS.items():
        result[key] = {
            "symbol": symbol,
            "name":   name,
            "history": fetch_fear_index_history(symbol, name),
        }
    return result


TZ_TW = timezone(timedelta(hours=8))
today = datetime.now(TZ_TW)

if os.environ.get("DATE_OVERRIDE"):
    today = datetime.strptime(os.environ["DATE_OVERRIDE"], "%Y-%m-%d").replace(tzinfo=TZ_TW)

date_str   = today.strftime("%Y-%m-%d")
date_label = today.strftime("%Y.%m.%d")
weekday_cn = ["週一","週二","週三","週四","週五","週六","週日"][today.weekday()]

print(f"[{date_str}] 檢查今日是否已發布...")
if os.path.exists(f"Backup/{date_str}.html"):
    print(f"  今日報告已存在（Backup/{date_str}.html），跳過本次生成（一天只發布一次）。")
    exit(0)

print(f"[{date_str}] 檢查美股假日...")
if is_prev_us_day_holiday(today):
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    print(f"  前一美股交易日 {prev.strftime('%Y-%m-%d')} 為假日，跳過本次報告生成。")
    exit(0)

print(f"[{date_str}] 檢查台股假日...")
tw_holiday_note = ""
if is_prev_tw_day_holiday(today):
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    print(f"  前一台股交易日 {prev.strftime('%Y-%m-%d')} 為假日（休市/國定假日），台股數據將標註為最近交易日資料。")
    tw_holiday_note = (
        "\n【重要】今日台股休市（國定假日或連假）。所有台股相關數字（台積電、鴻海、聯發科、0050、加權指數等）"
        "請明確標註為「最近一個交易日」資料，勿當作今日即時數字呈現。\n"
    )

print("  正在用 yfinance 抓取未來 2 週財報日曆...")
earnings_data = fetch_earnings_calendar(today)
earnings_table = format_earnings_for_prompt(earnings_data)
print(f"  財報日曆：找到 {len(earnings_data)} 筆")

print("  正在用 yfinance 抓取本益比趨勢（1Y / 3Y）...")
import json as _json
pe_data = fetch_all_pe_data()
pe_json = _json.dumps(pe_data, ensure_ascii=False)

print("  正在用 yfinance 抓取恐懼指數（近 6 個月）...")
fear_data = fetch_all_fear_index()
fear_json = _json.dumps(fear_data, ensure_ascii=False)

print("  正在用 TWSE OpenAPI 抓取法人連三日買賣超排行...")
institutional_data = fetch_institutional_3day_ranking(today)
institutional_json = _json.dumps(institutional_data, ensure_ascii=False) if institutional_data else None

print("  正在讀取三地市場深度分析 prompt...")
market_analysis_prompt = load_market_analysis_prompt(date_str, weekday_cn)

if institutional_json:
    institutional_prefetch_block = f"""
## 【已預先抓取】法人連三日買賣超排行（直接用於圖表，勿再搜尋，勿自行編造股號或數字）
以下 JSON 來自 TWSE OpenAPI 三大法人買賣超日報，已計算連續 3 個交易日同向買賣超個股：

{institutional_json}

欄位說明：as_of_dates = 計算所用的 3 個交易日；lots_3d = 3 日合計買賣超張數（正=買超，負=賣超）；
est_amount_ntd = 用最新收盤價估算的金額（新台幣元，非逐日精確金額，屬估算值，null 表示無收盤價可估算）。
"""
    institutional_task_line = (
        "3. 台股三大法人動向：搜尋外資/投信/自營商「整體」買賣超金額（連三日個股排行已預先抓取，不需再搜尋，"
        "直接使用上方 JSON，勿自行編造股號或金額）"
    )
else:
    institutional_prefetch_block = ""
    institutional_task_line = """3. 台股三大法人動向：外資/投信/自營商整體買賣超金額；並分別搜尋「連三日同向買賣超排行」：
   - 外資連三日買超前 10 名個股（股號、股名、三日買超金額、三日買超張數）
   - 外資連三日賣超前 10 名個股（股號、股名、三日賣超金額、三日賣超張數）
   - 投信連三日買超前 10 名個股（股號、股名、三日買超金額、三日買超張數）
   - 投信連三日賣超前 10 名個股（股號、股名、三日賣超金額、三日賣超張數）
   （資料來源建議：CMoney、goodinfo.tw、twse.com.tw、anue.com、moneyDJ）"""

PROMPT = f"""
今天是 {date_label}（{weekday_cn}），台灣台中。
{tw_holiday_note}請為我生成一份完整的「每日投資情報 HTML 網頁」。

## 【已預先抓取】未來 2 週財報日曆（直接使用，勿再搜尋）
以下資料來自 Yahoo Finance API，請直接用於財報速覽區塊，不需要再搜尋財報日期：

{earnings_table}

## 【已預先抓取】本益比趨勢資料（直接用於圖表，勿再搜尋）
以下 JSON 包含台股與美股各標的的月度 P/E 歷史（1Y / 3Y），請直接用於本益比趨勢圖區塊：

{pe_json}

欄位說明：trailing_3y = 近 3 年月 Trailing P/E 歷史趨勢；trailing_1y = 近 1 年月資料；current_trailing_pe = 當前 Trailing P/E（TTM 實際 EPS）；current_forward_pe = 當前 Forward P/E（分析師預估未來 12 個月 EPS，null 表示無資料）。

## 【已預先抓取】美股 VIX 恐懼指數近 6 個月日資料（直接用於圖表，勿再搜尋）
{fear_json}

欄位說明：history = 每日 [{{"date":"YYYY-MM-DD","value":數值}}] 陣列。
{institutional_prefetch_block}
## 必須完成的搜尋任務（依序執行，至少 8 次搜尋）
1. 今日/昨日美股收盤：S&P 500、Nasdaq、Dow 漲跌幅與主要個股
2. 台股今日行情：加權指數、台積電（2330）、鴻海（2317）、聯發科（2454）
{institutional_task_line}
4. 今日最重要的 AI/半導體新聞（NVDA/TSMC/AVGO/MRVL）
5. 地緣政治：伊朗局勢最新進展、油價動態
6. 總體經濟：Fed 動態、美債殖利率、PCE/CPI 最新數據、CME FedWatch 降息機率
7. SpaceX SPCX 等重大 IPO 進度
8. 台指期夜盤最新走勢：當日夜盤開盤價、最新價、漲跌點數、成交量、與日盤收盤的差距
9. LLY Foundayo（orforglipron）週處方量（TRx）趨勢：
    - Foundayo 是 Eli Lilly orforglipron 的商品名，為口服 GLP-1 小分子藥物，與 Mounjaro/Zepbound（tirzepatide 注射劑）是完全不同的產品線，絕對不可混用或替代
    - 搜尋最近 8–12 週的 Foundayo / orforglipron 週處方量數據（來源：IQVIA、Symphony Health、投行研報、財經新聞）
    - 取得每週 TRx 絕對數量與週增長率（WoW%）
    - 若暫無處方量數據（如仍在商業化初期），搜尋 orforglipron 上市進度、處方量放量速度分析師預估或醫療通路鋪貨狀況，並在圖表區說明目前所處商業化階段
10. AI 基礎建設驗證指標（三項，每項均需搜尋最新數據）：
   - CSP capex 同比變化：Microsoft/Amazon/Google/Meta 最新季度雲端資本支出金額與 YoY 成長率
   - AI 伺服器出貨量月度趨勢：最新月份全球 AI 伺服器出貨量或出貨量預估（來源：TrendForce / IDC）
   - HBM 合約價與現貨價利差：最新 HBM3e 或 HBM3 合約價、現貨價，及兩者利差（來源：DRAMeXchange / TrendForce）

## 額外任務：三地市場深度分析（獨立完整執行，結果嵌入 HTML 新區塊）
除了上方任務外，請完整執行以下這份獨立的「每日三地市場分析」規格（含台股/美股/韓股搜尋、資料規則、信心等級標註 F/G/E/I/W、洗盤 vs 出貨七維度快檢），並將完整分析結果整理成 HTML 報告中的一個新區塊（區塊標題：「三地市場深度分析」）。此區塊需完整保留下方七大結構（核心結論、事件鏈、美股、韓股、台股、洗盤vs出貨七維度快檢表格、行動清單），並在區塊末尾附上「今日資料缺口」清單。以下為完整規格：

---
{market_analysis_prompt if market_analysis_prompt else "（找不到 doc/Prompt/daily_market_analysis_prompt.md，此區塊略過）"}
---

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
- AI 基礎建設驗證指標區塊（每次必須包含，使用搜尋任務 10 的數據）：
  - 3 格並排卡片，每格一個指標
  - 格 1「CSP Capex YoY」：顯示 MSFT/AMZN/GOOGL/META 各自最新季度 capex 金額與 YoY%，用小 bar 或數值對比呈現
  - 格 2「AI 伺服器出貨量」：顯示最新月份數字與月度趨勢方向（↑↓），標明來源與月份
  - 格 3「HBM 價差」：顯示合約價、現貨價、利差金額與百分比；利差擴大標綠（供需緊）、收窄標紅
  - 每格底部標明資料來源與日期
- KPI 指標看板（4 格）
- 視覺圖表區（Chart.js 4.4.1 + datalabels 2.2.0）
- LLY Foundayo 週處方量區塊（使用搜尋任務 9 的數據）：
  - 上方：Chart.js 折線圖，X 軸為週別（如 W1/W2...），Y 軸為 TRx 數量（千份）
  - 下方：長條圖或標注，顯示每週 WoW 增長率（%），正增長綠色、負增長紅色
  - 右上角顯示最新一週 TRx 數值與 WoW%（大字突出）
  - 【重要】Foundayo = orforglipron（口服小分子 GLP-1），與 Mounjaro/Zepbound（tirzepatide 注射劑）是獨立產品線，圖表內容嚴禁混用
  - 若 TRx 數據尚不可得（商業化初期），改以文字卡片說明：當前商業化階段、分析師 TRx 放量預估、鋪貨進度
  - 標明資料來源（IQVIA / Symphony Health / 投行）與資料截止日期
- 美股 VIX 恐懼指數近 6 個月趨勢圖區塊（使用上方 fear_data JSON）：
  - Chart.js 折線圖，X 軸：近 6 個月日期；Y 軸：VIX 指數值
  - 加入水平參考線：VIX 20（警戒）、VIX 30（恐慌），標示顏色
  - 線條顏色：數值高於 25 時轉紅，低於 15 時轉綠，中間為琥珀色
- 台指期夜盤動態區塊：
  - 顯示夜盤最新報價、漲跌點數與百分比、成交量
  - 與日盤收盤差距（用顏色標示漲跌：漲綠跌紅）
  - 夜盤交易時段說明（15:00–05:00 台灣時間）
  - 資料來源標示（搜尋到的資料時間）
- 本益比趨勢圖區塊（使用上方已提供的 pe_data JSON）：
  - 兩個 Tab：「台股」和「美股」
  - 每個 Tab 內有「1Y」和「3Y」切換按鈕
  - Chart.js 折線圖，深色主題，格線淡化
  - 台股 Tab：顯示 pe_data.tw 各標的的 Trailing P/E 歷史趨勢（多條實線，每條一個顏色）
  - 美股 Tab：顯示 pe_data.us 各標的的 Trailing P/E 歷史趨勢（多條實線，每條一個顏色）
  - Forward P/E 顯示方式（每個標的）：
    - 若 current_forward_pe 不為 null，在圖表上畫一條對應顏色的**水平虛線**，代表當前 Forward P/E 水準
    - 水平虛線加上 label「{{name}} Fwd」
  - 圖表右上角（圖表內浮層）顯示當前數值對比小表格：每個標的一行，顯示「名稱 ｜ Trailing: xx.x ｜ Forward: xx.x」，Forward 若無資料顯示「N/A」
  - 若某標的 trailing_3y / trailing_1y 為空且 current_forward_pe 也為 null，則不渲染該標的
  - 圖表標題標明「本益比（P/E）趨勢 — 實線 Trailing TTM / 虛線 Forward」
- 台股法人連三日買賣超排行區塊（使用搜尋任務 3 的外資/投信連三日前10名數據）：
  - 標題「法人連三日同向買賣超排行」，副標題顯示資料截止日期
  - 頂部 2 個 Tab 切換：「外資」「投信」
  - 每個 Tab 內並排 2 欄（左右各半）：
    - 左欄：綠色標題列「連三日買超前十」，表格欄位：排名 ｜ 股號 ｜ 股名 ｜ 三日買超(金額) ｜ 三日買超(張)，金額數字綠色
    - 右欄：紅色標題列「連三日賣超前十」，表格欄位：排名 ｜ 股號 ｜ 股名 ｜ 三日賣超(金額) ｜ 三日賣超(張)，金額數字紅色
  - 表格背景深色，交替列略微區隔，字體使用 IBM Plex Mono
  - 若資料不足 10 筆，顯示實際取得的筆數
  - 若使用上方【已預先抓取】法人資料：金額欄位是用最新收盤價估算（est_amount_ntd 為 null 時該欄顯示「—」），底部標明「資料來源：TWSE OpenAPI（估算金額）」與截止日期（as_of_dates）；若該區塊改為 AI 搜尋取得，底部標明實際搜尋來源（CMoney / Goodinfo / 證交所）與截止日期
- 未來 2 週財報速覽（Filter 按鈕：全部/美股/台股/★持倉）
- 財經新聞中心（Tab：4 個主題）
- 三地市場深度分析區塊（置於財經新聞中心之後、風險矩陣之前；使用上方「額外任務」的完整分析內容）：
  - 依序完整呈現：核心結論、事件鏈、美股、韓股、台股、洗盤vs出貨七維度快檢表格、行動清單、今日資料缺口
  - 信心等級（F/G/E/I/W）以小色塊標籤呈現在每個數據點旁：F 綠、G 藍、E 黃、I 紫、W 灰（灰底不可過暗，需符合文字色階規則）
  - 洗盤vs出貨七維度快檢用表格呈現（維度｜今日觀察｜傾向），並在表格下方明顯標示機率權重（如「洗盤 70% / 出貨 30%」）與升級/降級條件
  - 行動清單用 checklist 樣式（若 X 發生 → 做 Y），附價位與日期
  - 比較性數據一律用表格，分析文字用完整散文段落，避免碎片化 bullet
- 風險矩陣表格
- 投資主題機會（5 張卡片）
- 大師策略總結（3 欄）
- Footer（資料來源）

## 個人持倉背景
台積電(2330)、鴻海(2317)、聯發科(2454)、SMH、NVDA、AVGO、ORCL、LLY、0050、IAUM(黃金)

## 輸出格式
輸出完整的 HTML，用 ```html ... ``` 包裹，包含所有 CSS 和 JavaScript。
在 `<body>` 開始標籤之後，立刻加入一段 HTML 註解，格式如下（供推播通知使用，不會顯示給讀者）：
<!--SUMMARY
第一行：大盤漲跌重點（台股加權指數、那斯達克等關鍵指數當日表現，一行內）
第二行：今日最重要的一則新聞或事件（一行內）
第三行：對持倉組合最需要注意的一點（一行內）
SUMMARY-->
每行不加任何 Markdown 符號，純文字即可，總長度控制在 150 字以內。
不要解釋，直接輸出 HTML。
"""

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

print(f"[{date_str}] 開始生成報告...")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 64000
TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 16}]

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


def validate_html(html: str) -> list[str]:
    """回傳驗證失敗的原因清單；空清單代表通過。避免截斷或空洞的報告被發布上線。"""
    problems = []
    if len(html) < 20000:
        problems.append(f"內容過短（{len(html):,} bytes，預期 20,000+）")
    if "</html>" not in html.lower():
        problems.append("找不到 </html> 結尾標籤，內容可能被截斷")
    for required in ("<table", "<canvas", "<script"):
        if required not in html.lower():
            problems.append(f"找不到必要標籤 {required}")
    return problems


validation_problems = validate_html(html_content)
if validation_problems:
    raise RuntimeError(
        "報告驗證失敗，中止發布以避免半份報告上線：\n  - " + "\n  - ".join(validation_problems)
    )
print("  ✅ 報告驗證通過")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

backup_dir = "Backup"
os.makedirs(backup_dir, exist_ok=True)
shutil.copy("index.html", f"{backup_dir}/{date_str}.html")

print(f"  ✅ 報告已寫入 index.html（{len(html_content):,} bytes）")
print(f"  ✅ 已備份至 Backup/{date_str}.html")

summary_match = re.search(r"<!--SUMMARY\s*([\s\S]*?)SUMMARY-->", html_content)
summary_text = summary_match.group(1).strip() if summary_match else ""
if summary_text:
    print(f"  📋 摘要：{summary_text}")
else:
    print("  ⚠️ 未找到通知摘要（SUMMARY 註解），通知將只包含連結")

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a", encoding="utf-8") as f:
        f.write("summary<<REPORT_SUMMARY_EOF\n")
        f.write(summary_text + "\n")
        f.write("REPORT_SUMMARY_EOF\n")
