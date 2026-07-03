def test_build_ticker_data_formats_quotes():
    from scripts.report_render import build_ticker_data

    quotes = {
        "TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": 274.0, "change_pct": 0.59},
        "2330": {"symbol": "2330.TW", "name": "台積電", "price": 2400.0, "change": -5.0, "change_pct": -0.21},
    }
    result = {
        item["sym"]: item
        for item in __import__("scripts.report_render", fromlist=["build_ticker_data"]).build_ticker_data(quotes)
    }
    assert result["加權指數"]["up"] is True
    assert result["加權指數"]["pct"] == "+0.59%"
    assert result["台積電"]["up"] is False
    assert result["台積電"]["pct"] == "-0.21%"


def test_build_ticker_data_normalizes_negative_zero():
    from scripts.report_render import build_ticker_data

    quotes = {"VIX": {"symbol": "^VIX", "name": "VIX", "price": 16.15, "change": -0.0, "change_pct": -0.0}}
    result = build_ticker_data(quotes)[0]
    assert result["chg"] == "+0"
    assert result["pct"] == "+0.00%"
    assert result["up"] is True


def test_build_kpi_cards_marks_missing_quote_as_na():
    from scripts.report_render import build_kpi_cards

    cards = build_kpi_cards({})
    assert len(cards) == 8
    assert all(c["val"] == "N/A" for c in cards)


def test_build_kpi_cards_formats_present_quote():
    from scripts.report_render import build_kpi_cards

    quotes = {"TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": 274.0, "change_pct": 0.59}}
    card = build_kpi_cards(quotes)[0]
    assert card["label"] == "台股加權指數"
    assert card["val"] == "46,744"
    assert card["val_class"] == "green"
    assert card["change_text"] == "+274 (+0.59%)"


def test_build_kpi_cards_normalizes_negative_zero_change():
    from scripts.report_render import build_kpi_cards

    quotes = {"TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": -0.0, "change_pct": -0.0}}
    card = build_kpi_cards(quotes)[0]
    assert card["change_text"] == "+0 (+0.00%)"
    assert card["val_class"] == ""


def test_render_report_produces_html_with_ticker_and_kpi_data():
    from scripts.report_render import render_report

    context = {
        "date_label": "2026.07.03", "weekday_cn": "週五", "tw_holiday_note": "",
        "ticker_data": [{"sym": "加權指數", "price": "46,744", "chg": "+274", "pct": "+0.59%", "up": True}],
        "kpi_cards": [{"label": "台股加權指數", "val": "46,744", "val_class": "green",
                        "change_class": "green", "change_text": "+274 (+0.59%)", "extra": None}] * 8,
        "vix_history": [{"date": "2026-07-01", "value": 16.5}],
        "pe_data": {"tw": [], "us": []},
        "institutional": {"as_of_dates": [], "foreign_buy_top10": [], "foreign_sell_top10": [],
                           "trust_buy_top10": [], "trust_sell_top10": []},
        "earnings": [],
    }
    html = render_report(context)
    assert "46,744" in html
    assert "</html>" in html.lower()


def test_build_vix_history_extracts_us_history():
    from scripts.report_render import build_vix_history

    fear_data = {"us": {"symbol": "^VIX", "name": "美股 VIX 恐懼指數",
                        "history": [{"date": "2026-07-01", "value": 16.5}]}}
    assert build_vix_history(fear_data) == [{"date": "2026-07-01", "value": 16.5}]


def test_build_pe_data_adds_chart_color():
    from scripts.report_render import build_pe_data

    pe_data = {"tw": [{"symbol": "2330.TW", "name": "台積電", "trailing_3y": [],
                       "trailing_1y": [], "current_trailing_pe": 33.4, "current_forward_pe": 19.6}]}
    result = build_pe_data(pe_data)
    assert result["tw"][0]["color"] == "#4f8ef7"
    assert result["tw"][0]["current_trailing_pe"] == 33.4


def test_build_institutional_context_handles_none():
    from scripts.report_render import build_institutional_context

    result = build_institutional_context(None)
    assert result["foreign_buy_top10"] == []
    assert result["as_of_dates"] == []


def test_build_institutional_context_passes_through_data():
    from scripts.report_render import build_institutional_context

    data = {"as_of_dates": ["2026-07-01"], "foreign_buy_top10": [{"code": "2330", "name": "台積電",
             "lots_3d": 100.0, "est_amount_ntd": 24000000}],
             "foreign_sell_top10": [], "trust_buy_top10": [], "trust_sell_top10": []}
    assert build_institutional_context(data) == data


def test_build_earnings_context_passes_through_list():
    from scripts.report_render import build_earnings_context

    earnings = [{"date": "2026-07-08", "symbol": "LLY", "name": "Eli Lilly", "market": "美股"}]
    assert build_earnings_context(earnings) == earnings
