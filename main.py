import yfinance as yf
import pandas as pd
import requests
import os
import time
import mplfinance as mpf
from datetime import datetime
import xml.etree.ElementTree as ET

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 台股核心標的 (更新名單與債券)
TW_CORE = [
    {'symbol': '2330.TW', 'name': '台積電'},
    {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'},
    {'symbol': '2308.TW', 'name': '台達電'},
    {'symbol': '0050.TW', 'name': '元大台灣50'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'},
    {'symbol': '00937B.TW', 'name': '群益ESG投等債20+'},
    {'symbol': '00687B.TW', 'name': '國泰20年美債'}
]

# 美股指數與巨頭
US_WATCH = {
    '^GSPC': 'S&P 500', 
    '^IXIC': 'Nasdaq', 
    '^SOX': '費城半導體',
    'NVDA': '輝達',
    'AAPL': '蘋果',
    'MSFT': '微軟'
}

def get_filtered_news(query):
    """精準篩選：經濟日報、工商日報、華爾街日報"""
    # 搜尋指令：(關鍵字) + 報系名稱
    source_query = f"{query} (經濟日報 OR 工商日報 OR 華爾街日報)"
    url = f"https://news.google.com/rss/search?q={source_query}+when:48h&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        r = requests.get(url, timeout=10)
        root = ET.fromstring(r.text)
        items = []
        for item in root.findall('.//item')[:2]:
            items.append(f"🔹 {item.find('title').text}\n   [閱讀原文]({item.find('link').text})")
        return "\n".join(items) if items else "近期暫無指定報系之重大報導。"
    except: return "新聞抓取失敗。"

def analyze_ma_relation(price, ma20, ma60):
    """判定價格與均線的關聯性"""
    if price > ma20 and price > ma60: return "站穩 MA20 與 MA60 之上 (多頭強勢)"
    if price < ma20 and price < ma60: return "位於 MA20 與 MA60 之下 (空頭排列)"
    if price > ma60 and price < ma20: return "站穩 MA60，但受阻於 MA20 之下 (偏多整理)"
    if price > ma20 and price < ma60: return "站穩 MA20，但承壓於 MA60 之下 (反彈格局)"
    return "均線糾結中"

def calculate_indicators(df):
    """計算週 KD 與 MACD"""
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    # 週線轉換
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    ln, hn = df_w['Low'].rolling(9).min(), df_w['High'].rolling(9).max()
    rsv = (df_w['Close'] - ln) / (hn - ln) * 100
    df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
    df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
    ema12, ema26 = df_w['Close'].ewm(span=12).mean(), df_w['Close'].ewm(span=26).mean()
    df_w['MACD'] = ema12 - ema26
    df_w['Sig'] = df_w['MACD'].ewm(span=9).mean()
    return df, df_w

def send_tg(msg, img=None):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/"
    if img:
        with open(img, 'rb') as f:
            requests.post(url+"sendPhoto", data={'chat_id':TG_CHAT_ID, 'caption':msg, 'parse_mode':'Markdown'}, files={'photo':f})
    else:
        requests.post(url+"sendMessage", data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'Markdown', 'disable_web_page_preview':True})

def process_target(sym, name, is_us=False):
    """處理單一標的：分析、繪圖、發送"""
    try:
        df_raw = yf.download(sym, period="2y", progress=False)
        if df_raw.empty: return
        if isinstance(df_raw.columns, pd.MultiIndex): df_raw.columns = df_raw.columns.get_level_values(0)
        df, df_w = calculate_indicators(df_raw.astype(float).dropna())
        
        last_p = df['Close'].iloc[-1]
        ma20, ma60 = df['MA20'].iloc[-1], df['MA60'].iloc[-1]
        ma_relation = analyze_ma_relation(last_p, ma20, ma60)
        
        # 週指標
        k, d, pk, pd_v = df_w['K'].iloc[-1], df_w['D'].iloc[-1], df_w['K'].iloc[-2], df_w['D'].iloc[-2]
        kd_status = "金叉轉強" if k > d and pk <= pd_v else "死亡交叉" if k < d and pk >= pd_v else "趨勢延續"
        
        # 繪圖
        fn = f"chart_{sym.replace('^','').replace('.','_')}.png"
        pdf = df.tail(60)
        ap = [mpf.make_addplot(pdf['MA20'], color='blue', width=0.8), 
              mpf.make_addplot(pdf['MA60'], color='orange', width=0.8)]
        mpf.plot(pdf, type='candle', style='charles', addplot=ap, title=f"{name} ({sym})", savefig=fn)
        
        # 組合訊息
        news = get_filtered_news(name)
        msg = (f"📈 *標的報告：{name} ({sym})*\n"
               f"現價: `{last_p:.2f}`\n"
               f"均線狀態: {ma_relation}\n"
               f"週 KD: `{k:.1f}/{d:.1f}` ({kd_status})\n\n"
               f"📰 *核心財經動態 (三大報系)：*\n{news}")
        
        send_tg(msg, fn)
        if os.path.exists(fn): os.remove(fn)
        time.sleep(1)
    except Exception as e: print(f"Error processing {sym}: {e}")

def main():
    date_str = datetime.now().strftime('%Y/%m/%d')
    send_tg(f"👑 *台北盤前旗艦級全方位分析 ({date_str})*")
    
    # 一、台股核心標的 (含債券與圖表)
    send_tg("--- 🟢 第一部分：台股核心與債券監測 ---")
    for item in TW_CORE:
        process_target(item['symbol'], item['name'])
        
    # 二、美股指數與科技巨頭 (含圖表)
    send_tg("--- 🔵 第二部分：美股指數與巨頭監測 ---")
    for sym, name in US_WATCH.items():
        process_target(sym, name, is_us=True)

    send_tg(f"🏁 *{date_str} 盤前掃描任務完成。*")

if __name__ == "__main__":
    main()
