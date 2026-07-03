def test_data_fetchers_module_importable():
    import scripts.data_fetchers as df
    assert callable(df.fetch_earnings_calendar)
    assert callable(df.fetch_all_pe_data)
    assert callable(df.fetch_institutional_3day_ranking)
    assert callable(df.fetch_all_fear_index)
    assert callable(df.is_prev_us_day_holiday)
    assert callable(df.is_prev_tw_day_holiday)
    assert callable(df.load_market_analysis_prompt)
