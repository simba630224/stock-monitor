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
    {'symbol': '00687B.TW', 'name': '國泰20年美債'},
    {'symbol': '009812.TW', 'name': '野村日本東證ETF'}
]

US_WATCH = {
    '^GSPC': '標普500 S&P500 指數', 
    '^IXIC': '納斯達克 Nasdaq', 
    '^SOX': '費城半導體 SOX',
    'NVDA': '輝達 Nvidia',
    'AAPL': '蘋果 Apple',
    'MSFT': '微軟 Microsoft',
    'GOOGL': '谷歌 Google'
}

def get_filtered_news(name):
    """
    深度財經過濾邏輯：
    1. 強制搜尋標題包含財經關鍵字 (股市/股價/財經/ETF/債券)
    2. 強制排除娛樂圈所有相關關鍵字
    """
    topic_limit = "(intitle:股市 OR intitle:股價 OR intitle:財經 OR intitle:ETF OR intitle:債券 OR intitle:美股)"
    exclude_list = "-娛樂 -明星 -藝人 -影視 -大S -小S -汪小菲 -具俊曄 -許雅鈞 -綜藝 -緋聞 -穿搭 -八卦"
    media_limit = "(經濟日報 OR 工商日報 OR 華爾街日報)"
    
    query = f"{name} {topic_limit} {media_limit} {exclude_list}"
    url = f"https://news.google.com/rss/search?q={query}+when:48h&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    
    try:
        r = requests.get(url, timeout=10)
        root = ET.fromstring(r.text)
        items = []
        for item in root.findall('.//item')[:2]:
            title = item.find('title').text
            link = item.find('link').text
            
            if any(bad in title for bad in ["大S", "小S", "汪小菲", "婚姻", "婆婆"]):
                continue
                
            items.append(f"🔹 {title}\n   [閱讀原文]({link})")
            
        return "\n".join(items) if items else "近期暫無指定權威報系之重大財經報導。"
    except: 
        return "新聞載入暫時失敗。"

def analyze_ma_relation(price, ma20, ma60):
    if price > ma20 and price > ma60: return "🟢 站穩 MA20 與 MA60 (強勢排列)"
    if price < ma20 and price < ma60: return "🔴 位於 MA20 與 MA60 之下 (偏空格局)"
    if price > ma60 and price < ma20: return "🟡 守住 MA60 季線，但上方受 MA20 壓制 (築底中)"
    if price > ma20 and price < ma60: return "🔵 突破 MA20 月線，但面臨 MA60 季線挑戰 (反彈中)"
    return "均線交纏整理中"

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
        # 1. 抓取股價歷史資料
        df_raw = yf.download(sym, period="2y", progress=False)
        if df_raw.empty: return
        if isinstance(df_raw.columns, pd.MultiIndex): 
            df_raw.columns = df_raw.columns.get_level_values(0)
        df, df_w = calculate_indicators(df_raw.astype(float).dropna())
        
        # 2. 抓取 本益比 (Trailing & Forward)
        t_pe_str = "無"
        f_pe_str = "無"
        try:
            ticker_obj = yf.Ticker(sym)
            info = ticker_obj.info
            t_pe = info.get('trailingPE')
            f_pe = info.get('forwardPE')
            
            if isinstance(t_pe, (int, float)):
                t_pe_str = f"{t_pe:.2f}"
            if isinstance(f_pe, (int, float)):
                f_pe_str = f"{f_pe:.2f}"
        except:
            pass 
        
        last_p = df['Close'].iloc[-1]
        ma_status = analyze_ma_relation(last_p, df['MA20'].iloc[-1], df['MA60'].iloc[-1])
        
        k, d, pk, pd_v = df_w['K'].iloc[-1], df_w['D'].iloc[-1], df_w['K'].iloc[-2], df_w['D'].iloc[-2]
        kd_text = "金叉轉強" if k > d and pk <= pd_v else "死亡交叉" if k < d and pk >= pd_v else "趨勢延續"
        
        # 繪圖 (MA20藍, MA60橘)
        fn = f"chart_{sym.replace('^','').replace('.','_')}.png"
        pdf = df.tail(60)
        ap = [mpf.make_addplot(pdf['MA20'], color='blue', width=1.2), 
              mpf.make_addplot(pdf['MA60'], color='orange', width=1.2)]
        mpf.plot(pdf, type='candle', style='charles', addplot=ap, title=f"{name}", savefig=fn)
        
        # 抓取過濾後新聞
        news = get_filtered_news(name)
        
        # 3. 輸出文字模板更新
        msg = (f"📊 *報告標的：{name}*\n"
               f"目前價位: `{last_p:.2f}`\n"
               f"本益比: `歷史 {t_pe_str} / 預估 {f_pe_str}`\n"
               f"均線位置: {ma_status}\n"
               f"週線 KD: `{k:.1f}/{d:.1f}` ({kd_text})\n\n"
               f"📰 *核心財經頭條：*\n{news}")
        
        send_tg(msg, fn)
        if os.path.exists(fn): os.remove(fn)
        time.sleep(1) # 增加暫停時間，避免被 Yahoo API 阻擋
    except Exception as e: 
        print(f"Error {sym}: {e}")

def main():
    now_str = datetime.now().strftime('%Y/%m/%d')
    send_tg(f"🏛️ *全球財經深度掃描報告 ({now_str})*")
    
    # 台股標的
    for item in TW_CORE:
        process_target(item['symbol'], item['name'])
    # 美股標的
    for sym, name in US_WATCH.items():
        process_target(sym, name)

    send_tg(f"🏁 *報告傳輸完成。*")

if __name__ == "__main__":
    main()
