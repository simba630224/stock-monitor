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

US_WATCH = {
    '^GSPC': 'S&P 500 指數', # 加入「指數」二字增加精確度
    '^IXIC': 'Nasdaq 納斯達克', 
    '^SOX': '費城半導體 SOX',
    'NVDA': '輝達 Nvidia',
    'AAPL': '蘋果 Apple',
    'MSFT': '微軟 Microsoft'
}

def get_filtered_news(name):
    """加強過濾：排除娛樂、社會新聞，鎖定財經報系"""
    # 排除大S、明星等干擾字眼
    exclude_query = "-娛樂 -明星 -大S -汪小菲 -具俊曄 -電影 -戲劇"
    # 鎖定報系與財經領域
    source_query = f"{name} (經濟日報 OR 工商日報 OR 華爾街日報) {exclude_query}"
    
    url = f"https://news.google.com/rss/search?q={source_query}+when:48h&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        r = requests.get(url, timeout=10)
        root = ET.fromstring(r.text)
        items = []
        for item in root.findall('.//item')[:2]:
            title = item.find('title').text
            # 再次檢查標題中是否含有大S等字眼 (雙重防線)
            if any(bad in title for bad in ["大S", "具俊曄", "汪小菲"]):
                continue
            items.append(f"🔹 {title}\n   [閱讀原文]({item.find('link').text})")
        return "\n".join(items) if items else "近期暫無核心報系之財經新聞。"
    except: return "新聞抓取失敗。"

def analyze_ma_relation(price, ma20, ma60):
    if price > ma20 and price > ma60: return "🟢 站穩 MA20 與 MA60 之上 (強勢)"
    if price < ma20 and price < ma60: return "🔴 位於 MA20 與 MA60 之下 (弱勢)"
    if price > ma60 and price < ma20: return "🟡 守住 MA60 季線，但受阻於 MA20 (整理)"
    if price > ma20 and price < ma60: return "🔵 突破 MA20 月線，但面臨 MA60 壓力 (反彈)"
    return "均線糾結中"

def calculate_indicators(df):
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    ln, hn = df_w['Low'].rolling(9).min(), df_w['High'].rolling(9).max()
    rsv = (df_w['Close'] - ln) / (hn - ln) * 100
    df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
    df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
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

def process_target(sym, name):
    try:
        df_raw = yf.download(sym, period="2y", progress=False)
        if df_raw.empty: return
        if isinstance(df_raw.columns, pd.MultiIndex): df_raw.columns = df_raw.columns.get_level_values(0)
        df, df_w = calculate_indicators(df_raw.astype(float).dropna())
        
        last_p = df['Close'].iloc[-1]
        ma20, ma60 = df['MA20'].iloc[-1], df['MA60'].iloc[-1]
        ma_status = analyze_ma_relation(last_p, ma20, ma60)
        
        k, d, pk, pd_v = df_w['K'].iloc[-1], df_w['D'].iloc[-1], df_w['K'].iloc[-2], df_w['D'].iloc[-2]
        kd_text = "金叉轉強" if k > d and pk <= pd_v else "死亡交叉" if k < d and pk >= pd_v else "趨勢中"
        
        fn = f"chart_{sym.replace('^','').replace('.','_')}.png"
        pdf = df.tail(60)
        ap = [mpf.make_addplot(pdf['MA20'], color='blue', width=1), 
              mpf.make_addplot(pdf['MA60'], color='orange', width=1)]
        mpf.plot(pdf, type='candle', style='charles', addplot=ap, title=f"{name}", savefig=fn)
        
        news = get_filtered_news(name)
        msg = (f"📈 *標的報告：{name}*\n"
               f"現價: `{last_p:.2f}`\n"
               f"均線狀態: {ma_status}\n"
               f"週 KD: `{k:.1f}/{d:.1f}` ({kd_text})\n\n"
               f"📰 *核心財經頭條 (三大報系)：*\n{news}")
        
        send_tg(msg, fn)
        if os.path.exists(fn): os.remove(fn)
        time.sleep(1)
    except Exception as e: print(f"Error {sym}: {e}")

def main():
    date_str = datetime.now().strftime('%Y/%m/%d')
    send_tg(f"🏆 *旗艦級全方位財經掃描 ({date_str})*")
    
    # 執行監測
    for item in TW_CORE:
        process_target(item['symbol'], item['name'])
    for sym, name in US_WATCH.items():
        process_target(sym, name)

    send_tg(f"🏁 *{date_str} 盤前報告掃描完成。*")

if __name__ == "__main__":
    main()
