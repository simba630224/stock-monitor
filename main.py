import yfinance as yf
import pandas as pd
import requests
import os
import mplfinance as mpf
from datetime import datetime

# --- 環境變數 ---
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

WATCH_LIST = [
    {'symbol': '2330.TW',   'name': '台積電'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '台灣50'},
    {'symbol': '00878.TW',  'name': '國泰永續高股息'},
    {'symbol': '009812.TW', 'name': 'Japan'},
    {'symbol': '00830.TW',  'name': '費城半導體'},
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': 'GOOGL',     'name': 'GOOGLE'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'MSFT',      'name': 'MSFT'},
    {'symbol': 'QQQ',       'name': '那斯達克'},
    {'symbol': 'VOO',       'name': 'S&P500'},
    {'symbol': 'VT',        'name': 'World Stock'}
]

def calculate_all(df):
    """手動計算所有技術指標 (MA, MACD, RSI, 週KD)"""
    # 1. 均線
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    # 2. MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    macd_l = ema12 - ema26
    sig_l = macd_l.ewm(span=9, adjust=False).mean()
    df['MACDh'] = macd_l - sig_l
    # 3. RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    # 4. 週 KD
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    l_min, h_max = df_w['Low'].rolling(9).min(), df_w['High'].rolling(9).max()
    rsv = (df_w['Close'] - l_min) / (h_max - l_min) * 100
    df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
    df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
    return df, df_w

def send_tg(msg, img=None):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/"
    try:
        if img:
            requests.post(url+"sendPhoto", data={'chat_id':TG_CHAT_ID, 'caption':msg, 'parse_mode':'Markdown'}, files={'photo':open(img,'rb')})
        else:
            requests.post(url+"sendMessage", data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'Markdown'})
    except: pass

def main():
    date_now = datetime.now().strftime('%Y/%m/%d')
    send_tg(f"🔔 *深度分析報告啟動* ({date_now})")
    
    gold, dead, breakout = [], [], []

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df, df_w = calculate_all(df.astype(float).dropna())
            
            # 數據特徵
            price = df['Close'].iloc[-1]
            chg = (price/df['Close'].iloc[-2]-1)*100
            rsi = df['RSI'].iloc[-1]
            vol_ratio = df['Volume'].iloc[-1] / df['Volume'].iloc[-21:-1].mean()
            
            # 週線狀態
            k, d, pk, pd_v = df_w['K'].iloc[-1], df_w['D'].iloc[-1], df_w['K'].iloc[-2], df_w['D'].iloc[-2]
            status = "金叉轉強" if k > d and pk <= pd_v else "死叉警戒" if k < d and pk >= pd_v else "整理"
            if "金叉" in status: gold.append(name)
            if "死叉" in status: dead.append(name)

            # 繪圖
            fn = f"temp_{sym.replace('.','_')}.png"
            p_df = df.tail(60)
            ap = [mpf.make_addplot(p_df['MA20'], color='blue', width=0.8),
                  mpf.make_addplot(p_df['MA60'], color='orange', width=0.8),
                  mpf.make_addplot(p_df['MACDh'], type='bar', panel=1, color=['red' if x > 0 else 'green' for x in p_df['MACDh']])]
            mpf.plot(p_df, type='candle', style='charles', addplot=ap, title=name, savefig=fn, panel_ratios=(3,1))
            
            # 深入文字分析
            msg = f"📈 *{name} ({sym})*\n"
            msg += f"現價: `{price:.2f}` ({chg:+.2f}%)\n"
            msg += f"週線KD: `K:{k:.1f}/D:{d:.1f}` ({status})\n"
            msg += f"強弱指標: `RSI:{rsi:.1f}` ({'超買' if rsi>70 else '超跌' if rsi<30 else '中性'})\n"
            msg += f"量能觀察: `{vol_ratio:.2f}x` (對比20日均量)\n"
            msg += f"支撐: MA20 `{df['MA20'].iloc[-1]:.1f}`"
            
            send_tg(msg, fn)
            if os.path.exists(fn): os.remove(fn)
        except Exception as e: print(f"Error {sym}: {e}")

    # 總結
    rep = f"【{date_now} 深度篩選總結】\n"
    rep += f"🔹 週金叉: {', '.join(gold) if gold else '無'}\n"
    rep += f"🔸 週死叉: {', '.join(dead) if dead else '無'}\n"
    send_tg(rep)

if __name__ == "__main__":
    main()
