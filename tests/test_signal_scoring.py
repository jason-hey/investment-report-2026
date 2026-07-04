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


def test_load_signal_history_returns_empty_dict_when_file_missing(tmp_path):
    from scripts.signal_scoring import load_signal_history

    result = load_signal_history(str(tmp_path / "does_not_exist.json"))
    assert result == {}


def test_save_and_load_signal_history_roundtrip(tmp_path):
    from scripts.signal_scoring import save_signal_history, load_signal_history

    path = str(tmp_path / "history.json")
    data = {"2026-07-03": {"picks": [{"code": "2330", "score": 3}]}}
    save_signal_history(path, data)

    loaded = load_signal_history(path)
    assert loaded == data


def test_compute_win_rate_review_checks_yesterdays_picks_against_todays_price(monkeypatch):
    from scripts.signal_scoring import compute_win_rate_review

    history = {"2026-07-02": {"picks": [{"code": "2330", "name": "台積電", "score": 3}]}}
    quotes_like = {"2330": {"price": 510.0, "change": 10.0, "change_pct": 2.0}}

    review = compute_win_rate_review(history, "2026-07-02", quotes_like)
    assert review["checked_date"] == "2026-07-02"
    assert review["total_picks"] == 1
    assert review["up_count"] == 1
    assert round(review["win_rate_pct"], 1) == 100.0


def test_compute_win_rate_review_returns_zero_picks_when_date_not_in_history():
    """第一次執行、或前一交易日剛好沒有入選紀錄時，不應該拋例外，應回傳 total_picks=0。"""
    from scripts.signal_scoring import compute_win_rate_review

    review = compute_win_rate_review({}, "2026-07-02", {})
    assert review["checked_date"] == "2026-07-02"
    assert review["total_picks"] == 0
    assert review["up_count"] == 0
    assert review["win_rate_pct"] is None
    assert review["picks_detail"] == []


def test_compute_win_rate_review_skips_pick_missing_code():
    """
    迴歸測試：歷史檔是手動可編輯的 JSON，若某筆入選紀錄缺少 "code"（格式錯誤／
    合併衝突留下的壞資料），不應該讓整個回顧函式 KeyError 中斷，只跳過那一筆。
    """
    from scripts.signal_scoring import compute_win_rate_review

    history = {"2026-07-02": {"picks": [{"name": "缺代號的股票", "score": 1}]}}
    review = compute_win_rate_review(history, "2026-07-02", {})
    assert review["total_picks"] == 1
    assert review["up_count"] == 0
    assert review["picks_detail"] == []


def test_load_signal_history_treats_non_dict_json_as_empty(tmp_path):
    """迴歸測試：檔案是合法 JSON 但不是物件（例如 list）時，也應視為空歷史，而不是原樣回傳。"""
    from scripts.signal_scoring import load_signal_history
    import json as json_module

    path = str(tmp_path / "bad_shape.json")
    with open(path, "w", encoding="utf-8") as f:
        json_module.dump(["not", "a", "dict"], f)

    result = load_signal_history(path)
    assert result == {}


def test_load_signal_history_treats_corrupt_json_as_empty(tmp_path):
    from scripts.signal_scoring import load_signal_history

    path = str(tmp_path / "corrupt.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")

    result = load_signal_history(path)
    assert result == {}


def test_record_todays_picks_prunes_history_beyond_max_days():
    """
    迴歸測試：record_todays_picks() 的核心職責是防止 data/stock_signals_history.json
    無限成長。這裡驗證超過 max_history_days 時，最舊的紀錄會被砍掉，只留最新 N 筆。
    """
    from scripts.signal_scoring import record_todays_picks

    history = {f"2026-06-{d:02d}": {"picks": []} for d in range(1, 31)}  # 30 筆舊紀錄
    assert len(history) == 30

    scored_list = [{"code": "2330", "name": "台積電", "score": 1}]
    updated = record_todays_picks(history, "2026-07-01", scored_list, max_history_days=30)

    assert len(updated) == 30
    assert "2026-07-01" in updated  # 今天的紀錄有寫入
    assert "2026-06-01" not in updated  # 最舊的一筆被砍掉
    assert "2026-06-02" in updated  # 次舊的仍保留
