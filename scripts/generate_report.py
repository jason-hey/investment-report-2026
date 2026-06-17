"""
Daily Investment Report Generator
每天自動呼叫 Claude API + web_search（伺服器端工具），生成 HTML 報告並備份舊報告
"""
import anthropic
import os
import re
import shutil
from datetime import datetime, timezone, timedelta

TZ_TW = timezone(timedelta(hours=8))
today = datetime.now(TZ_TW)

if os.environ.get("DATE_OVERRIDE"):
    today = datetime.strptime(os.environ["DATE_OVERRIDE"], "%Y-%m-%d").replace(tzinfo=TZ_TW)

date_str   = today.strftime("%Y-%m-%d")
date_label = today.strftime("%Y.%m.%d")
weekday_cn = ["週一","週二","週三","週四","週五","週六","週日"][today.weekday()]

PROMPT = f"""
今天是 {date_label}（{weekday_cn}），台灣台中。
請為我生成一份完整的「每日投資情報 HTML 網頁」。

## 必須完成的搜尋任務（依序執行，至少 8 次搜尋）
1. 今日/昨日美股收盤：S&P 500、Nasdaq、Dow 漲跌幅與主要個股
2. 台股今日行情：加權指數、台積電（2330）、鴻海（2317）、聯發科（2454）
3. 台股三大法人動向：外資/投信/自營商買賣超
4. 今日最重要的 AI/半導體新聞（NVDA/TSMC/AVGO/MRVL）
5. 地緣政治：伊朗局勢最新進展、油價動態
6. 本週財報：今日 + 未來 7 天重要財報公司
7. 總體經濟：Fed 動態、美債殖利率、PCE/CPI 最新數據、CME FedWatch 降息機率
8. SpaceX SPCX 等重大 IPO 進度

## HTML 設計規格
- 深色主題（背景 #04040d，IBM Plex Mono + Inter 字體）
- 頂部跑馬燈（即時數據）
- 標題區（badges + 日期 + 4 條關鍵 pill）
- 英雄橫幅（2 欄，最重要的 2 個事件）
- 每日必看 5 大預警指標模組（VIX/HY利差/10Y殖利率/AI龍頭線型/台股槓桿）
- 數據驗證區（✓ 已確認 / ⚠ 預估）
- KPI 指標看板（4 格）
- 視覺圖表區（Chart.js 4.4.1 + datalabels 2.2.0）
- 未來 2 週財報速覽（Filter 按鈕：全部/美股/台股/★持倉）
- 財經新聞中心（Tab：4 個主題）
- 風險矩陣表格
- 投資主題機會（5 張卡片）
- 大師策略總結（3 欄）
- Footer（資料來源）

## 個人持倉背景
台積電(2330)、鴻海(2317)、聯發科(2454)、SMH、NVDA、AVGO、ORCL、LLY、0050、IAUM(黃金)

## 輸出格式
輸出完整的 HTML，用 ```html ... ``` 包裹，包含所有 CSS 和 JavaScript。
不要解釋，直接輸出 HTML。
"""

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

print(f"[{date_str}] 開始生成報告...")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 32000
TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}]

messages = [{"role": "user", "content": PROMPT}]

response = client.messages.create(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    tools=TOOLS,
    messages=messages
)

html_content = None

# web_search 是伺服器端工具：Claude 在同一輪對話內自動完成搜尋。
# 唯一需要我們手動處理的情況是 stop_reason == "pause_turn"
# （伺服器端搜尋迴圈達到單次請求上限，需把回應原樣送回去讓 Claude 繼續）。
for iteration in range(5):
    print(f"  迭代 {iteration+1}: stop_reason={response.stop_reason}")

    if response.stop_reason == "end_turn":
        for block in response.content:
            if hasattr(block, "text"):
                m = re.search(r"```html\s*([\s\S]*?)```", block.text)
                if m:
                    html_content = m.group(1).strip()
                elif "<html" in block.text.lower():
                    html_content = block.text.strip()
        break

    elif response.stop_reason == "pause_turn":
        messages.append({"role": "assistant", "content": response.content})
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            tools=TOOLS,
            messages=messages
        )
        continue

    else:
        print(f"  ⚠️ 非預期 stop_reason: {response.stop_reason}")
        for block in response.content:
            if hasattr(block, "text"):
                print(f"  已產生文字長度: {len(block.text)}")
        break

if not html_content:
    raise RuntimeError(f"未能從 Claude 取得 HTML 內容（最終 stop_reason={response.stop_reason}）")

archive_dir = "archive"
os.makedirs(archive_dir, exist_ok=True)
if os.path.exists("index.html"):
    shutil.copy("index.html", f"{archive_dir}/{date_str}.html")
    print(f"  已備份至 archive/{date_str}.html")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"  ✅ 報告已寫入 index.html（{len(html_content):,} bytes）")
