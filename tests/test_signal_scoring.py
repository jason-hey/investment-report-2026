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
