"""Jinja2 模板渲染：把預抓資料 + AI 敘述 JSON 組成模板變數，渲染出最終 HTML。"""
from jinja2 import Environment, FileSystemLoader

PE_COLORS = {"2330.TW": "#4f8ef7", "SPY": "#00d4ff", "NVDA": "#00e676", "LLY": "#ffa726"}


def _norm_zero(value):
    """把 -0.0 正規化成 0.0，避免格式化時印出誤導的負號（例如 '+-0'）。"""
    return 0.0 if value == 0 else value


def _fmt_price(value):
    """千分位 + 最多 2 位小數（去掉尾端多餘的 0 與小數點）。不能用 ':,g'——
    g 只有 6 位有效數字，加權指數 23,456.78 會被截成 '23,456.8'。"""
    s = f"{value:,.2f}"
    return s.rstrip("0").rstrip(".")


def _fmt_change(change, change_pct):
    change = _norm_zero(change)
    change_pct = _norm_zero(change_pct)
    sign = "+" if change >= 0 else ""
    return f"{sign}{_fmt_price(change)} ({sign}{change_pct:.2f}%)"


def _val_class(change):
    if change > 0:
        return "green"
    if change < 0:
        return "red"
    return ""


def _safe_css_token(value, allowed, default):
    """
    AI 回傳的 tone/status 字串會直接當 CSS class 插進模板；若 AI 打錯字或幻覺出
    不在允許清單內的值，用這個函式收斂成安全的預設值，避免樣式跑掉或殘留可疑字串。
    """
    return value if value in allowed else default


TONE_VALUES = {"green", "amber", "red", "blue"}
STATUS_VALUES = {"green", "amber", "red"}


def _sanitize_header_pills(header_pills):
    return [{**pill, "tone": _safe_css_token(pill.get("tone"), TONE_VALUES, "blue")} for pill in header_pills]


def _sanitize_institutional_summary(institutional_summary):
    return [
        {**item, "tone": _safe_css_token(item.get("tone"), {"green", "red"}, "")}
        for item in institutional_summary
    ]


def build_ticker_data(quotes):
    """把 fetch_quotes() 結果轉成 ticker 跑馬燈用的 list[dict]。"""
    order = ["TWII", "2330", "2317", "2454", "0050", "SPX", "NVDA", "AVGO",
             "LLY", "ORCL", "SMH", "IAUM", "VIX", "US10Y", "WTI"]
    items = []
    for key in order:
        q = quotes.get(key)
        if not q:
            continue
        change = _norm_zero(q["change"])
        change_pct = _norm_zero(q["change_pct"])
        items.append({
            "sym": q["name"],
            "price": _fmt_price(q["price"]),
            "chg": f'{"+" if change >= 0 else ""}{_fmt_price(change)}',
            "pct": f'{"+" if change_pct >= 0 else ""}{change_pct:.2f}%',
            "up": change >= 0,
        })
    return items


def build_kpi_cards(quotes):
    """固定 8 張卡片：加權指數/台積電/S&P500/WTI/聯發科/鴻海/IAUM/10Y殖利率。"""
    layout = [
        ("TWII", "台股加權指數"),
        ("2330", "台積電（2330）"),
        ("SPX", "S&P 500"),
        ("WTI", "原油（WTI）"),
        ("2454", "聯發科（2454）"),
        ("2317", "鴻海（2317）"),
        ("IAUM", "黃金（IAUM）"),
        ("US10Y", "10Y 美債殖利率"),
    ]
    cards = []
    for key, label in layout:
        q = quotes.get(key)
        if not q:
            cards.append({"label": label, "val": "N/A", "val_class": "",
                          "change_class": "", "change_text": "資料缺失", "extra": None})
            continue
        cards.append({
            "label": label,
            "val": _fmt_price(q["price"]),
            "val_class": _val_class(q["change"]),
            "change_class": _val_class(q["change"]),
            "change_text": _fmt_change(q["change"], q["change_pct"]),
            "extra": None,
        })
    return cards


def build_vix_history(fear_data):
    """fear_data 來自 data_fetchers.fetch_all_fear_index()，取 us.history。"""
    return fear_data.get("us", {}).get("history", [])


def build_pe_data(pe_data):
    """把 data_fetchers.fetch_all_pe_data() 的輸出加上圖表顏色，其餘欄位原樣保留。"""
    result = {}
    for market, items in pe_data.items():
        result[market] = []
        for item in items:
            result[market].append({**item, "color": PE_COLORS.get(item["symbol"], "#c8d0ec")})
    return result


def _fmt_institutional_row(row):
    """幫每一筆法人排行資料加上模板要顯示的字串：金額換算億元、張數加正負號與千分位。"""
    amount = row.get("est_amount_ntd")
    lots = _norm_zero(row["lots_3d"])
    return {
        **row,
        "amount_display": f"{amount / 100_000_000:,.2f}" if amount is not None else "—",
        "lots_display": f"{lots:+,.1f}",
    }


def build_institutional_context(institutional_data):
    """institutional_data 為 None 時（假日等原因預抓失敗）回傳空排行，模板顯示 0 筆。"""
    if not institutional_data:
        return {"as_of_dates": [], "foreign_buy_top10": [], "foreign_sell_top10": [],
                "trust_buy_top10": [], "trust_sell_top10": []}
    return {
        **institutional_data,
        "foreign_buy_top10": [_fmt_institutional_row(r) for r in institutional_data["foreign_buy_top10"]],
        "foreign_sell_top10": [_fmt_institutional_row(r) for r in institutional_data["foreign_sell_top10"]],
        "trust_buy_top10": [_fmt_institutional_row(r) for r in institutional_data["trust_buy_top10"]],
        "trust_sell_top10": [_fmt_institutional_row(r) for r in institutional_data["trust_sell_top10"]],
    }


def build_earnings_context(earnings_list):
    return earnings_list  # 已是 list[dict]，欄位與模板需要的一致，不需轉換


def build_korea_context(korea_data):
    """korea_data 來自 data_fetchers.fetch_korea_market()，原樣傳遞；None 或空 dict（尚未串接
    資料源時的預設值、或全部標的抓取失敗時 fetch_korea_market() 本身回傳的 {}）正規化成空 dict，
    讓模板端只需要 korea.get(key) 判斷，不需要額外檢查 korea 本身是否為 None
    （比照 build_institutional_context() 的既有正規化慣例）。"""
    return korea_data or {}


def _heatmap_color_class(change_pct):
    """依漲跌 % 分 5 級著色，門檻對稱：±0.5% 與 ±2.5%。"""
    if change_pct >= 2.5:
        return "heat-strong-up"
    if change_pct >= 0.5:
        return "heat-up"
    if change_pct <= -2.5:
        return "heat-strong-down"
    if change_pct <= -0.5:
        return "heat-down"
    return "heat-flat"


def build_heatmap_context(heatmap_data):
    """幫每檔股票加上依漲跌 % 決定的 CSS 著色class。"""
    return [{**item, "color_class": _heatmap_color_class(item["change_pct"])} for item in heatmap_data]


def build_sector_rotation_context(sector_data):
    """依當日漲跌% 由高到低排序，資金輪動表格由強到弱呈現。"""
    return sorted(sector_data, key=lambda item: item["change_pct_1d"], reverse=True)


def build_oil_context(oil_data):
    """
    oil_data 來自 data_fetchers.fetch_oil_prices()。除了原樣保留 wti/brent 兩個子 dict
    （None 正規化成 wti/brent 皆為空歷史的骨架，比照 build_institutional_context() 慣例），
    另外算出以「日期聯集」對齊的 dates/wti_values/brent_values 三個陣列，供圖表直接使用。

    WTI 與 Brent 是分開呼叫 yfinance 抓的（兩個獨立網路請求），兩個交易所的休市日曆也不完全
    相同，兩條歷史資料的長度或日期範圍可能不一致。若圖表直接各自把兩條歷史轉成陣列、共用同一組
    以「WTI 陣列位置」為準的 X 軸標籤，只要中間有一天只有其中一個標的缺資料，Brent 的資料點就會
    相對 WTI 系統性地錯位一格，且錯位是視覺上看不出來的（不會出現缺口，只是後面全部對錯位置）。
    改成先算出兩者日期的聯集、依日期排序、缺資料的日期用 None 補（Chart.js 對 null 值的處理是
    "這個點不畫、其餘正常"，不會造成錯位），從根本解決對齊問題。
    """
    if not oil_data:
        oil_data = {"wti": {"symbol": None, "name": "WTI 原油", "history": []},
                    "brent": {"symbol": None, "name": "Brent 原油", "history": []}}
    wti_history = oil_data.get("wti", {}).get("history") or []
    brent_history = oil_data.get("brent", {}).get("history") or []
    wti_by_date = {row["date"]: row["value"] for row in wti_history}
    brent_by_date = {row["date"]: row["value"] for row in brent_history}
    dates = sorted(set(wti_by_date) | set(brent_by_date))
    return {
        **oil_data,
        "dates": dates,
        "wti_values": [wti_by_date.get(d) for d in dates],
        "brent_values": [brent_by_date.get(d) for d in dates],
    }


def build_signal_scoring_context(scored_list, ai_reasons, win_rate_review):
    """
    把 signal_scoring.compute_signal_scores() 的結果、AI 寫的一句話原因、
    以及勝率回顧，合併成模板要用的 context。

    AI 敘述優先級最高；若 ai_reasons 中找不到某檔股票的原因，退回到
    Python 在 details 清單中生成的訊號說明，用「、」連接多個訊號
    （避免顯示空白原因，因為 compute_signal_scores() 保證 score >= 1
    意味著至少有一個訊號命中、details 不會是空清單）。

    ai_reasons 來自 AI 生成的 JSON（stock_signal_reasons 欄位），跟本檔案其他
    context builder 的輸入（Python 算好的 fetcher 資料）不同，屬於不可信來源
    ——validate_narrative_json() 只檢查頂層欄位是否存在，不檢查陣列內每個項目的
    形狀。比照本檔案既有的 _sanitize_* 系列慣例（處理 AI 幻覺/缺欄位輸出），
    用 .get() 而非直接索引，缺 "code" 的項目直接跳過，ai_reasons 本身是 None
    時正規化成空清單，避免一筆格式錯誤的 AI 輸出讓整份報告產生失敗。也額外防
    AI 把某一筆寫成非 dict（例如直接輸出一個字串而不是 {"code":..., "reason":...}）
    ——這種項目對 .get() 會拋 AttributeError，同樣直接跳過而不是整批失敗。
    """
    ai_reasons = ai_reasons or []
    reason_by_code = {
        item["code"]: item.get("reason")
        for item in ai_reasons
        if isinstance(item, dict) and item.get("code")
    }
    picks = []
    for entry in scored_list:
        reason = reason_by_code.get(entry["code"]) or "、".join(entry["details"])
        picks.append({
            "code": entry["code"],
            "name": entry["name"],
            "score": entry["score"],
            "signals_hit": entry["signals_hit"],
            "reason": reason,
        })
    return {"picks": picks, "win_rate_review": win_rate_review}


def _to_chart_number(value):
    """把 AI 可能輸出的數字型態（int/float/含千分位逗號的字串）收斂成真正的數字；
    無法轉換（None、非數字字串、bool）回傳 None，由呼叫端決定丟棄。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        num = float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    return int(num) if num.is_integer() else num


def _sanitize_lly_foundayo(lly):
    """
    lly_foundayo 來自 AI 生成的 JSON（不可信來源）；validate_narrative_json() 只保證
    它是 dict，不保證內部形狀。模板對 weekly_trx/wow_pct 有三種會炸的存取方式：
    `| tojson`（Undefined 直接 TypeError）、`"{:,}".format(trx)`（字串 ValueError）、
    `pct >= 0`（字串 TypeError）。比照本檔案既有 _sanitize_* 慣例：缺席的圖表欄位
    補成空清單、字串數字（如 "1,390"）轉成真正的數字、非 dict 或轉不了數字的項目
    直接丟棄，不讓一筆格式錯誤的 AI 輸出害整份報告產生失敗。
    """
    def clean_series(items, value_key):
        cleaned = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            num = _to_chart_number(item.get(value_key))
            if num is None:
                continue
            cleaned.append({**item, value_key: num})
        return cleaned

    return {
        **lly,
        "weekly_trx": clean_series(lly.get("weekly_trx"), "trx"),
        "wow_pct": clean_series(lly.get("wow_pct"), "pct"),
    }


def _sanitize_warning_indicators(warning_indicators):
    return {
        key: {**item, "status": _safe_css_token(item.get("status"), STATUS_VALUES, "amber")}
        for key, item in warning_indicators.items()
    }


def _sanitize_hero_events(hero_events):
    return [{**hero, "theme": _safe_css_token(hero.get("theme"), STATUS_VALUES, "amber")} for hero in hero_events]


def _default_signal_scoring_context():
    """
    signal_scoring_context 尚未提供時（Task 13 尚未把 generate_report.py 接上）的預設
    空殼。直接呼叫 build_signal_scoring_context() 用空輸入產生，而不是在這裡手刻第二份
    「空 signal scoring 長什麼樣子」的定義——避免兩處日後對 build_signal_scoring_context()
    的回傳形狀改動時不同步（比照 build_korea_context()/build_oil_context() 用函式產生
    正規化預設值的慣例，而非直接寫死字典字面值）。

    win_rate_review 的 checked_date 用 None，代表「完全還沒算過任何一天」；這跟
    compute_win_rate_review()（scripts/signal_scoring.py）在「有算過、但那天入選
    0 檔」情境下回傳 checked_date=實際日期字串是不同語意，兩者不要混用。
    """
    return build_signal_scoring_context(
        scored_list=[],
        ai_reasons=[],
        win_rate_review={"checked_date": None, "total_picks": 0, "up_count": 0,
                          "win_rate_pct": None, "picks_detail": []},
    )


def build_template_context(*, date_label, weekday_cn, tw_holiday_note,
                            quotes, fear_data, pe_data, institutional_data,
                            earnings_list, narrative_json,
                            korea_data=None, heatmap_data=(), sector_rotation_data=(), oil_data=None,
                            signal_scoring_context=None):
    """把所有預抓資料 + AI 敘述 JSON 組成 render_report() 需要的完整 context dict。

    korea_data/heatmap_data/sector_rotation_data/oil_data 4 個新參數給預設值
    （而非必填），因為 scripts/generate_report.py 尚未在 Task 8 把對應的抓取函式接進
    呼叫端——維持預設值可讓既有呼叫端（含 tests/conftest.py 匯入 generate_report.py
    時真的會執行到的那個呼叫）在新增資料源正式接上前，仍照舊正常運作。

    signal_scoring_context 同理給預設值 None（而非 Task 12 計畫文件裡寫的必填參數）：
    Task 13（把 compute_signal_scores() 真正接進 generate_report.py、並傳入實際的
    signal_scoring_context）還沒做，是下一個獨立任務。若這裡把參數設成必填，
    generate_report.py 現有那個尚未更新的呼叫（一被 import 就會執行，包括
    tests/conftest.py 的 autouse fixture）會立刻丟 TypeError，讓整個測試套件全部
    掛掉。None 會正規化成 _default_signal_scoring_context() 產生的同形狀空殼
    （picks: [] / win_rate_review 全部欄位歸零），讓模板讀取
    signal_scoring.picks、signal_scoring.win_rate_review.total_picks 時永遠拿到
    一致的形狀，而不是 None。
    """
    signal_scoring = signal_scoring_context if signal_scoring_context is not None else _default_signal_scoring_context()
    return {
        "date_label": date_label,
        "weekday_cn": weekday_cn,
        "tw_holiday_note": tw_holiday_note,
        "quotes": quotes,
        "ticker_data": build_ticker_data(quotes),
        "kpi_cards": build_kpi_cards(quotes),
        "vix_history": build_vix_history(fear_data),
        "pe_data": build_pe_data(pe_data),
        "institutional": build_institutional_context(institutional_data),
        "earnings": build_earnings_context(earnings_list),
        "korea": build_korea_context(korea_data),
        "heatmap": build_heatmap_context(heatmap_data),
        "sector_rotation": build_sector_rotation_context(sector_rotation_data),
        "oil": build_oil_context(oil_data),
        "header_pills": _sanitize_header_pills(narrative_json["header_pills"]),
        "data_validation": narrative_json["data_validation"],
        "hero_events": _sanitize_hero_events(narrative_json["hero_events"]),
        "warning_indicators": _sanitize_warning_indicators(narrative_json["warning_indicators"]),
        "night_session": narrative_json["night_session"],
        "institutional_summary": _sanitize_institutional_summary(narrative_json["institutional_summary"]),
        "news": narrative_json["news"],
        "ai_infra_html": narrative_json["ai_infra_html"],
        "theme_cards": narrative_json["theme_cards"],
        "strategy_cards": narrative_json["strategy_cards"],
        "risk_matrix_rows": narrative_json["risk_matrix_rows"],
        "market_deep_dive_html": narrative_json["market_deep_dive_html"],
        "lly_foundayo": _sanitize_lly_foundayo(narrative_json["lly_foundayo"]),
        "signal_scoring": signal_scoring,
    }


def render_report(context):
    """
    用 templates/report.html.j2 渲染最終 HTML 字串。

    autoescape=True：narrative_json 裡大部分欄位（新聞摘要、主題卡片、風險矩陣等）是
    AI 從 web_search 結果整理出來的敘述文字，屬於不可信輸入——若网頁本身被搜尋到的內容
    帶有惡意標籤，AI 逐字引用時可能把它原樣寫進 JSON 欄位。開啟 autoescape 讓所有
    `{{ }}` 輸出預設做 HTML escape，只有明確標記 `| safe` 的 3 個欄位
    （ai_infra_html、lly_foundayo.extra_html、market_deep_dive_html——這 3 個是
    JSON_OUTPUT_SPEC 裡唯一設計成「AI 直接輸出 HTML 片段」的欄位）才繞過escape，
    符合原本的信任範圍設計，而不是讓全部欄位都不做escape。
    """
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    template = env.get_template("report.html.j2")
    return template.render(**context)
