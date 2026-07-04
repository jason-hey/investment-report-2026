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


def _fake_narrative_json():
    """符合 REQUIRED_JSON_FIELDS 的最小假資料（見 scripts/generate_report.py 的 JSON_OUTPUT_SPEC），
    用來驗證完整 context 能渲染出通過 validate_html() 的 HTML。"""
    return {
        "daily_brief": "大盤上漲收復失土\n重大新聞為台積電法說優於預期\n持倉留意升息預期升溫",
        "header_pills": [
            {"icon": "🦅", "text": "測試重點一", "tone": "green"},
            {"icon": "⚡", "text": "測試重點二", "tone": "amber"},
            {"icon": "📈", "text": "測試重點三", "tone": "green"},
            {"icon": "🤖", "text": "測試重點四", "tone": "blue"},
        ],
        "data_validation": [
            {"status": "confirmed", "label": "測試已確認項目"},
            {"status": "estimated", "label": "測試估計項目"},
        ],
        "hero_events": [
            {"flag": "🇺🇸", "label": "今日重大事件 #1 — 測試事件一", "theme": "green",
             "headline": "測試標題一：美股創高", "body": "測試內文一：詳細敘述美股表現"},
            {"flag": "🇹🇼", "label": "今日重大事件 #2 — 測試事件二", "theme": "amber",
             "headline": "測試標題二：台股翻紅", "body": "測試內文二：詳細敘述台股表現"},
        ],
        "warning_indicators": {
            "vix": {"status": "green", "note": "VIX 判讀說明"},
            "hy_spread": {"status": "green", "value_text": "~290 bp", "note": "利差判讀說明"},
            "us10y": {"status": "amber", "note": "殖利率判讀說明"},
            "ai_leaders": {"status": "amber", "note": "AI 龍頭線型判讀說明"},
            "tw_leverage": {"status": "amber", "value_text": "6,110 億", "note": "融資餘額判讀說明"},
        },
        "night_session": {"price": "46,880", "change_pts": "+136", "change_pct": "+0.29%",
                           "volume": "12,345", "vs_day_close_note": "夜盤升水測試備註",
                           "source_note": "資料來源測試備註"},
        "institutional_summary": [
            {"label": "外資", "text": "買超 +測試億", "tone": "green", "emphasize": False},
            {"label": "投信", "text": "買超 +測試億", "tone": "green", "emphasize": False},
            {"label": "自營商", "text": "買超 +測試億", "tone": "green", "emphasize": False},
            {"label": "三大合計", "text": "+測試億", "tone": "green", "emphasize": True},
        ],
        "news": {
            "ai_semi": [{"title": "AI半導體測試新聞標題", "summary": "測試摘要內容",
                         "source": "TestSource", "date": "2026-07-03"}],
            "macro": [{"title": "總經測試新聞標題", "summary": "測試摘要內容",
                       "source": "TestSource", "date": "2026-07-03"}],
            "geo": [{"title": "地緣測試新聞標題", "summary": "測試摘要內容",
                     "source": "TestSource", "date": "2026-07-03"}],
            "ipo": [{"title": "IPO測試新聞標題", "summary": "測試摘要內容",
                     "source": "TestSource", "date": "2026-07-03"}],
        },
        "theme_cards": [
            {"icon": "🤖", "title": "測試主題一", "body": "測試說明一", "tickers": ["NVDA"]},
            {"icon": "🏭", "title": "測試主題二", "body": "測試說明二", "tickers": ["2330"]},
            {"icon": "💊", "title": "測試主題三", "body": "測試說明三", "tickers": ["LLY"]},
            {"icon": "🏗️", "title": "測試主題四", "body": "測試說明四", "tickers": ["ORCL"]},
            {"icon": "🥇", "title": "測試主題五", "body": "測試說明五", "tickers": ["IAUM"]},
        ],
        "strategy_cards": [
            {"name": "🔬 巴菲特框架 — 測試", "quote": "測試名言一", "points": ["測試觀點1", "測試觀點2"]},
            {"name": "📈 動能策略 — 測試", "quote": "測試名言二", "points": ["測試觀點1", "測試觀點2"]},
            {"name": "🛡️ 防禦配置 — 測試", "quote": "測試名言三", "points": ["測試觀點1", "測試觀點2"]},
        ],
        "risk_matrix_rows": [
            {"risk": "測試風險項目", "likelihood": "高", "impact": "中", "mitigation": "測試因應方式"},
        ],
        "ai_infra_html": '<div class="infra-test">AI 基礎建設驗證指標測試內容片段</div>',
        "market_deep_dive_html": '<div class="deep-dive-test">三地市場深度分析測試內容片段</div>',
        "lly_foundayo": {
            "weekly_trx": [{"week": "W1", "trx": 1390}, {"week": "W2", "trx": 3200}],
            "wow_pct": [{"week": "W2", "pct": 130.2}],
            "commentary": "LLY Foundayo 測試敘述內容",
            "stage_note": "",
            "extra_html": '<div class="lly-extra-test">LLY 額外資訊測試內容片段</div>',
        },
    }


def _narrative_context_fields():
    """_fake_narrative_json() 扣掉 daily_brief（該欄位不進模板 context，只給通知用）。"""
    data = _fake_narrative_json()
    data.pop("daily_brief")
    return data


def test_render_report_produces_html_with_ticker_and_kpi_data():
    from scripts.report_render import render_report, build_korea_context, build_oil_context

    quotes = {"TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": 274.0, "change_pct": 0.59}}
    context = {
        "date_label": "2026.07.03", "weekday_cn": "週五", "tw_holiday_note": "",
        "quotes": quotes,
        "ticker_data": [{"sym": "加權指數", "price": "46,744", "chg": "+274", "pct": "+0.59%", "up": True}],
        "kpi_cards": [{"label": "台股加權指數", "val": "46,744", "val_class": "green",
                        "change_class": "green", "change_text": "+274 (+0.59%)", "extra": None}] * 8,
        "vix_history": [{"date": "2026-07-01", "value": 16.5}],
        "pe_data": {"tw": [], "us": []},
        "institutional": {"as_of_dates": [], "foreign_buy_top10": [], "foreign_sell_top10": [],
                           "trust_buy_top10": [], "trust_sell_top10": []},
        "earnings": [],
        "korea": build_korea_context(None),
        "heatmap": [],
        "sector_rotation": [],
        "oil": build_oil_context(None),
        **_narrative_context_fields(),
    }
    html = render_report(context)
    assert "46,744" in html
    assert "</html>" in html.lower()


def test_render_report_renders_institutional_table_rows():
    from scripts.report_render import render_report, build_institutional_context, build_korea_context, build_oil_context

    institutional = build_institutional_context({
        "as_of_dates": ["2026-07-01", "2026-07-02", "2026-07-03"],
        "foreign_buy_top10": [{"code": "2330", "name": "台積電", "lots_3d": 29100.0, "est_amount_ntd": 6985000000}],
        "foreign_sell_top10": [{"code": "2317", "name": "鴻海", "lots_3d": -39700.0, "est_amount_ntd": 950000000}],
        "trust_buy_top10": [], "trust_sell_top10": [],
    })
    context = {
        "date_label": "2026.07.03", "weekday_cn": "週五", "tw_holiday_note": "",
        "quotes": {},
        "ticker_data": [], "kpi_cards": [{"label": "x", "val": "1", "val_class": "",
                          "change_class": "", "change_text": "+0 (+0.00%)", "extra": None}] * 8,
        "vix_history": [], "pe_data": {"tw": [], "us": []},
        "institutional": institutional, "earnings": [],
        "korea": build_korea_context(None),
        "heatmap": [],
        "sector_rotation": [],
        "oil": build_oil_context(None),
        **_narrative_context_fields(),
    }
    html = render_report(context)
    assert "69.85" in html
    assert "+29,100.0" in html
    assert "9.50" in html
    assert "-39,700.0" in html
    assert "2026-07-03" in html  # as_of_dates 顯示最新一筆


def test_build_template_context_and_render_produces_valid_html():
    from scripts.report_render import build_template_context, render_report

    quotes = {"TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": 274.0, "change_pct": 0.59},
              "VIX": {"symbol": "^VIX", "name": "VIX", "price": 16.15, "change": 0.23, "change_pct": 1.45},
              "US10Y": {"symbol": "^TNX", "name": "10Y美債殖利率", "price": 4.48, "change": 0.02, "change_pct": 0.45}}
    narrative = _fake_narrative_json()
    context = build_template_context(
        date_label="2026.07.03", weekday_cn="週五", tw_holiday_note="",
        quotes=quotes,
        fear_data={"us": {"symbol": "^VIX", "name": "VIX", "history": [{"date": "2026-07-01", "value": 16.5}]}},
        pe_data={"tw": [], "us": []},
        institutional_data=None,
        earnings_list=[{"date": "2026-07-10", "symbol": "NVDA", "name": "NVIDIA", "market": "美股"}],
        narrative_json=narrative,
        korea_data={"KOSPI": {"symbol": "^KS11", "name": "KOSPI 指數", "price": 3100.0, "change": 25.0, "change_pct": 0.81}},
        heatmap_data=[{"symbol": "AAPL", "change_pct": 1.5}],
        sector_rotation_data=[{"symbol": "XLK", "name": "科技", "change_pct_1d": 1.2, "change_pct_1w": 3.0}],
        oil_data={"wti": {"symbol": "CL=F", "name": "WTI 原油", "history": [{"date": "2026-07-01", "value": 68.5}]},
                  "brent": {"symbol": "BZ=F", "name": "Brent 原油", "history": [{"date": "2026-07-01", "value": 72.0}]}},
    )
    context["signal_scoring"] = {
        "picks": [{"code": "2330", "name": "台積電", "score": 2, "signals_hit": ["adr"], "reason": "測試理由"}],
        "win_rate_review": {"checked_date": "2026-07-02", "total_picks": 1, "up_count": 1,
                             "win_rate_pct": 100.0, "picks_detail": []},
    }
    html = render_report(context)

    from scripts.generate_report import validate_html
    assert validate_html(html) == []

    # 沒有殘留未渲染的 Jinja 標記
    assert "{{" not in html
    assert "{%" not in html

    # 抽查幾個敘述 JSON 裡的獨特字串確實出現在輸出中
    assert "測試標題一：美股創高" in html
    assert "VIX 判讀說明" in html
    assert "夜盤升水測試備註" in html
    assert "AI半導體測試新聞標題" in html
    assert "測試主題一" in html
    assert "巴菲特框架 — 測試" in html
    assert "測試風險項目" in html
    assert "三地市場深度分析測試內容片段" in html
    assert "LLY Foundayo 測試敘述內容" in html
    assert "NVIDIA" in html  # earnings_list 透過 build_earnings_context 傳入

    # Task 8 事後補齊的 5 個欄位（header_pills/data_validation/ai_infra_html/
    # lly_foundayo.extra_html/institutional_summary）也要確認實際出現在輸出中，
    # 不能只靠 validate_html() 這種粗略檢查（那不會抓到迴圈變數名稱打錯字）
    assert "測試重點一" in html
    assert "測試已確認項目" in html
    assert "infra-test" in html
    assert "lly-extra-test" in html
    assert "買超 +測試億" in html

    # Task 7 新增的 4 個區塊（韓國股市/美股熱力圖/資金板塊輪動/油價走勢）
    assert "KOSPI 指數" in html
    assert "AAPL" in html

    # Task 11 新增的今日觀察清單評分表 + 昨日選股回顧區塊
    assert "測試理由" in html
    assert "命中率" in html


def test_render_report_signal_scoring_no_history_shows_fallback_note():
    from scripts.report_render import build_template_context, render_report

    quotes = {"TWII": {"symbol": "^TWII", "name": "加權指數", "price": 46744.0, "change": 274.0, "change_pct": 0.59},
              "VIX": {"symbol": "^VIX", "name": "VIX", "price": 16.15, "change": 0.23, "change_pct": 1.45},
              "US10Y": {"symbol": "^TNX", "name": "10Y美債殖利率", "price": 4.48, "change": 0.02, "change_pct": 0.45}}
    narrative = _fake_narrative_json()
    context = build_template_context(
        date_label="2026.07.03", weekday_cn="週五", tw_holiday_note="",
        quotes=quotes,
        fear_data={"us": {"symbol": "^VIX", "name": "VIX", "history": [{"date": "2026-07-01", "value": 16.5}]}},
        pe_data={"tw": [], "us": []},
        institutional_data=None,
        earnings_list=[{"date": "2026-07-10", "symbol": "NVDA", "name": "NVIDIA", "market": "美股"}],
        narrative_json=narrative,
        korea_data={"KOSPI": {"symbol": "^KS11", "name": "KOSPI 指數", "price": 3100.0, "change": 25.0, "change_pct": 0.81}},
        heatmap_data=[{"symbol": "AAPL", "change_pct": 1.5}],
        sector_rotation_data=[{"symbol": "XLK", "name": "科技", "change_pct_1d": 1.2, "change_pct_1w": 3.0}],
        oil_data={"wti": {"symbol": "CL=F", "name": "WTI 原油", "history": [{"date": "2026-07-01", "value": 68.5}]},
                  "brent": {"symbol": "BZ=F", "name": "Brent 原油", "history": [{"date": "2026-07-01", "value": 72.0}]}},
    )
    context["signal_scoring"] = {
        "picks": [],
        "win_rate_review": {"checked_date": "", "total_picks": 0, "up_count": 0,
                             "win_rate_pct": 0.0, "picks_detail": []},
    }
    html = render_report(context)

    from scripts.generate_report import validate_html
    assert validate_html(html) == []
    assert "尚無歷史入選紀錄" in html
    assert "XLK" in html
    assert "68.5" in html


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


def test_build_template_context_sanitizes_unrecognized_tone_and_status_values():
    from scripts.report_render import build_template_context

    narrative = _fake_narrative_json()
    narrative.pop("daily_brief")
    narrative["header_pills"][0]["tone"] = "purple-typo"
    narrative["institutional_summary"][0]["tone"] = "not-a-color"
    narrative["warning_indicators"]["vix"]["status"] = "SUPER_BULLISH"
    narrative["hero_events"][0]["theme"] = "rainbow"

    context = build_template_context(
        date_label="2026.07.03", weekday_cn="週五", tw_holiday_note="",
        quotes={}, fear_data={}, pe_data={"tw": [], "us": []}, institutional_data=None,
        earnings_list=[], narrative_json=narrative,
    )

    assert context["header_pills"][0]["tone"] == "blue"
    assert context["institutional_summary"][0]["tone"] == ""
    assert context["warning_indicators"]["vix"]["status"] == "amber"
    assert context["hero_events"][0]["theme"] == "amber"


def test_build_institutional_context_handles_none():
    from scripts.report_render import build_institutional_context

    result = build_institutional_context(None)
    assert result["foreign_buy_top10"] == []
    assert result["as_of_dates"] == []


def test_build_institutional_context_adds_display_fields():
    from scripts.report_render import build_institutional_context

    data = {"as_of_dates": ["2026-07-01"], "foreign_buy_top10": [{"code": "2330", "name": "台積電",
             "lots_3d": 29100.0, "est_amount_ntd": 6985000000}],
             "foreign_sell_top10": [{"code": "2317", "name": "鴻海",
             "lots_3d": -39700.0, "est_amount_ntd": 950000000}],
             "trust_buy_top10": [], "trust_sell_top10": []}
    result = build_institutional_context(data)
    buy_row = result["foreign_buy_top10"][0]
    sell_row = result["foreign_sell_top10"][0]
    assert buy_row["amount_display"] == "69.85"
    assert buy_row["lots_display"] == "+29,100.0"
    assert sell_row["amount_display"] == "9.50"
    assert sell_row["lots_display"] == "-39,700.0"
    # 原始欄位仍保留，模板其他地方（如 code/name）還會用到
    assert buy_row["code"] == "2330"


def test_build_institutional_context_missing_amount_shows_dash():
    from scripts.report_render import build_institutional_context

    data = {"as_of_dates": [], "foreign_buy_top10": [{"code": "2330", "name": "台積電",
             "lots_3d": 100.0, "est_amount_ntd": None}],
             "foreign_sell_top10": [], "trust_buy_top10": [], "trust_sell_top10": []}
    assert build_institutional_context(data)["foreign_buy_top10"][0]["amount_display"] == "—"


def test_build_institutional_context_normalizes_negative_zero_lots():
    from scripts.report_render import build_institutional_context

    data = {"as_of_dates": [], "foreign_buy_top10": [{"code": "2330", "name": "台積電",
             "lots_3d": -0.0, "est_amount_ntd": 100000000}],
             "foreign_sell_top10": [], "trust_buy_top10": [], "trust_sell_top10": []}
    assert build_institutional_context(data)["foreign_buy_top10"][0]["lots_display"] == "+0.0"


def test_build_earnings_context_passes_through_list():
    from scripts.report_render import build_earnings_context

    earnings = [{"date": "2026-07-08", "symbol": "LLY", "name": "Eli Lilly", "market": "美股"}]
    assert build_earnings_context(earnings) == earnings


def test_build_korea_context_passes_through_data():
    from scripts.report_render import build_korea_context

    data = {"KOSPI": {"symbol": "^KS11", "name": "KOSPI 指數", "price": 3100.0, "change": 25.0, "change_pct": 0.81}}
    assert build_korea_context(data) == data


def test_build_korea_context_normalizes_none_to_empty_dict():
    """generate_report.py 尚未串接 fetch_korea_market() 前，korea_data 預設值是 None；
    模板端用 korea.get(key) 判斷，None.get(...) 會直接拋 UndefinedError，所以要正規化成 {}。"""
    from scripts.report_render import build_korea_context

    assert build_korea_context(None) == {}
    assert build_korea_context({}) == {}


def test_build_heatmap_context_adds_color_class():
    from scripts.report_render import build_heatmap_context

    data = [
        {"symbol": "AAPL", "change_pct": 3.5},
        {"symbol": "TSLA", "change_pct": -2.1},
        {"symbol": "MSFT", "change_pct": 0.05},
    ]
    result = build_heatmap_context(data)
    by_symbol = {item["symbol"]: item for item in result}
    assert by_symbol["AAPL"]["color_class"] == "heat-strong-up"
    assert by_symbol["TSLA"]["color_class"] == "heat-down"
    assert by_symbol["MSFT"]["color_class"] == "heat-flat"


def test_heatmap_color_class_boundary_values():
    """鎖定 5 級著色的 4 個門檻邊界（±0.5% / ±2.5%），避免日後 > 跟 >= 打錯字沒被抓到。"""
    from scripts.report_render import _heatmap_color_class

    assert _heatmap_color_class(2.5) == "heat-strong-up"
    assert _heatmap_color_class(0.5) == "heat-up"
    assert _heatmap_color_class(-0.5) == "heat-down"
    assert _heatmap_color_class(-2.5) == "heat-strong-down"


def test_build_sector_rotation_context_sorts_by_1d_change_desc():
    from scripts.report_render import build_sector_rotation_context

    data = [
        {"symbol": "XLE", "name": "能源", "change_pct_1d": -1.2, "change_pct_1w": 2.0},
        {"symbol": "XLK", "name": "科技", "change_pct_1d": 2.5, "change_pct_1w": 5.0},
    ]
    result = build_sector_rotation_context(data)
    assert [item["symbol"] for item in result] == ["XLK", "XLE"]


def test_build_oil_context_passes_through_and_builds_aligned_arrays():
    from scripts.report_render import build_oil_context

    data = {"wti": {"symbol": "CL=F", "name": "WTI 原油", "history": [{"date": "2026-07-01", "value": 68.5}]},
            "brent": {"symbol": "BZ=F", "name": "Brent 原油", "history": []}}
    result = build_oil_context(data)
    assert result["wti"] == data["wti"]
    assert result["brent"] == data["brent"]
    assert result["dates"] == ["2026-07-01"]
    assert result["wti_values"] == [68.5]
    assert result["brent_values"] == [None]


def test_build_oil_context_normalizes_none_to_empty_history():
    """generate_report.py 尚未串接 fetch_oil_prices() 前，oil_data 預設值是 None。"""
    from scripts.report_render import build_oil_context

    result = build_oil_context(None)
    assert result["wti"]["history"] == []
    assert result["brent"]["history"] == []
    assert result["dates"] == []
    assert result["wti_values"] == []
    assert result["brent_values"] == []


def test_build_oil_context_aligns_mismatched_wti_brent_dates():
    """
    迴歸測試：WTI 與 Brent 是分開抓的，某一天可能只有其中一個標的有資料
    （不同交易所假日曆不同）。若圖表直接各自把兩條歷史轉成陣列、共用同一組以
    「陣列位置」為準的 X 軸標籤，中間缺一天資料就會讓其中一條線後面全部對錯位置。
    這裡驗證：用日期聯集對齊後，各自缺資料的日期要精確地對應到 None，而不是
    被另一條線的資料填補、造成錯位。
    """
    from scripts.report_render import build_oil_context

    data = {
        "wti": {"symbol": "CL=F", "name": "WTI 原油", "history": [
            {"date": "2026-07-01", "value": 68.0},
            {"date": "2026-07-02", "value": 69.0},
            {"date": "2026-07-03", "value": 70.0},
        ]},
        "brent": {"symbol": "BZ=F", "name": "Brent 原油", "history": [
            {"date": "2026-07-01", "value": 72.0},
            # 2026-07-02 該標的缺資料（例如假日曆不同）
            {"date": "2026-07-03", "value": 74.0},
        ]},
    }
    result = build_oil_context(data)

    assert result["dates"] == ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert result["wti_values"] == [68.0, 69.0, 70.0]
    # Brent 在 07-02 缺資料，必須是 None（不是 68.0/69.0 這種被 WTI 值污染的結果，
    # 也不能整條線往前/往後平移）
    assert result["brent_values"] == [72.0, None, 74.0]


def test_build_signal_scoring_context_merges_scores_with_ai_reasons():
    from scripts.report_render import build_signal_scoring_context

    scored_list = [{"code": "2330", "name": "台積電", "score": 2,
                    "signals_hit": ["adr", "dual_buy"], "details": ["ADR 溢價 +1.5%", "外資投信同步買超"]}]
    ai_reasons = [{"code": "2330", "reason": "ADR 溢價偏高且外資投信同步買超"}]
    win_rate_review = {"checked_date": "2026-07-02", "total_picks": 5, "up_count": 3,
                        "win_rate_pct": 60.0, "picks_detail": []}

    context = build_signal_scoring_context(scored_list, ai_reasons, win_rate_review)

    assert context["picks"][0]["code"] == "2330"
    assert context["picks"][0]["reason"] == "ADR 溢價偏高且外資投信同步買超"
    assert context["win_rate_review"]["win_rate_pct"] == 60.0


def test_build_signal_scoring_context_falls_back_to_details_when_no_ai_reason():
    from scripts.report_render import build_signal_scoring_context

    scored_list = [{"code": "2330", "name": "台積電", "score": 1,
                    "signals_hit": ["adr"], "details": ["ADR 溢價 +1.5%"]}]
    context = build_signal_scoring_context(scored_list, ai_reasons=[], win_rate_review={
        "checked_date": "2026-07-02", "total_picks": 0, "up_count": 0, "win_rate_pct": None, "picks_detail": []
    })
    # AI 沒有給這檔股票寫原因時，退回顯示 Python 算好的 details 合併字串，不要顯示空白
    assert context["picks"][0]["reason"] == "ADR 溢價 +1.5%"


def test_build_signal_scoring_context_skips_malformed_ai_reason_entry():
    """
    迴歸測試：ai_reasons 是 AI 生成的 JSON（不可信來源），若某筆缺 "code"
    （AI 幻覺/漏欄位），不應該讓整個函式 KeyError，只是那筆被忽略，其餘
    股票仍正常退回 details 合併字串。
    """
    from scripts.report_render import build_signal_scoring_context

    scored_list = [{"code": "2330", "name": "台積電", "score": 1,
                    "signals_hit": ["adr"], "details": ["ADR 溢價 +1.5%"]}]
    ai_reasons = [{"reason": "缺 code 的壞資料"}]  # 沒有 "code"
    context = build_signal_scoring_context(scored_list, ai_reasons, win_rate_review={
        "checked_date": "2026-07-02", "total_picks": 0, "up_count": 0, "win_rate_pct": None, "picks_detail": []
    })
    assert context["picks"][0]["reason"] == "ADR 溢價 +1.5%"


def test_build_signal_scoring_context_treats_none_ai_reasons_as_empty():
    """迴歸測試：AI 若把 stock_signal_reasons 輸出成 null 而非 []，不應該讓函式 TypeError。"""
    from scripts.report_render import build_signal_scoring_context

    scored_list = [{"code": "2330", "name": "台積電", "score": 1,
                    "signals_hit": ["adr"], "details": ["ADR 溢價 +1.5%"]}]
    context = build_signal_scoring_context(scored_list, ai_reasons=None, win_rate_review={
        "checked_date": "2026-07-02", "total_picks": 0, "up_count": 0, "win_rate_pct": None, "picks_detail": []
    })
    assert context["picks"][0]["reason"] == "ADR 溢價 +1.5%"


def test_build_signal_scoring_context_handles_empty_scored_list():
    from scripts.report_render import build_signal_scoring_context

    context = build_signal_scoring_context([], ai_reasons=[], win_rate_review={
        "checked_date": "2026-07-02", "total_picks": 0, "up_count": 0, "win_rate_pct": None, "picks_detail": []
    })
    assert context["picks"] == []
