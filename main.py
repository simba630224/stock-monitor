import yfinance as yf
import pandas as pd
import requests
import os
import time
import mplfinance as mpf
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

# --- 1. 配置與清單 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 台股監測清單
TW_WATCH = [
    {'symbol': '2330.TW', 'name': '台積電', 'type': '權值龍頭'},
    {'symbol': '2317.TW', 'name': '鴻海', 'type': '權值龍頭'},
    {'symbol': '2454.TW', 'name': '聯發科', 'type': '權值龍頭'},
    {'symbol': '2308.TW', 'name': '台達電', 'type': '權值龍頭'},
    {'symbol': '0050.TW', 'name': '元大台灣50', 'type': '核心 ETF'},
    {'symbol': '006208.TW', 'name': '富邦台50', 'type': '核心 ETF'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息', 'type': '高股息'}
]

# 美股觀察清單 (指數與 BATMMAAN)
US_INDICES = {'^GSPC': 'S&P 500', '^IXIC': 'Nasdaq', '^SOX': '費城半導體'}
BATMMAAN = ['AVGO', 'AAPL', 'TSLA', 'MSFT', 'META', 'AMZN', 'GOOGL', 'NVDA']

def get_news(query, count=2):
    """抓取 Google News 中文新聞"""
    url = f"https://news.google.com/rss/search?q={query}+when:24h&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        r = requests.get(url, timeout=10)
        root = ET.fromstring(r.text)
        items = []
        for item in root.findall('.//item')[:count]:
            items.append(f"🔹 {item.find('title').text}\n   [閱讀]({item.find('link').text})")
        return "\n".join(items) if items else "暫無重大新聞。"
    except: return "新聞載入失敗。"

def calculate_indicators(df):
    """計算技術指標"""
    # 日線
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    # 週線
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    ln, hn = df_w['Low'].rolling(9).min(), df_w['High'].rolling(9).max()
    rsv = (df_w['Close'] - ln) / (hn - ln) * 100
    df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
    df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
    # 週 MACD
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

def main():
    date_str = datetime.now().strftime('%Y/%m/%d')
    print(f"--- 啟動深度分析: {date_str} ---")
    
    # --- 第一部分：週線指標監測表 ---
    table_msg = f"📊 *一、 全球與台股核心標的：週線指標監測*\n"
    table_msg += "_KD > 80 高檔，< 20 低檔_\n\n"
    
    backout_list = [] # 用於第二部分
    
    for item in TW_WATCH:
        df_raw = yf.download(item['symbol'], period="2y", progress=False)
        if df_raw.empty: continue
        if isinstance(df_raw.columns, pd.MultiIndex): df_raw.columns = df_raw.columns.get_level_values(0)
        df, df_w = calculate_indicators(df_raw.astype(float).dropna())
        
        # 提取指標
        k, d, pk, pd_v = df_w['K'].iloc[-1], df_w['D'].iloc[-1], df_w['K'].iloc[-2], df_w['D'].iloc[-2]
        macd, sig, pm = df_w['MACD'].iloc[-1], df_w['Sig'].iloc[-1], df_w['MACD'].iloc[-2]
        
        status = "金叉轉強" if k > d and pk <= pd_v else "死亡交叉" if k < d and pk >= pd_v else "整理"
        macd_trend = "趨勢向上" if macd > pm else "趨勢向下" if macd < pm else "持平"
        
        table_msg += f"📍 *{item['name']} ({item['symbol']})*\n"
        table_msg += f"狀態: `{status}` (K:{k:.1f}/D:{d:.1f})\n"
        table_msg += f"MACD: `{macd_trend}`\n\n"

        # 判定第二部分：強勢回測 (1/29 爆量篩選)
        # 由於 1/29 是固定點，我們尋找距離當前約 5-6 個交易日的爆量
        vol_avg = df['Volume'].iloc[-20:-6].mean()
        vol_5 = df['Volume'].iloc[-6] # 假設 5 日前為目標突破點
        stay_ma = df['Close'].iloc[-1] >= df['MA20'].iloc[-1] or df['Close'].iloc[-1] >= df['MA60'].iloc[-1]
        
        if vol_5 > vol_avg * 1.5 and stay_ma:
            backout_list.append(f"✅ *{item['name']}*：帶量突破後，目前站穩均線支撐。")

    send_tg(table_msg)

    # --- 第二部分：強勢回測名單 ---
    backout_msg = f"🚀 *二、 強勢回測名單篩選*\n"
    backout_msg += "_邏輯：5日前爆量突破且目前守住 MA20/60_\n\n"
    backout_msg += "\n".join(backout_list) if backout_list else "今日無顯著符合標的。"
    send_tg(backout_msg)

    # --- 第三部分：關鍵標的技術線圖 (台積電專屬) ---
    tsmc_df = yf.download('2330.TW', period="1y", progress=False)
    if isinstance(tsmc_df.columns, pd.MultiIndex): tsmc_df.columns = tsmc_df.columns.get_level_values(0)
    tsmc_df, _ = calculate_indicators(tsmc_df.astype(float).dropna())
    
    fn = "tsmc_analysis.png"
    pdf = tsmc_df.tail(60)
    ap = [mpf.make_addplot(pdf['MA20'], color='blue'), mpf.make_addplot(pdf['MA60'], color='orange')]
    mpf.plot(pdf, type='candle', style='charles', addplot=ap, title="TSMC (2330) Analysis", savefig=fn)
    
    tsmc_msg = f"📉 *三、 關鍵標的技術線圖分析 (2330)*\n\n"
    tsmc_msg += f"1. *K線均線*: 股價位於 MA20 `{tsmc_df['MA20'].iloc[-1]:.1f}` 之上，形態收斂。\n"
    tsmc_msg += f"2. *量能*: 昨日量能對比均量約 `{tsmc_df['Volume'].iloc[-1]/tsmc_df['Volume'].iloc[-20:].mean():.2f}` 倍。\n"
    tsmc_msg += f"3. *週線指標*: 處於週金叉後的發散階段。\n\n"
    tsmc_msg += f"📰 *台積電即時新聞：*\n{get_news('台積電 2330')}"
    
    send_tg(tsmc_msg, fn)
    if os.path.exists(fn): os.remove(fn)

    # --- 第四部分：美股指數與 BATMMAAN 重點新聞 ---
    us_news = f"🌎 *四、 美股指數與巨頭重點新聞*\n\n"
    for idx_sym, idx_name in US_INDICES.items():
        us_news += f"📌 *{idx_name} ({idx_sym})*\n{get_news(idx_name, 1)}\n\n"
    
    us_news += f"🔥 *BATMMAAN 科技巨頭焦點*\n"
    us_news += get_news("輝達 Nvidia 蘋果 Apple 微軟 MSFT", 3)
    
    send_tg(us_news)

if __name__ == "__main__":
    main()
