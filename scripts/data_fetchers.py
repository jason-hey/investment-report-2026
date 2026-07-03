"""
每日報告用的所有資料預抓函式：yfinance（財報日曆／P/E／VIX／即時報價）、
TWSE OpenAPI（法人連三日買賣超）、假日判斷、市場分析 prompt 讀取。
"""
import requests
from datetime import datetime, timedelta

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
