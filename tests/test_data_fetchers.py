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
