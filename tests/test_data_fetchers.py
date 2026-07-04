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
