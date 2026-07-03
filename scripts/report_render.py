"""Jinja2 模板渲染：把預抓資料 + AI 敘述 JSON 組成模板變數，渲染出最終 HTML。"""
from jinja2 import Environment, FileSystemLoader

PE_COLORS = {"2330.TW": "#4f8ef7", "SPY": "#00d4ff", "NVDA": "#00e676", "LLY": "#ffa726"}


def _norm_zero(value):
    """把 -0.0 正規化成 0.0，避免 f'{value:g}' 印出誤導的負號（例如 '+-0'）。"""
    return 0.0 if value == 0 else value


def _fmt_change(change, change_pct):
    change = _norm_zero(change)
    change_pct = _norm_zero(change_pct)
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:g} ({sign}{change_pct:.2f}%)"


def _val_class(change):
    if change > 0:
        return "green"
    if change < 0:
        return "red"
    return ""


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
            "price": f'{q["price"]:,g}',
            "chg": f'{"+" if change >= 0 else ""}{change:g}',
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
            "val": f'{q["price"]:,g}',
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


def render_report(context):
    """用 templates/report.html.j2 渲染最終 HTML 字串。"""
    env = Environment(loader=FileSystemLoader("templates"), autoescape=False)
    template = env.get_template("report.html.j2")
    return template.render(**context)
