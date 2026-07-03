"""
Daily Investment Report Generator
每天自動呼叫 Claude API + web_search（伺服器端工具），生成 HTML 報告並備份舊報告
使用串流模式（SDK 要求：max_tokens 較大時必須用 streaming，避免長時間請求被中斷）
"""
import anthropic
import json
import os
import re
import shutil
from datetime import datetime, timezone, timedelta

from scripts.data_fetchers import (
    is_prev_us_day_holiday,
    is_prev_tw_day_holiday,
    fetch_earnings_calendar,
    format_earnings_for_prompt,
    fetch_all_pe_data,
    fetch_institutional_3day_ranking,
    load_market_analysis_prompt,
    fetch_all_fear_index,
)

# AI 敘述 JSON 的必要欄位（見 JSON_OUTPUT_SPEC）；Task 9 的 render_report() 依賴這些欄位齊全。
REQUIRED_JSON_FIELDS = [
    "daily_brief", "header_pills", "data_validation", "hero_events",
    "warning_indicators", "night_session", "news", "ai_infra_html",
    "theme_cards", "strategy_cards", "risk_matrix_rows",
    "market_deep_dive_html", "lly_foundayo",
]

TZ_TW = timezone(timedelta(hours=8))
today = datetime.now(TZ_TW)

if os.environ.get("DATE_OVERRIDE"):
    today = datetime.strptime(os.environ["DATE_OVERRIDE"], "%Y-%m-%d").replace(tzinfo=TZ_TW)

date_str   = today.strftime("%Y-%m-%d")
date_label = today.strftime("%Y.%m.%d")
weekday_cn = ["週一","週二","週三","週四","週五","週六","週日"][today.weekday()]

print(f"[{date_str}] 檢查今日是否已發布...")
if os.path.exists(f"Backup/{date_str}.html"):
    print(f"  今日報告已存在（Backup/{date_str}.html），跳過本次生成（一天只發布一次）。")
    exit(0)

print(f"[{date_str}] 檢查美股假日...")
if is_prev_us_day_holiday(today):
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    print(f"  前一美股交易日 {prev.strftime('%Y-%m-%d')} 為假日，跳過本次報告生成。")
    exit(0)

print(f"[{date_str}] 檢查台股假日...")
tw_holiday_note = ""
if is_prev_tw_day_holiday(today):
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    print(f"  前一台股交易日 {prev.strftime('%Y-%m-%d')} 為假日（休市/國定假日），台股數據將標註為最近交易日資料。")
    tw_holiday_note = (
        "\n【重要】今日台股休市（國定假日或連假）。所有台股相關數字（台積電、鴻海、聯發科、0050、加權指數等）"
        "請明確標註為「最近一個交易日」資料，勿當作今日即時數字呈現。\n"
    )

print("  正在用 yfinance 抓取未來 2 週財報日曆...")
earnings_data = fetch_earnings_calendar(today)
earnings_table = format_earnings_for_prompt(earnings_data)
print(f"  財報日曆：找到 {len(earnings_data)} 筆")

print("  正在用 yfinance 抓取本益比趨勢（1Y / 3Y）...")
pe_data = fetch_all_pe_data()
pe_json = json.dumps(pe_data, ensure_ascii=False)

print("  正在用 yfinance 抓取恐懼指數（近 6 個月）...")
fear_data = fetch_all_fear_index()
fear_json = json.dumps(fear_data, ensure_ascii=False)

print("  正在用 TWSE OpenAPI 抓取法人連三日買賣超排行...")
institutional_data = fetch_institutional_3day_ranking(today)
institutional_json = json.dumps(institutional_data, ensure_ascii=False) if institutional_data else None

print("  正在讀取三地市場深度分析 prompt...")
market_analysis_prompt = load_market_analysis_prompt(date_str, weekday_cn)

if institutional_json:
    institutional_prefetch_block = f"""
## 【已預先抓取】法人連三日買賣超排行（直接用於圖表，勿再搜尋，勿自行編造股號或數字）
以下 JSON 來自 TWSE OpenAPI 三大法人買賣超日報，已計算連續 3 個交易日同向買賣超個股：

{institutional_json}

欄位說明：as_of_dates = 計算所用的 3 個交易日；lots_3d = 3 日合計買賣超張數（正=買超，負=賣超）；
est_amount_ntd = 用最新收盤價估算的金額（新台幣元，非逐日精確金額，屬估算值，null 表示無收盤價可估算）。
"""
    institutional_task_line = (
        "3. 台股三大法人動向：搜尋外資/投信/自營商「整體」買賣超金額（連三日個股排行已預先抓取，不需再搜尋，"
        "直接使用上方 JSON，勿自行編造股號或金額）"
    )
else:
    institutional_prefetch_block = ""
    institutional_task_line = """3. 台股三大法人動向：外資/投信/自營商整體買賣超金額；並分別搜尋「連三日同向買賣超排行」：
   - 外資連三日買超前 10 名個股（股號、股名、三日買超金額、三日買超張數）
   - 外資連三日賣超前 10 名個股（股號、股名、三日賣超金額、三日賣超張數）
   - 投信連三日買超前 10 名個股（股號、股名、三日買超金額、三日買超張數）
   - 投信連三日賣超前 10 名個股（股號、股名、三日賣超金額、三日賣超張數）
   （資料來源建議：CMoney、goodinfo.tw、twse.com.tw、anue.com、moneyDJ）"""

JSON_OUTPUT_SPEC = """
## 輸出格式（重要：只輸出 JSON，不要輸出 HTML）
根據上方已提供的數字資料與你完成的搜尋任務，輸出一份 JSON（用 ```json ... ``` 包裹），結構如下：

{
  "daily_brief": "3 行、每行純文字不加符號，總長度 150 字以內：第一行大盤漲跌重點；第二行今日最重要新聞或事件；第三行對持倉組合最需要注意的一點。3 行用 \\n 分隔存成同一個字串。",
  "header_pills": [
    {"icon": "🦅", "text": "<一句話重點1>", "tone": "green 或 amber 或 red 或 blue"}
  ],
  "data_validation": [
    {"status": "confirmed 或 estimated", "label": "<資料項目與來源，例如「台股收盤（TWSE 官方）」>"}
  ],
  "hero_events": [
    {"flag": "🇺🇸", "label": "今日重大事件 #1 — <一句話標題>", "theme": "green 或 amber 或 red",
     "headline": "<完整標題句>", "body": "<完整段落敘述，含資料來源標註>"},
    {"flag": "🇹🇼", "label": "今日重大事件 #2 — <一句話標題>", "theme": "green 或 amber 或 red",
     "headline": "<完整標題句>", "body": "<完整段落敘述，含資料來源標註>"}
  ],
  "warning_indicators": {
    "vix": {"status": "green/amber/red", "note": "<一句話判讀，VIX 數值已由系統提供，不需重複列出>"},
    "hy_spread": {"status": "green/amber/red", "value_text": "<搜尋到的 HY 利差數值文字>", "note": "<一句話判讀>"},
    "us10y": {"status": "green/amber/red", "note": "<一句話判讀，10Y 殖利率數值已由系統提供>"},
    "ai_leaders": {"status": "green/amber/red", "note": "<AI 龍頭股線型判讀，如 NVDA/AVGO 近期走勢>"},
    "tw_leverage": {"status": "green/amber/red", "value_text": "<搜尋到的台股融資餘額數值文字>", "note": "<一句話判讀>"}
  },
  "night_session": {"price": "<夜盤最新價>", "change_pts": "<漲跌點數>", "change_pct": "<漲跌%>",
                     "volume": "<成交量>", "vs_day_close_note": "<與日盤收盤比較的一句話>",
                     "source_note": "<資料來源與時間>"},
  "news": {
    "ai_semi": [{"title": "...", "summary": "...", "source": "...", "date": "YYYY-MM-DD"}],
    "macro": [{"title": "...", "summary": "...", "source": "...", "date": "YYYY-MM-DD"}],
    "geo": [{"title": "...", "summary": "...", "source": "...", "date": "YYYY-MM-DD"}],
    "ipo": [{"title": "...", "summary": "...", "source": "...", "date": "YYYY-MM-DD"}]
  },
  "ai_infra_html": "<使用搜尋任務 10 的三項數據（CSP capex YoY、AI 伺服器出貨量、HBM 合約價與現貨價利差），直接輸出「AI 基礎建設驗證指標」這個區塊的 HTML 片段（3 格並排卡片，不含外層 <html>/<body>），沿用你過去產出這個區塊時的既有格式規則>",
  "theme_cards": [
    {"icon": "🤖", "title": "<主題名稱>", "body": "<兩三句話說明>", "tickers": ["NVDA", "AVGO"]}
  ],
  "strategy_cards": [
    {"name": "🔬 巴菲特框架 — 安全邊際", "quote": "<一句名言>", "points": ["<觀點1>", "<觀點2>", "<觀點3>"]}
  ],
  "risk_matrix_rows": [
    {"risk": "<風險名稱>", "likelihood": "高/中/低", "impact": "高/中/低", "mitigation": "<因應方式>"}
  ],
  "market_deep_dive_html": "<完整執行下方三地市場深度分析規格後，直接輸出這個區塊的 HTML 片段（不含外層 <html>/<body>，只要這個區塊本身的 div 結構），沿用你過去產出這個區塊時的既有格式規則（信心等級標籤、洗盤vs出貨表格等）>",
  "lly_foundayo": {"weekly_trx": [{"week": "W1", "trx": 1390}], "wow_pct": [{"week": "W2", "pct": 12.3}],
                    "commentary": "<敘述>", "stage_note": "<若無 TRx 數據時的商業化階段說明>",
                    "extra_html": "<商業化階段 / 分析師全年預估 / 與 NVO 競品對比 3 格卡片 + Medicare 覆蓋里程碑說明的 HTML 片段，沿用你過去產出這個區塊時的既有格式規則>"}
}

上面是結構範例，不是要照抄的內容；實際筆數規則如下（範例中只示範 1 筆）：
- header_pills 固定輸出 4 則，每則一句話重點（今日最值得注意的事實），對應頁首的重點提示列
- data_validation 列出今天報告中「已確認」與「估計值」的資料項目各幾筆均可，只要涵蓋當天實際用到的關鍵資料來源（台股/美股收盤、法人排行、夜盤等）
- news 的 ai_semi/macro/geo/ipo 各自視實際搜尋結果填入多筆，該分類若搜尋不到內容也要回傳空陣列 `[]`，不可省略欄位本身
- theme_cards 固定輸出 5 張，依序涵蓋：AI 算力基礎建設、台灣半導體供應鏈、口服 GLP-1、AI 電力/資料中心、黃金/實物資產
- strategy_cards 固定輸出 3 張，依序為：巴菲特框架、動能策略、防禦配置

嚴格遵守以下規則，避免輸出無法解析的 JSON：
- 只能輸出合法 JSON。不可包含 `/* */` 或 `//` 這類註解、不可有結尾多餘逗號
- 任何字串值裡如果本來就含有雙引號或換行（例如新聞標題、名言），必須依 JSON 規則轉義（`\\"`、`\\n`），不可直接貼原始文字
- 所有欄位都必須存在，不可省略欄位本身
- 不要輸出 JSON 以外的任何文字、不要用 Markdown 標題，直接輸出 ```json 區塊，且區塊結束後不要再輸出任何內容
"""

PROMPT = f"""
今天是 {date_label}（{weekday_cn}），台灣台中。
{tw_holiday_note}請為我生成一份完整的「每日投資情報 HTML 網頁」。

## 【已預先抓取】未來 2 週財報日曆（直接使用，勿再搜尋）
以下資料來自 Yahoo Finance API，請直接用於財報速覽區塊，不需要再搜尋財報日期：

{earnings_table}

## 【已預先抓取】本益比趨勢資料（直接用於圖表，勿再搜尋）
以下 JSON 包含台股與美股各標的的月度 P/E 歷史（1Y / 3Y），請直接用於本益比趨勢圖區塊：

{pe_json}

欄位說明：trailing_3y = 近 3 年月 Trailing P/E 歷史趨勢；trailing_1y = 近 1 年月資料；current_trailing_pe = 當前 Trailing P/E（TTM 實際 EPS）；current_forward_pe = 當前 Forward P/E（分析師預估未來 12 個月 EPS，null 表示無資料）。

## 【已預先抓取】美股 VIX 恐懼指數近 6 個月日資料（直接用於圖表，勿再搜尋）
{fear_json}

欄位說明：history = 每日 [{{"date":"YYYY-MM-DD","value":數值}}] 陣列。
{institutional_prefetch_block}
## 必須完成的搜尋任務（依序執行，至少 8 次搜尋）
1. 今日/昨日美股收盤：S&P 500、Nasdaq、Dow 漲跌幅與主要個股
2. 台股今日行情：加權指數、台積電（2330）、鴻海（2317）、聯發科（2454）
{institutional_task_line}
4. 今日最重要的 AI/半導體新聞（NVDA/TSMC/AVGO/MRVL）
5. 地緣政治：伊朗局勢最新進展、油價動態
6. 總體經濟：Fed 動態、美債殖利率、PCE/CPI 最新數據、CME FedWatch 降息機率
7. SpaceX SPCX 等重大 IPO 進度
8. 台指期夜盤最新走勢：當日夜盤開盤價、最新價、漲跌點數、成交量、與日盤收盤的差距
9. LLY Foundayo（orforglipron）週處方量（TRx）趨勢：
    - Foundayo 是 Eli Lilly orforglipron 的商品名，為口服 GLP-1 小分子藥物，與 Mounjaro/Zepbound（tirzepatide 注射劑）是完全不同的產品線，絕對不可混用或替代
    - 搜尋最近 8–12 週的 Foundayo / orforglipron 週處方量數據（來源：IQVIA、Symphony Health、投行研報、財經新聞）
    - 取得每週 TRx 絕對數量與週增長率（WoW%）
    - 若暫無處方量數據（如仍在商業化初期），搜尋 orforglipron 上市進度、處方量放量速度分析師預估或醫療通路鋪貨狀況，並在圖表區說明目前所處商業化階段
10. AI 基礎建設驗證指標（三項，每項均需搜尋最新數據）：
   - CSP capex 同比變化：Microsoft/Amazon/Google/Meta 最新季度雲端資本支出金額與 YoY 成長率
   - AI 伺服器出貨量月度趨勢：最新月份全球 AI 伺服器出貨量或出貨量預估（來源：TrendForce / IDC）
   - HBM 合約價與現貨價利差：最新 HBM3e 或 HBM3 合約價、現貨價，及兩者利差（來源：DRAMeXchange / TrendForce）

## 額外任務：三地市場深度分析（獨立完整執行，結果嵌入 HTML 新區塊）
除了上方任務外，請完整執行以下這份獨立的「每日三地市場分析」規格（含台股/美股/韓股搜尋、資料規則、信心等級標註 F/G/E/I/W、洗盤 vs 出貨七維度快檢），並將完整分析結果整理成 HTML 報告中的一個新區塊（區塊標題：「三地市場深度分析」）。此區塊需完整保留下方七大結構（核心結論、事件鏈、美股、韓股、台股、洗盤vs出貨七維度快檢表格、行動清單），並在區塊末尾附上「今日資料缺口」清單。以下為完整規格：

---
{market_analysis_prompt if market_analysis_prompt else "（找不到 doc/Prompt/daily_market_analysis_prompt.md，此區塊略過）"}
---

## 個人持倉背景
台積電(2330)、鴻海(2317)、聯發科(2454)、SMH、NVDA、AVGO、ORCL、LLY、0050、IAUM(黃金)

{JSON_OUTPUT_SPEC}
"""

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

print(f"[{date_str}] 開始生成報告...")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 64000
TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 16}]

messages = [{"role": "user", "content": PROMPT}]


def call_claude(messages):
    """用串流模式呼叫 API，回傳最終完整訊息物件"""
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=TOOLS,
        messages=messages
    ) as stream:
        for _ in stream.text_stream:
            pass
        return stream.get_final_message()


def extract_json_block(text):
    """
    從模型輸出的文字中萃取 ```json ... ``` 區塊並解析成 dict；失敗回傳 None。
    用貪婪匹配（非 *?）抓到文字中「最後一個」收尾 ```，而不是第一個——
    JSON 字串值內容（例如 market_deep_dive_html 或新聞內文）可能剛好包含
    ``` 字元，非貪婪匹配會在那裡提早截斷，導致明明是合法 JSON 卻解析失敗。
    """
    m = re.search(r"```json\s*([\s\S]*)```", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"  ⚠️ JSON 解析失敗: {e}")
        return None


def validate_narrative_json(data):
    """回傳缺少的必要欄位清單；空清單代表通過。"""
    if data is None:
        return REQUIRED_JSON_FIELDS  # 全部視為缺失
    return [field for field in REQUIRED_JSON_FIELDS if field not in data]


response = call_claude(messages)
narrative_json = None

for iteration in range(5):
    print(f"  迭代 {iteration+1}: stop_reason={response.stop_reason}")

    if response.stop_reason == "end_turn":
        for block in response.content:
            if hasattr(block, "text"):
                parsed = extract_json_block(block.text)
                if parsed:
                    narrative_json = parsed
        break

    elif response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        response = call_claude(messages)
        continue

    elif response.stop_reason == "max_tokens":
        print(f"  ⚠️ 達到 max_tokens 上限，嘗試從已產生內容中萃取 JSON...")
        for block in response.content:
            if hasattr(block, "text"):
                print(f"  已產生文字長度: {len(block.text)}")
                parsed = extract_json_block(block.text)
                if parsed:
                    narrative_json = parsed
        break

    else:
        print(f"  ⚠️ 非預期 stop_reason: {response.stop_reason}")
        for block in response.content:
            if hasattr(block, "text"):
                print(f"  已產生文字長度: {len(block.text)}")
        break

if not narrative_json:
    raise RuntimeError(f"未能從 Claude 取得 JSON 內容（最終 stop_reason={response.stop_reason}）")

missing_fields = validate_narrative_json(narrative_json)
if missing_fields:
    raise RuntimeError(
        f"AI 回傳 JSON 缺少必要欄位，中止發布：缺少 {missing_fields}；"
        f"實際收到的欄位：{sorted(narrative_json.keys())}"
    )
print("  ✅ AI 敘述 JSON 驗證通過")


def validate_html(html: str) -> list[str]:
    """回傳驗證失敗的原因清單；空清單代表通過。避免截斷或空洞的報告被發布上線。"""
    problems = []
    if len(html) < 20000:
        problems.append(f"內容過短（{len(html):,} bytes，預期 20,000+）")
    if "</html>" not in html.lower():
        problems.append("找不到 </html> 結尾標籤，內容可能被截斷")
    for required in ("<table", "<canvas", "<script"):
        if required not in html.lower():
            problems.append(f"找不到必要標籤 {required}")
    return problems


# TODO(Task 9): 呼叫 scripts.report_render.render_report(narrative_json, fetch_quotes(), ...)
# 產出完整 HTML後，比照舊版流程呼叫 validate_html()、寫入 index.html、備份到 Backup/{date_str}.html。
# 這裡先不寫檔，只從已驗證的 narrative_json 取出摘要供通知使用。

summary_text = (narrative_json.get("daily_brief") or "").strip()
if summary_text:
    print(f"  📋 摘要：{summary_text}")
else:
    print("  ⚠️ 未找到通知摘要（daily_brief 欄位為空），通知將只包含連結")

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a", encoding="utf-8") as f:
        f.write("summary<<REPORT_SUMMARY_EOF\n")
        f.write(summary_text + "\n")
        f.write("REPORT_SUMMARY_EOF\n")
