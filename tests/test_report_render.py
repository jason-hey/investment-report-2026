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


def test_build_kpi_cards_marks_missing_quote_as_na():
    from scripts.report_render import build_kpi_cards

    cards = build_kpi_cards({})
    assert len(cards) == 8
    assert all(c["val"] == "N/A" for c in cards)


def test_render_report_produces_html_with_ticker_and_kpi_data():
    from scripts.report_render import render_report

    context = {
        "date_label": "2026.07.03", "weekday_cn": "週五", "tw_holiday_note": "",
        "ticker_data": [{"sym": "加權指數", "price": "46,744", "chg": "+274", "pct": "+0.59%", "up": True}],
        "kpi_cards": [{"label": "台股加權指數", "val": "46,744", "val_class": "green",
                        "change_class": "green", "change_text": "+274 (+0.59%)", "extra": None}] * 8,
    }
    html = render_report(context)
    assert "46,744" in html
    assert "</html>" in html.lower()
