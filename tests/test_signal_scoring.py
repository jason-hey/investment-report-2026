def test_tw_stock_watchlist_has_no_duplicate_codes():
    from scripts.signal_scoring import TW_STOCK_WATCHLIST

    codes = [code for _, code, _ in TW_STOCK_WATCHLIST]
    assert len(codes) == len(set(codes))


def test_us_to_tw_supply_chain_only_references_watchlist_codes():
    from scripts.signal_scoring import TW_STOCK_WATCHLIST, US_TO_TW_SUPPLY_CHAIN

    watchlist_codes = {code for _, code, _ in TW_STOCK_WATCHLIST}
    for us_symbol, tw_codes in US_TO_TW_SUPPLY_CHAIN.items():
        for code in tw_codes:
            assert code in watchlist_codes, f"{us_symbol} 映射到不在清單裡的 {code}"


def test_score_adr_signal_hits_when_premium_above_threshold():
    from scripts.signal_scoring import score_adr_signal

    adr_data = {"TSM": {"tw_code": "2330", "premium_pct": 1.5}}
    hits = score_adr_signal(adr_data)
    assert hits["2330"]["hit"] is True
    assert "1.5" in hits["2330"]["detail"] or "1.50" in hits["2330"]["detail"]


def test_score_adr_signal_misses_when_premium_below_threshold():
    from scripts.signal_scoring import score_adr_signal

    adr_data = {"UMC": {"tw_code": "2303", "premium_pct": 0.1}}
    hits = score_adr_signal(adr_data)
    assert hits["2303"]["hit"] is False


def test_score_us_supply_chain_signal_lights_up_mapped_codes():
    from scripts.signal_scoring import score_us_supply_chain_signal

    heatmap_data = [{"symbol": "NVDA", "change_pct": 4.5}, {"symbol": "AAPL", "change_pct": -0.1}]
    hits = score_us_supply_chain_signal(heatmap_data)
    assert hits.get("3231", {}).get("hit") is True
    assert "2317" not in hits or hits["2317"]["hit"] is False


def test_score_us_supply_chain_signal_ignores_below_threshold():
    from scripts.signal_scoring import score_us_supply_chain_signal

    heatmap_data = [{"symbol": "NVDA", "change_pct": 1.0}]
    hits = score_us_supply_chain_signal(heatmap_data)
    assert "3231" not in hits


def test_score_us_supply_chain_signal_combines_details_when_multiple_drivers_hit_same_code():
    """
    迴歸測試：3231（緯創）同時被 NVDA 跟 AMD 映射到。若兩者當日漲幅都超過門檻，
    detail 應該把兩個觸發來源都列出來，而不是後面處理的 AMD 蓋掉前面的 NVDA。
    """
    from scripts.signal_scoring import score_us_supply_chain_signal

    heatmap_data = [{"symbol": "NVDA", "change_pct": 5.0}, {"symbol": "AMD", "change_pct": 3.0}]
    hits = score_us_supply_chain_signal(heatmap_data)
    assert hits["3231"]["hit"] is True
    assert "NVDA" in hits["3231"]["detail"]
    assert "AMD" in hits["3231"]["detail"]


def test_score_dual_buy_signal_hits_when_both_foreign_and_trust_buy():
    from scripts.signal_scoring import score_dual_buy_signal

    institutional_data = {
        "2330": {"dual_buy": True},
        "2317": {"dual_buy": False},
    }
    hits = score_dual_buy_signal(institutional_data)
    assert hits["2330"]["hit"] is True
    assert "2317" not in hits


def test_score_buy_value_ratio_signal_hits_above_threshold():
    from scripts.signal_scoring import score_buy_value_ratio_signal

    institutional_data = {
        "2330": {"buy_value_ratio_pct": 5.0},
        "2317": {"buy_value_ratio_pct": 1.0},
        "3231": {"buy_value_ratio_pct": None},
    }
    hits = score_buy_value_ratio_signal(institutional_data)
    assert hits["2330"]["hit"] is True
    assert "2317" not in hits
    assert "3231" not in hits


def test_score_short_squeeze_signal_requires_both_high_ratio_and_price_uptick():
    from scripts.signal_scoring import score_short_squeeze_signal

    margin_data = {
        "2330": {"short_margin_ratio_pct": 35.0},
        "2317": {"short_margin_ratio_pct": 35.0},
    }
    price_history = {
        "2330": {"closes": [100.0, 102.0]},
        "2317": {"closes": [100.0, 98.0]},
    }
    hits = score_short_squeeze_signal(margin_data, price_history)
    assert hits.get("2330", {}).get("hit") is True
    assert "2317" not in hits or hits["2317"]["hit"] is False


def test_score_short_squeeze_signal_misses_when_ratio_below_threshold():
    from scripts.signal_scoring import score_short_squeeze_signal

    margin_data = {"2330": {"short_margin_ratio_pct": 10.0}}
    price_history = {"2330": {"closes": [100.0, 102.0]}}
    hits = score_short_squeeze_signal(margin_data, price_history)
    assert "2330" not in hits


def test_score_revenue_yoy_signal_hits_above_threshold():
    from scripts.signal_scoring import score_revenue_yoy_signal

    revenue_data = {
        "2330": {"yoy_change_pct": 30.0},
        "2317": {"yoy_change_pct": 5.0},
    }
    hits = score_revenue_yoy_signal(revenue_data)
    assert hits["2330"]["hit"] is True
    assert "2317" not in hits


def test_score_breakout_signal_detects_20d_high_with_volume_surge():
    from scripts.signal_scoring import score_breakout_signal

    closes = [100.0] * 29 + [110.0]
    volumes = [1000.0] * 24 + [1000.0] * 5 + [3000.0]
    price_history = {"2330": {"closes": closes, "volumes": volumes[:30]}}
    hits = score_breakout_signal(price_history)
    assert hits["2330"]["hit"] is True


def test_score_breakout_signal_misses_without_volume_surge():
    from scripts.signal_scoring import score_breakout_signal

    closes = [100.0] * 29 + [110.0]
    volumes = [1000.0] * 30
    price_history = {"2330": {"closes": closes, "volumes": volumes}}
    hits = score_breakout_signal(price_history)
    assert "2330" not in hits


def test_score_rs_rank_signal_hits_top_relative_strength():
    from scripts.signal_scoring import score_rs_rank_signal

    strong_closes = [100.0] * 20 + [130.0]
    weak_closes = [100.0] * 20 + [95.0]
    price_history = {
        "2330": {"closes": strong_closes},
        "2317": {"closes": weak_closes},
    }
    hits = score_rs_rank_signal(price_history, twii_return_pct=0.0, top_n=1)
    assert hits.get("2330", {}).get("hit") is True
    assert "2317" not in hits


def test_score_rs_rank_signal_skips_zero_close_without_crashing():
    """
    迴歸測試：closes[-21] 若為 0（例如停牌股或資料異常）會讓報酬率計算除以零。
    這裡驗證該檔股票被跳過而不是讓整個函式拋出例外（會讓每日報告產生流程中斷）。
    """
    from scripts.signal_scoring import score_rs_rank_signal

    price_history = {
        "BAD": {"closes": [0.0] * 20 + [5.0]},
        "2330": {"closes": [100.0] * 20 + [130.0]},
    }
    hits = score_rs_rank_signal(price_history, twii_return_pct=0.0, top_n=15)
    assert "BAD" not in hits
    assert hits.get("2330", {}).get("hit") is True


def test_compute_signal_scores_ranks_by_total_hits_desc():
    from scripts.signal_scoring import compute_signal_scores, TW_STOCK_WATCHLIST

    fake_signals = {
        "adr": {},
        "us_supply_chain": {"2330": {"hit": True, "detail": "NVDA +5%"}},
        "dual_buy": {"2330": {"hit": True, "detail": "外資投信同步買超"}},
        "buy_value_ratio": {},
        "short_squeeze": {},
        "revenue_yoy": {},
        "breakout": {},
        "rs_rank": {},
    }
    scores = compute_signal_scores(fake_signals, TW_STOCK_WATCHLIST)
    assert scores[0]["code"] == "2330"
    assert scores[0]["score"] == 2


def test_compute_signal_scores_excludes_zero_hit_stocks():
    from scripts.signal_scoring import compute_signal_scores, TW_STOCK_WATCHLIST

    fake_signals = {
        "adr": {}, "us_supply_chain": {}, "dual_buy": {}, "buy_value_ratio": {},
        "short_squeeze": {}, "revenue_yoy": {}, "breakout": {}, "rs_rank": {},
    }
    scores = compute_signal_scores(fake_signals, TW_STOCK_WATCHLIST)
    assert scores == []
