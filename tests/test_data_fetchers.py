def test_data_fetchers_module_importable():
    import scripts.data_fetchers as df
    assert callable(df.fetch_earnings_calendar)
    assert callable(df.fetch_all_pe_data)
    assert callable(df.fetch_institutional_3day_ranking)
    assert callable(df.fetch_all_fear_index)
    assert callable(df.is_prev_us_day_holiday)
    assert callable(df.is_prev_tw_day_holiday)
    assert callable(df.load_market_analysis_prompt)


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

    # ^TNX（10Y 美債殖利率）Yahoo/CBOE 回傳的是殖利率 x10，price/change 需除以 10 換算成實際百分比
    us10y = result["US10Y"]
    assert us10y["symbol"] == "^TNX"
    assert us10y["price"] == 10.5
    assert us10y["change"] == 0.5
    assert round(us10y["change_pct"], 2) == 5.0


def test_fetch_quotes_skips_ticker_with_nan_close(monkeypatch):
    """
    迴歸測試（實測用真實 yfinance 資料發現）：每天 08:00（台灣時間）執行時，美股/
    韓股當天的交易日可能還沒完全收盤結算，yfinance 對這種「今天」列常回傳
    Close=NaN，列數本身正常（len(hist) >= 2 這個檢查抓不到）。NaN 若沒被擋下來
    會原樣流進模板 context，顯示成 "NaN" 字樣或讓 tojson 輸出壞掉的 JSON。
    """
    import math
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            return pd.DataFrame(
                {"Close": [100.0, math.nan]},
                index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_quotes()

    assert result == {}


def test_fetch_earnings_calendar_includes_tw_holdings(monkeypatch):
    import scripts.data_fetchers as df
    from datetime import datetime, timezone, timedelta

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.calendar = {"Earnings Date": ["2026-07-10"]}
            self.info = {"longName": f"{symbol} Inc"}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    base_date = datetime(2026, 7, 3, tzinfo=timezone(timedelta(hours=8)))
    results = df.fetch_earnings_calendar(base_date, days_ahead=14)

    tw_rows = [r for r in results if r["market"] == "台股"]
    assert {r["symbol"] for r in tw_rows} == {"2330", "2317", "2454"}
    us_rows = [r for r in results if r["market"] == "美股"]
    assert len(us_rows) == len(df.EARNINGS_WATCH)


def test_fetch_pe_history_applies_ttm_eps_only_after_estimated_publication_date(monkeypatch):
    """
    迴歸測試（前視偏差 look-ahead bias）：yfinance 的 quarterly_income_stmt 索引是
    「財報季度截止日」，不是「實際公布日」（美股 10-Q 期限、台股季報期限都是季度結束
    後約 45 天）。若直接拿季度截止日當作 TTM EPS 的生效日，P/E 歷史會在財報公布前
    1~2 個月就套用還沒公開的 EPS——例如 Q1 截止 2026-03-31、實際 5 月中公布，
    4 月的 P/E 點位卻已經用了 Q1 的新 EPS。這裡驗證：TTM EPS 要等到
    「季度截止日 + 45 天」（估計公布日）之後的月份才生效。
    """
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.info = {"forwardPE": None}
            # 5 季 Diluted EPS：前 4 季各 1.0（TTM=4.0，截止 2025-12-31），
            # 最新一季 5.0（TTM=8.0，截止 2026-03-31、估計公布日 2026-05-15）
            self.quarterly_income_stmt = pd.DataFrame(
                [[1.0, 1.0, 1.0, 1.0, 5.0]],
                index=["Diluted EPS"],
                columns=pd.to_datetime(["2025-03-31", "2025-06-30", "2025-09-30",
                                         "2025-12-31", "2026-03-31"]),
            )

        def history(self, period, interval):
            # 兩個月度點位：2026-04（Q1 截止後、公布前）與 2026-06（公布後），收盤價均 80
            return pd.DataFrame(
                {"Close": [80.0, 80.0]},
                index=pd.to_datetime(["2026-04-01", "2026-06-01"]),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_pe_history("NVDA", "NVIDIA")

    by_month = {p["date"]: p["pe"] for p in result["trailing_3y"]}
    # 2026-04：Q1 財報尚未公布（2026-03-31 + 45 天 = 2026-05-15），應仍用舊 TTM 4.0 → P/E 20.0
    assert by_month["2026-04"] == 20.0
    # 2026-06：Q1 已公布，改用新 TTM 8.0 → P/E 10.0
    assert by_month["2026-06"] == 10.0


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


def test_fetch_sector_rotation_returns_1d_and_1w_change(monkeypatch):
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
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


def test_fetch_sector_rotation_uses_fixed_5_trading_days_for_1w_not_whole_window(monkeypatch):
    """
    迴歸測試（實測用真實 yfinance 資料發現）：period="2wk" 是日曆 2 週，實際回傳的
    交易日筆數常常有 9-10 筆（沒遇到假日時接近兩個完整的 5 日工作週），不是「剛好
    一週」。若直接拿這個區間「第一筆」當作一週前的價格，change_pct_1w 量測的其實
    接近 2 週前的價格，跟標籤不符。這裡用 9 筆假資料驗證：一週前應該是「今天」往回
    數第 6 筆（index -6），不是整個區間最早的第 0 筆。
    """
    import scripts.data_fetchers as df
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            # 9 個交易日收盤價（index 0-8）：today=index -1=106.0；5 個交易日前
            # （today 往回數 6 個位置）= index -6 = index 3 = 40.0
            closes = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 106.0]
            return pd.DataFrame(
                {"Close": closes},
                index=pd.date_range("2026-06-22", periods=9, freq="D"),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_sector_rotation()

    first = result[0]
    # 一週前應為 index -6 = 40.0，不是整個區間第一筆（index 0 = 10.0）
    assert round(first["change_pct_1w"], 2) == round((106.0 - 40.0) / 40.0 * 100, 2)


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


def test_fetch_monthly_revenue_handles_null_revenue_field(monkeypatch):
    import scripts.data_fetchers as df
    import requests

    class FakeResponse:
        def json(self):
            return [
                {"公司代號": "2330", "公司名稱": "台積電", "營業收入-當月營收": None,
                 "營業收入-去年同月增減(%)": "35.5"},
            ]

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    result = df.fetch_monthly_revenue(["2330"])

    assert "2330" in result
    assert result["2330"]["revenue"] == ""
    assert result["2330"]["yoy_change_pct"] == 35.5


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


def test_fetch_watchlist_institutional_reuses_supplied_close_prices_and_value(monkeypatch):
    """
    迴歸測試（Task 13 Fix 2）：generate_report.py 同一次執行內會呼叫
    fetch_institutional_3day_ranking() 與 fetch_watchlist_institutional()，兩者
    原本各自打一次 STOCK_DAY_ALL 端點抓一樣的資料。呼叫端可改傳
    close_prices_and_value 參數重用已抓好的資料——這裡驗證傳入後完全不會呼叫
    requests.get（用一個會直接丟例外的假 requests.get 確保沒有走到網路呼叫路徑）。
    """
    import scripts.data_fetchers as df
    import requests
    from datetime import datetime, timezone, timedelta

    def fake_t86(date_str):
        return {"2330": {"name": "台積電", "foreign_net": 5_000_000, "trust_net": 1_000_000}}

    def boom(*a, **k):
        raise AssertionError("不應該呼叫 requests.get：close_prices_and_value 應該被重用")

    monkeypatch.setattr(df, "_fetch_twse_t86", fake_t86)
    monkeypatch.setattr(requests, "get", boom)

    base_date = datetime(2026, 7, 3, tzinfo=timezone(timedelta(hours=8)))
    result = df.fetch_watchlist_institutional(
        ["2330"], base_date,
        close_prices_and_value=({"2330": 500.0}, {"2330": 2_000_000_000}),
    )

    assert "2330" in result
    assert result["2330"]["buy_value_ratio_pct"] is not None


def test_fetch_institutional_3day_ranking_reuses_supplied_close_prices(monkeypatch):
    """
    迴歸測試（Task 13 Fix 2）：同上一個測試，但驗證 fetch_institutional_3day_ranking()
    的 close_prices 參數——傳入後不應該呼叫 requests.get（_fetch_twse_close_prices()
    內部才會打 STOCK_DAY_ALL；_fetch_twse_t86 走的是不同的 T86 端點，這裡改用假的
    _fetch_twse_t86 讓 3 個交易日資料齊全，才能測到「不再另外抓收盤價」這件事）。
    """
    import scripts.data_fetchers as df
    import requests
    from datetime import datetime, timezone, timedelta

    # 連 3 天皆為外資買超的假資料，確保 rank_for() 有結果可以組出來
    def fake_t86(date_str):
        return {"2330": {"name": "台積電", "foreign_net": 1_000_000, "trust_net": 1_000_000}}

    def boom(*a, **k):
        raise AssertionError("不應該呼叫 requests.get：close_prices 應該被重用")

    monkeypatch.setattr(df, "_fetch_twse_t86", fake_t86)
    monkeypatch.setattr(requests, "get", boom)

    base_date = datetime(2026, 7, 6, tzinfo=timezone(timedelta(hours=8)))  # 週一，避開週末
    result = df.fetch_institutional_3day_ranking(base_date, close_prices={"2330": 500.0})

    assert result is not None
    assert len(result["as_of_dates"]) == 3
    buy_codes = [r["code"] for r in result["foreign_buy_top10"]]
    assert "2330" in buy_codes


def test_prev_trading_day_skips_weekend():
    import scripts.data_fetchers as df
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))
    # 2026-07-06 是週一，前一交易日應為週五 2026-07-03（台股正常交易日）
    result = df.prev_trading_day(datetime(2026, 7, 6, tzinfo=tz))
    assert result.strftime("%Y-%m-%d") == "2026-07-03"


def test_prev_trading_day_skips_tw_weekday_holiday():
    """
    迴歸測試（勝率回顧量錯天）：原本 prev_trading_date 只跳過週末、不跳過台股國定
    假日。2026-01-01（元旦，週四）台股休市，2026-01-02（週五）早上跑報告時，
    「前一交易日」應該是 2025-12-31（週三），不是休市的 2026-01-01——否則勝率回顧
    會拿不存在交易的日期去查歷史入選清單，或用選股之前的漲跌來評判選股。
    """
    import scripts.data_fetchers as df
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))
    result = df.prev_trading_day(datetime(2026, 1, 2, tzinfo=tz))
    assert result.strftime("%Y-%m-%d") == "2025-12-31"


def test_prev_trading_day_falls_back_to_weekend_skip_when_calendar_unavailable(monkeypatch):
    """行事曆查詢失敗（版本問題、日期超出行事曆範圍等）時，退回「只跳週末」的保守行為，
    不能讓整個 pipeline 因此崩潰。"""
    import exchange_calendars
    import scripts.data_fetchers as df
    from datetime import datetime, timezone, timedelta

    def boom(*_a, **_k):
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(exchange_calendars, "get_calendar", boom)
    tz = timezone(timedelta(hours=8))
    # 2026-01-02 是週五：行事曆掛掉時退回只跳週末 → 前一「平日」是 2026-01-01
    result = df.prev_trading_day(datetime(2026, 1, 2, tzinfo=tz))
    assert result.strftime("%Y-%m-%d") == "2026-01-01"


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


def test_fetch_watchlist_price_history_filters_nan_rows_together(monkeypatch):
    """
    迴歸測試：若 Close 在某一列是 NaN、Volume 在「另一列」是 NaN（不是同一列），
    分別過濾 closes/volumes 兩個 list 會讓兩者砍掉不同列，導致 closes[i] 跟
    volumes[i] 變成不同交易日的資料（位置錯位）。這裡驗證兩者是「同一列一起丟棄」，
    過濾後最後一筆仍然正確配對（收盤價 129.0 對應成交量 5000，而非被錯位污染）。
    """
    import scripts.data_fetchers as df
    import math
    import pandas as pd

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period, interval):
            n = 30
            closes = [100.0 + i for i in range(n)]
            volumes = [1000] * (n - 1) + [5000]
            closes[10] = math.nan     # Close 在第 10 列是 NaN
            volumes[20] = math.nan    # Volume 在第 20 列是 NaN（不同列）
            return pd.DataFrame(
                {"Close": closes, "Volume": volumes},
                index=pd.date_range("2026-06-01", periods=n, freq="D"),
            )

    monkeypatch.setattr(df.yf, "Ticker", FakeTicker)
    result = df.fetch_watchlist_price_history([("2330.TW", "2330")])

    row = result["2330"]
    # 30 列中有 2 列（index 10、20）任一欄位是 NaN，應整列一起丟棄，剩 28 列
    assert len(row["closes"]) == 28
    assert len(row["volumes"]) == 28
    # 最後一列（原始 index 29）未被丟棄，兩個 list 仍應對齊同一天：收盤價 129.0 配成交量 5000
    assert row["closes"][-1] == 129.0
    assert row["volumes"][-1] == 5000
