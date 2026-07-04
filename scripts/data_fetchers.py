"""
每日報告用的所有資料預抓函式：yfinance（財報日曆／P/E／VIX／即時報價）、
TWSE OpenAPI（法人連三日買賣超）、假日判斷、市場分析 prompt 讀取。
"""
import math
from datetime import datetime, timedelta
import yfinance as yf

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

# 台股個人持倉：(yfinance 代號, 顯示代號)，市場標記為「台股」
TW_EARNINGS_WATCH = [
    ("2330.TW", "2330"),
    ("2317.TW", "2317"),
    ("2454.TW", "2454"),
]


def _fetch_earnings_for_symbol(yf, symbol, display_symbol, market, base_date, end_date):
    """查詢單一標的的財報日期，回傳落在區間內的第一筆（或 None）。"""
    try:
        ticker = yf.Ticker(symbol)
        cal = ticker.calendar
        if not cal:
            return None

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
                return {
                    "date":   ed.strftime("%Y-%m-%d"),
                    "symbol": display_symbol,
                    "name":   info.get("longName", display_symbol),
                    "market": market,
                }
    except Exception as e:
        print(f"  ⚠️ {display_symbol} 財報查詢失敗: {e}")
    return None


def fetch_earnings_calendar(base_date, days_ahead=14):
    """用 yfinance 抓未來 days_ahead 天內的財報日期（美股 + 台股持倉），回傳排序好的 list。"""
    try:
        import yfinance as yf
    except ImportError:
        print("  ⚠️ yfinance 未安裝，跳過財報 API 抓取")
        return []

    end_date = base_date + timedelta(days=days_ahead)
    results = []

    for symbol in EARNINGS_WATCH:
        row = _fetch_earnings_for_symbol(yf, symbol, symbol, "美股", base_date, end_date)
        if row:
            results.append(row)

    for yf_symbol, display_symbol in TW_EARNINGS_WATCH:
        row = _fetch_earnings_for_symbol(yf, yf_symbol, display_symbol, "台股", base_date, end_date)
        if row:
            results.append(row)

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

def _twse_to_int(s):
    """把 TWSE OpenAPI 的數字字串（可能含千分位逗號、空字串或 "--"）轉成 int，缺值視為 0。"""
    s = (s or "").strip()
    return int(s.replace(",", "")) if s not in ("", "--") else 0


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

    rows = {}
    for row in data["data"]:
        code = row[idx["證券代號"]].strip()
        rows[code] = {
            "name": row[idx["證券名稱"]].strip(),
            "foreign_net": _twse_to_int(row[idx["外陸資買賣超股數(不含外資自營商)"]]) + _twse_to_int(row[idx["外資自營商買賣超股數"]]),
            "trust_net": _twse_to_int(row[idx["投信買賣超股數"]]),
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


def fetch_institutional_3day_ranking(base_date, close_prices=None):
    """
    用 TWSE OpenAPI 抓取最近 3 個交易日的三大法人（外資／投信）買賣超日報，
    找出「連三日同向買賣超」（3 天方向一致）個股，依 3 日合計張數排名前 10。
    金額用最新收盤價估算（非逐日精確金額，僅供參考）。
    任何一步失敗都回傳 None，由呼叫端退回讓 AI 自行搜尋。

    close_prices：可選，呼叫端若已經呼叫過 _fetch_twse_close_prices()（例如
    generate_report.py 同一次執行還會呼叫 fetch_watchlist_institutional()，
    兩者原本都各自打一次 STOCK_DAY_ALL 端點），可以把結果傳進來重用，避免
    同一個 run 打兩次一模一樣的 TWSE API。預設 None 時維持原本自行抓取的行為。
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
        close_prices = close_prices if close_prices is not None else _fetch_twse_close_prices()

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


def fetch_watchlist_institutional(codes, base_date, close_prices_and_value=None):
    """
    抓取「今天」（實際上是最近一個有資料的交易日，往前找最多 5 天）一天的三大法人
    買賣超（重用既有 _fetch_twse_t86），篩選出 codes 清單內的個股，並算出：
    - dual_buy：外資與投信是否同一天同步買超（皆 > 0）
    - buy_value_ratio_pct：外資+投信合計買超金額（用收盤價估算） / 當日成交值 * 100
      （買超佔成交值比重，取代絕對金額排序——對中小型股更有鑑別度）

    close_prices_and_value：可選的 (close_prices, trade_values) tuple，用途同
    fetch_institutional_3day_ranking() 的 close_prices 參數——避免同一次執行內
    重複打一次 STOCK_DAY_ALL。預設 None 時維持原本自行抓取的行為。
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

    close_prices, trade_values = (
        close_prices_and_value if close_prices_and_value is not None else _fetch_twse_close_prices_and_value()
    )
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


# ── 融資融券：軋空候選（券資比偏高）訊號 ──────────────────────────────

def fetch_margin_trading(codes):
    """
    抓取 TWSE OpenAPI 集中市場融資融券餘額（全市場一次回傳，不支援用代號查詢），
    篩選出 codes 清單內的個股，計算券資比（融券今日餘額 / 融資今日餘額 * 100）。
    codes: 要篩選的股票代號 list（不含 .TW 後綴，例如 ["2330", "2317"]）。
    """
    import requests

    result = {}
    try:
        resp = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN", timeout=15)
        data = resp.json()
        code_set = set(codes)
        for row in data:
            code = row.get("股票代號", "").strip()
            if code not in code_set:
                continue
            margin_balance = _twse_to_int(row.get("融資今日餘額"))
            short_balance = _twse_to_int(row.get("融券今日餘額"))
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
        print(f"  {display_name}: {len(results)} 天資料")
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


# ── 即時報價：ticker 跑馬燈 / KPI 儀表板用，取代 AI 手key 數字 ──────────────

QUOTE_TICKERS = {
    "TWII":  ("^TWII", "加權指數"),
    "2330":  ("2330.TW", "台積電"),
    "2317":  ("2317.TW", "鴻海"),
    "2454":  ("2454.TW", "聯發科"),
    "0050":  ("0050.TW", "0050"),
    "SPX":   ("^GSPC", "S&P 500"),
    "NASDAQ": ("^IXIC", "Nasdaq"),
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


def _has_nan_close(*closes):
    """
    收盤價含 NaN 時回傳 True。yfinance 對「今天尚未真正收盤/結算」的最後一列
    常見回傳 NaN 而不是缺列——len(hist) < 2 這個檢查抓不到這種情況（列數正常，
    只是值是 NaN），若不擋下來，NaN 會原樣流進 Jinja context，在報告上顯示成
    "NaN" 字樣或讓 tojson 輸出壞掉的 JSON。每天 08:00（台灣時間）執行時，美股
    /韓股當天的交易日可能還沒完全結算，這個情況並非罕見邊界案例。
    """
    return any(math.isnan(c) for c in closes)


def fetch_quotes():
    """
    抓取 QUOTE_TICKERS 全部標的最新收盤價與日漲跌（%）。
    單一標的失敗不影響其他標的；該標的從結果中省略，由呼叫端決定如何顯示缺值。
    """
    result = {}
    for key, (symbol, name) in QUOTE_TICKERS.items():
        try:
            hist = yf.Ticker(symbol).history(period="5d", interval="1d")
            if hist.empty or len(hist) < 2:
                print(f"  ⚠️ {name}({symbol}) 報價資料不足，略過")
                continue
            prev_close = float(hist["Close"].iloc[-2])
            last_close = float(hist["Close"].iloc[-1])
            if _has_nan_close(prev_close, last_close):
                print(f"  ⚠️ {name}({symbol}) 收盤價為 NaN（可能尚未收盤結算），略過")
                continue
            # ^TNX（10Y 美債殖利率）Yahoo/CBOE 回傳的是殖利率 x10（例如 4.48% 顯示為 44.8），
            # 換算成實際百分比才能直接當殖利率呈現；change_pct 是比值不受影響，不需調整。
            if symbol == "^TNX":
                prev_close /= 10
                last_close /= 10
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
            if _has_nan_close(prev_close, last_close):
                print(f"  ⚠️ {name}({symbol}) 收盤價為 NaN（可能尚未收盤結算），略過")
                continue
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
            if _has_nan_close(prev_close, last_close):
                print(f"  ⚠️ {symbol} 收盤價為 NaN（可能尚未收盤結算），略過")
                continue
            change_pct = (last_close - prev_close) / prev_close * 100 if prev_close else 0.0
            result.append({"symbol": symbol, "change_pct": round(change_pct, 2)})
        except Exception as e:
            print(f"  ⚠️ {symbol} 熱力圖抓取失敗: {e}")
    print(f"  美股熱力圖：成功 {len(result)}/{len(US_HEATMAP_TICKERS)} 檔")
    return result


# ── 美股資金板塊輪動：11 檔 SPDR 產業 ETF 當日 + 一週表現 ──────────────────

SECTOR_ETF_TICKERS = [
    ("XLK", "科技"), ("XLF", "金融"), ("XLE", "能源"), ("XLV", "醫療"),
    ("XLY", "非必需消費"), ("XLP", "必需消費"), ("XLI", "工業"),
    ("XLB", "原物料"), ("XLRE", "房地產"), ("XLU", "公用事業"), ("XLC", "通訊服務"),
]


def fetch_sector_rotation():
    """抓取 11 檔 SPDR 產業 ETF 近 2 週日線，算出當日與一週漲跌 %。
    period="2wk" 是日曆 2 週，實際回傳的交易日筆數會隨當週有無假日在 9-10 筆左右
    （兩個接近完整的 5 個交易日的星期）——若直接拿「這個區間的第一筆」當作「一週前」，
    實際量測的是接近 2 週前、而非 1 週前的價格，"一週漲跌" 的標籤會系統性失真。
    改成固定往回數 5 個交易日（index -6，「今天」是 -1）代表「一週前」，資料筆數不足
    5 個交易日時才退回用「這個區間最早的一筆」（比什麼都沒有好，但不是常態）。"""
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
            week_ago_idx = -6 if len(closes) >= 6 else 0
            week_ago = float(closes.iloc[week_ago_idx])
            if _has_nan_close(last, prev_day, week_ago):
                print(f"  ⚠️ {name}({symbol}) 收盤價為 NaN（可能尚未收盤結算），略過")
                continue
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


# ── ADR 溢價：TSM/UMC/ASX 對應台股的溢價率 ────────────────────────────────

ADR_TICKERS = {
    "TSM": ("2330.TW", "2330", 5),   # (台股 yfinance 代號, 顯示代號, ADR:普通股比例)
    "UMC": ("2303.TW", "2303", 5),
    # ASX 原始 2003 上市比例為 1:5，現行比例已改為 1 ADS = 2 普通股
    # （見 ASE Technology Holding 20-F 申報文件與 Nasdaq 掛牌資訊）
    "ASX": ("3711.TW", "3711", 2),
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


# ── 月營收：YoY 大增訊號（v1 只做 YoY，不做「創新高」——見前置事實說明） ──

def fetch_monthly_revenue(codes):
    """
    抓取 TWSE OpenAPI 上市公司每月營業收入彙總表（全市場一次回傳，不支援用代號查詢），
    篩選出 codes 清單內的個股。v1 只用資料源本身已算好的「去年同月增減(%)」，
    不嘗試回推歷史月營收序列去判斷「是否創新高」（免費資料源沒有提供夠長的歷史）。
    """
    result = {}
    import requests
    try:
        resp = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", timeout=15)
        data = resp.json()
        code_set = set(codes)
        for row in data:
            code = (row.get("公司代號") or "").strip()
            if code not in code_set:
                continue
            try:
                yoy = float(row.get("營業收入-去年同月增減(%)") or 0)
            except ValueError:
                yoy = 0.0
            result[code] = {
                "name": (row.get("公司名稱") or "").strip(),
                "revenue": (row.get("營業收入-當月營收") or "").strip(),
                "yoy_change_pct": round(yoy, 2),
            }
    except Exception as e:
        print(f"  ⚠️ 月營收資料抓取失敗: {e}")
    print(f"  月營收：清單內找到 {len(result)}/{len(codes)} 檔資料")
    return result


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
            # 逐列一起過濾（而非分別過濾 Close/Volume 兩個 list）：
            # 避免某一列只有 Close 或只有 Volume 是 NaN 時，兩個 list 各自砍掉不同列，
            # 造成位置錯位（closes[i] 跟 volumes[i] 變成不同交易日的資料）。
            valid_rows = [
                (float(c), float(v))
                for c, v in zip(hist["Close"].tolist(), hist["Volume"].tolist())
                if not math.isnan(c) and not math.isnan(v)
            ]
            closes = [c for c, _ in valid_rows]
            volumes = [v for _, v in valid_rows]
            if len(closes) < 21 or len(volumes) < 6:
                print(f"  ⚠️ {code}({symbol}) 有效資料不足，略過")
                continue
            result[code] = {"closes": closes[-30:], "volumes": volumes[-30:]}
        except Exception as e:
            print(f"  ⚠️ {code}({symbol}) 歷史價量抓取失敗: {e}")
    print(f"  觀察清單歷史價量：成功 {len(result)}/{len(watchlist)} 檔")
    return result
