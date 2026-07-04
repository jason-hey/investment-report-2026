"""
台股當日選股訊號評分：固定精選 ~65 檔台股，計算 8 項統計上有領先性的訊號，
組成「今日觀察清單」綜合評分表；並持久化每日入選清單，供隔天算「昨日選股回顧」勝率。

刻意不掃描全市場——理由：控制 yfinance/TWSE 呼叫量與執行時間、避免不穩定
（見 docs/superpowers/specs/2026-07-03-report-architecture-and-features-design.md 的 C 節）。
"""

# 精選 ~65 檔台股，涵蓋：台積電供應鏈、AI 伺服器、蘋果概念、記憶體、金融。
# (yfinance 代號, 顯示代號, 顯示名稱)
TW_STOCK_WATCHLIST = [
    # 台積電供應鏈 / 晶圓代工
    ("2330.TW", "2330", "台積電"), ("2303.TW", "2303", "聯電"), ("5347.TW", "5347", "世界先進"),
    ("3711.TW", "3711", "日月光投控"), ("6770.TW", "6770", "力積電"),
    # IC 設計
    ("2454.TW", "2454", "聯發科"), ("3034.TW", "3034", "聯詠"), ("3443.TW", "3443", "創意"),
    ("3529.TW", "3529", "力旺"), ("6533.TW", "6533", "晶心科"), ("2379.TW", "2379", "瑞昱"),
    ("3661.TW", "3661", "世芯-KY"), ("6415.TW", "6415", "矽力-KY"), ("8046.TW", "8046", "南電"),
    # AI 伺服器 / 系統組裝
    ("2382.TW", "2382", "廣達"), ("2357.TW", "2357", "華碩"), ("3231.TW", "3231", "緯創"),
    ("6669.TW", "6669", "緯穎"), ("2356.TW", "2356", "英業達"), ("4938.TW", "4938", "和碩"),
    ("2377.TW", "2377", "微星"), ("2376.TW", "2376", "技嘉"),
    # 散熱 / 機殼 / 電源
    ("3017.TW", "3017", "奇鋐"), ("3324.TW", "3324", "雙鴻"), ("2308.TW", "2308", "台達電"),
    ("6409.TW", "6409", "旭隼"), ("2421.TW", "2421", "建準"),
    # PCB / 網通
    ("3037.TW", "3037", "欣興"), ("2313.TW", "2313", "華通"), ("2383.TW", "2383", "台光電"),
    ("6274.TW", "6274", "台燿"), ("2412.TW", "2412", "中華電"),
    # 蘋果概念
    ("2317.TW", "2317", "鴻海"), ("3008.TW", "3008", "大立光"), ("2354.TW", "2354", "鴻準"),
    ("6805.TW", "6805", "富世達"), ("2327.TW", "2327", "國巨"), ("3406.TW", "3406", "玉晶光"),
    # 記憶體
    ("2408.TW", "2408", "南亞科"), ("3006.TW", "3006", "晶豪科"), ("8299.TW", "8299", "群聯"),
    ("2337.TW", "2337", "旺宏"), ("4967.TW", "4967", "十銓"),
    # 被動元件 / 其他半導體周邊
    ("2492.TW", "2492", "華新科"),
    # 金融
    ("2891.TW", "2891", "中信金"), ("2882.TW", "2882", "國泰金"), ("2881.TW", "2881", "富邦金"),
    ("2886.TW", "2886", "兆豐金"), ("2892.TW", "2892", "第一金"), ("2884.TW", "2884", "玉山金"),
    ("2887.TW", "2887", "台新金"), ("5880.TW", "5880", "合庫金"), ("2880.TW", "2880", "華南金"),
    ("2885.TW", "2885", "元大金"), ("2883.TW", "2883", "開發金"), ("2890.TW", "2890", "永豐金"),
    # 傳產權值 / ETF
    ("0050.TW", "0050", "元大台灣50"), ("1301.TW", "1301", "台塑"), ("1303.TW", "1303", "南亞"),
    ("2002.TW", "2002", "中鋼"), ("2603.TW", "2603", "長榮"), ("2609.TW", "2609", "陽明"),
    ("2615.TW", "2615", "萬海"), ("1216.TW", "1216", "統一"), ("2912.TW", "2912", "統一超"),
]

# 美股族群 → 台股供應鏈映射：對照 data_fetchers.US_HEATMAP_TICKERS 的代號，
# 每個美股 ticker 對應「當它今日大漲/大跌時，應該點亮的台股觀察名單」。
US_TO_TW_SUPPLY_CHAIN = {
    "NVDA": ["3231", "2382", "3017", "3324", "6669", "2356"],   # AI 伺服器族群
    "AVGO": ["3711", "2454"],                                     # ASIC / 網通
    "AAPL": ["2317", "3008", "2354", "6805", "2327"],            # 蘋果概念
    "MU":   ["2408", "3006", "8299", "2337"],                     # 記憶體
    "TSM":  ["2330", "2303", "5347"],                             # 晶圓代工（ADR 本身也對應）
    "AMD":  ["2382", "3231", "6770"],
    "QCOM": ["2454", "2379"],
}


# ── 8 項訊號計算：純函式，輸入為 data_fetchers 抓回來的 dict/list，不做任何網路呼叫 ──

def score_adr_signal(adr_data, threshold_pct=0.5):
    """ADR 溢價 > threshold_pct% 視為命中（隔天台股偏多的領先訊號）。"""
    hits = {}
    for adr_symbol, row in adr_data.items():
        code = row["tw_code"]
        hit = row["premium_pct"] > threshold_pct
        hits[code] = {"hit": hit, "detail": f"{adr_symbol} ADR 溢價 {row['premium_pct']:+.2f}%"}
    return hits


def score_us_supply_chain_signal(heatmap_data, threshold_pct=2.0):
    """美股族群當日漲幅 > threshold_pct% 時，點亮 US_TO_TW_SUPPLY_CHAIN 映射的台股。"""
    hits = {}
    heatmap_by_symbol = {item["symbol"]: item["change_pct"] for item in heatmap_data}
    for us_symbol, tw_codes in US_TO_TW_SUPPLY_CHAIN.items():
        change_pct = heatmap_by_symbol.get(us_symbol)
        if change_pct is None or change_pct <= threshold_pct:
            continue
        for code in tw_codes:
            hits[code] = {"hit": True, "detail": f"{us_symbol} {change_pct:+.2f}% 帶動"}
    return hits


def score_dual_buy_signal(institutional_data):
    """外資、投信同一天同步買超。"""
    hits = {}
    for code, row in institutional_data.items():
        if row["dual_buy"]:
            hits[code] = {"hit": True, "detail": "外資＋投信同步買超"}
    return hits


def score_buy_value_ratio_signal(institutional_data, threshold_pct=3.0):
    """買超金額（估算） ÷ 當日成交值 > threshold_pct% 視為命中。"""
    hits = {}
    for code, row in institutional_data.items():
        ratio = row.get("buy_value_ratio_pct")
        if ratio is not None and ratio > threshold_pct:
            hits[code] = {"hit": True, "detail": f"買超佔成交值 {ratio:.1f}%"}
    return hits


def score_short_squeeze_signal(margin_data, price_history, ratio_threshold_pct=30.0):
    """
    軋空候選：券資比（融券今日餘額/融資今日餘額）> threshold（預設 30%），
    **且**股價開始轉強（最近一筆收盤價 > 前一筆收盤價）——原始規劃文件明確要求
    這兩個條件同時成立才算軋空候選，只看券資比偏高但股價仍在下跌不算（那是
    「融券續抱」而非「即將軋空」的訊號，兩者意義不同，不能只看券資比就命中）。
    """
    hits = {}
    for code, row in margin_data.items():
        ratio = row["short_margin_ratio_pct"]
        if ratio <= ratio_threshold_pct:
            continue
        closes = price_history.get(code, {}).get("closes", [])
        if len(closes) < 2 or closes[-1] <= closes[-2]:
            continue
        hits[code] = {"hit": True, "detail": f"券資比 {ratio:.1f}% 且股價轉強"}
    return hits


def score_revenue_yoy_signal(revenue_data, yoy_threshold_pct=20.0):
    """月營收 YoY 成長 > threshold（預設 20%）視為命中。"""
    hits = {}
    for code, row in revenue_data.items():
        if row["yoy_change_pct"] > yoy_threshold_pct:
            hits[code] = {"hit": True, "detail": f"月營收 YoY {row['yoy_change_pct']:+.1f}%"}
    return hits


def score_breakout_signal(price_history, volume_multiplier=1.5):
    """收盤價創近 20 日新高，且當日成交量 > 近 5 日均量 * volume_multiplier。"""
    hits = {}
    for code, row in price_history.items():
        closes = row["closes"]
        volumes = row["volumes"]
        if len(closes) < 21 or len(volumes) < 6:
            continue
        today_close = closes[-1]
        prior_20 = closes[-21:-1]
        today_volume = volumes[-1]
        prior_5_avg_volume = sum(volumes[-6:-1]) / 5
        is_new_high = today_close > max(prior_20)
        is_volume_surge = prior_5_avg_volume > 0 and today_volume > prior_5_avg_volume * volume_multiplier
        if is_new_high and is_volume_surge:
            hits[code] = {"hit": True, "detail": "量價齊揚突破 20 日新高"}
    return hits


def score_rs_rank_signal(price_history, twii_return_pct, top_n=15):
    """近 20 日報酬率減去加權指數同期報酬率，取排名前 top_n 名視為命中。"""
    rs_scores = []
    for code, row in price_history.items():
        closes = row["closes"]
        if len(closes) < 21:
            continue
        stock_return_pct = (closes[-1] / closes[-21] - 1) * 100
        rs = stock_return_pct - twii_return_pct
        rs_scores.append((code, rs))
    rs_scores.sort(key=lambda x: x[1], reverse=True)
    hits = {}
    for code, rs in rs_scores[:top_n]:
        if rs > 0:
            hits[code] = {"hit": True, "detail": f"近 20 日相對大盤強度 +{rs:.1f}%"}
    return hits


def compute_signal_scores(signals, watchlist):
    """
    把 8 個 {code: {"hit": bool, "detail": str}} dict 合併成綜合評分表：
    每檔股票列出命中的訊號數（score）與命中的訊號名稱清單，依 score 由高到低排序，
    只保留 score >= 1 的股票（沒有命中任何訊號的不需要出現在報告裡）。
    """
    signal_order = ["adr", "us_supply_chain", "dual_buy", "buy_value_ratio",
                     "short_squeeze", "revenue_yoy", "breakout", "rs_rank"]
    code_to_name = {code: name for _, code, name in watchlist}

    scored = {}
    for signal_name in signal_order:
        for code, hit_info in signals.get(signal_name, {}).items():
            if not hit_info.get("hit"):
                continue
            entry = scored.setdefault(code, {"code": code, "name": code_to_name.get(code, code),
                                              "score": 0, "signals_hit": [], "details": []})
            entry["score"] += 1
            entry["signals_hit"].append(signal_name)
            entry["details"].append(hit_info["detail"])

    result = list(scored.values())
    result.sort(key=lambda x: x["score"], reverse=True)
    return result
