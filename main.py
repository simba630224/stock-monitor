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

# 這裡僅列出示範，您可以按此格式補完前100大個股與50大ETF
# 為確保執行速度，建議優先放入您核心關注的標的
WATCH_LIST = [
    {'symbol': '2330.TW', 'name': '台積電'}, {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'}, {'symbol': '2382.TW', 'name': '廣達'},
    {'symbol': '2303.TW', 'name': '聯電'}, {'symbol': '2881.TW', 'name': '富邦金'},
    {'symbol': '0050.TW', 'name': '元大台灣50'}, {'symbol': '006208.TW', 'name': '富邦台50'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'}, {'symbol': '00919.TW', 'name': '群益台灣精選高息'}
]

def get_google_news(query, name):
    """透過 Google News RSS 抓取中文新聞 (最新3天)"""
    url = f"https://news.google.com/rss/search?q={query}+when:3d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        r = requests.get(url, timeout=10)
        root = ET.fromstring(r.text)
        news_items = []
        for item in root.findall('.//item')[:3]:
            title = item.find('title').text
            link = item.find('link').text
            news_items.append(f"🔹 {title}\n   [閱讀原文]({link})")
        return "\n\n".join(news_items) if news_items else "近期無重大新聞報告。"
    except: return "新聞抓取失敗。"

def calculate_indicators(df):
    """手動計算週線指標與日線均線"""
    # 日線 MA
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    # 週線數據轉換
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    # 週 KD (9,3,3)
    l9, h9 = df_w['Low'].rolling(9).min(), df_w['High'].rolling(9).max()
    rsv = (df_w['Close'] - l9) / (h9 - l9) * 100
    df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
    df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
    # 週 MACD
    ema12 = df_w['Close'].ewm(span=12).mean()
    ema26 = df_w['Close'].ewm(span=26).mean()
    df_w['MACD'] = ema12 - ema26
    df_w['Signal'] = df_w['MACD'].ewm(span=9).mean()
    return df, df_w

def send_tg(msg, img=None):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/"
    try:
        if img:
            with open(img, 'rb') as f:
                requests.post(url+"sendPhoto", data={'chat_id':TG_CHAT_ID, 'caption':msg, 'parse_mode':'Markdown'}, files={'photo':f})
        else:
            requests.post(url+"sendMessage", data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'Markdown', 'disable_web_page_preview':True})
    except: pass

def main():
    date_str = datetime.now().strftime('%Y/%m/%d')
    send_tg(f"📊 *台股盤前深度分析報告 ({date_str})*")
    
    signals = []
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df, df_w = calculate_indicators(df.astype(float).dropna())
            
            # 1. 週 KD / MACD 交叉判定
            k, d, pk, pd_v = df_w['K'].iloc[-1], df_w['D'].iloc[-1], df_w['K'].iloc[-2], df_w['D'].iloc[-2]
            macd, sig, pm, ps = df_w['MACD'].iloc[-1], df_w['Signal'].iloc[-1], df_w['MACD'].iloc[-2], df_w['Signal'].iloc[-2]
            
            kd_cross = "🔥金叉" if k > d and pk <= pd_v else "❄️死叉" if k < d and pk >= pd_v else "整理"
            macd_cross = "🚀金叉" if macd > sig and pm <= ps else "📉死叉" if macd < sig and pm >= ps else "持平"
            
            # 2. 強勢回測篩選 (5日前爆量 1.5x 且現價守 MA20/60)
            vol_avg = df['Volume'].iloc[-16:-6].mean()
            vol_5 = df['Volume'].iloc[-6]
            is_breakout = vol_5 > vol_avg * 1.5
            stay_ma = (df['Close'].iloc[-1] >= df['MA20'].iloc[-1]) or (df['Close'].iloc[-1] >= df['MA60'].iloc[-1])
            
            if (kd_cross != "整理") or (macd_cross != "持平") or (is_breakout and stay_ma):
                # 抓取新聞
                news = get_google_news(name, name)
                
                # 繪圖
                fn = f"temp_{sym.replace('.','_')}.png"
                p_df = df.tail(60)
                ap = [mpf.make_addplot(p_df['MA20'], color='blue'), mpf.make_addplot(p_df['MA60'], color='orange')]
                mpf.plot(p_df, type='candle', style='charles', addplot=ap, title=name, savefig=fn)
                
                report = (f"🔍 *標的分析：{name} ({sym})*\n"
                          f"💰 現價: `{df['Close'].iloc[-1]:.2f}`\n"
                          f"📈 週KD: `K:{k:.1f}/D:{d:.1f}` ({kd_cross})\n"
                          f"📊 週MACD: ({macd_cross})\n"
                          f"🚀 強勢突破回測: {'是' if is_breakout and stay_ma else '否'}\n\n"
                          f"📰 *相關新聞：*\n{news}")
                
                send_tg(report, fn)
                if os.path.exists(fn): os.remove(fn)
                time.sleep(2)
        except Exception as e: print(f"Error {sym}: {e}")

if __name__ == "__main__":
    main()
