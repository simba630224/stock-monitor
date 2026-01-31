import yfinance as yf
import pandas as pd
import requests
import os
import mplfinance as mpf
from datetime import datetime

# --- 環境變數 ---
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# 您指定的標的名單
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

def send_tg(msg, img_path=None):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = "https://api.telegram.org/bot{}/".format(TG_TOKEN)
    try:
        if img_path and os.path.exists(img_path):
            with open(img_path, 'rb') as f:
                requests.post(url + "sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': msg, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(url + "sendMessage", data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})
    except Exception as e: print("TG發送異常: " + str(e))

def calculate_indicators(df):
    """手動計算技術指標，避免套件安裝失敗"""
    # MA
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df['MACDh'] = macd_line - signal_line
    # 週 KD
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    low_min = df_w['Low'].rolling(window=9).min()
    high_max = df_w['High'].rolling(window=9).max()
    rsv = (df_w['Close'] - low_min) / (high_max - low_min) * 100
    df_w['K'] = rsv.ewm(com=2, adjust=False).mean()
    df_w['D'] = df_w['K'].ewm(com=2, adjust=False).mean()
    return df, df_w

def main():
    date_now = datetime.now().strftime('%Y/%m/%d')
    send_tg("🚀 *盤前監控啟動* ({})".format(date_now))

    gold, dead, breakout = [], [], []

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
            
            df, df_w = calculate_indicators(df)
            
            # 數據分析
            now_p = df['Close'].iloc[-1]
            prev_p = df['Close'].iloc[-2]
            change_pct = (now_p / prev_p - 1) * 100
            macd_h = df['MACDh'].iloc[-1]
            macd_trend = "轉強" if macd_h > df['MACDh'].iloc[-2] else "轉弱"
            
            k, d = df_w['K'].iloc[-1], df_w['D'].iloc[-1]
            pk, pd_v = df_w['K'].iloc[-2], df_w['D'].iloc[-2]
            
            is_gold = k > d and pk <= pd_v
            is_dead = k < d and pk >= pd_v
            if is_gold: gold.append(name)
            if is_dead: dead.append(name)

            # 強勢回測
            is_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean()*1.5 and (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
            if is_break: breakout.append(name)

            # 繪圖
            fn = "temp_" + sym.replace('.','_') + ".png"
            p_df = df.tail(60)
            mc = ['red' if x > 0 else 'green' for x in p_df['MACDh']]
            ap = [
                mpf.make_addplot(p_df['MA20'], color='blue', width=0.8),
                mpf.make_addplot(p_df['MA60'], color='orange', width=0.8),
                mpf.make_addplot(p_df['MACDh'], type='bar', panel=1, color=mc)
            ]
            mpf.plot(p_df, type='candle', style='charles', addplot=ap, title=name, savefig=fn, panel_ratios=(3,1))
            
            # 深入分析報告
            analysis = "📈 *{} ({})*\n".format(name, sym)
            analysis += "現價: `{:.2f}` ({:+.2f}%)\n".format(now_p, change_pct)
            analysis += "週線KD: `K:{:.1f} / D:{:.1f}` ({})\n".format(k, d, "金叉" if is_gold else "死叉" if is_dead else "盤整")
            analysis += "MACD柱: `{:.2f}` ({})\n".format(macd_h, macd_trend)
            analysis += "支撐: MA20 `{:.1f}`".format(df['MA20'].iloc[-1])
            
            send_tg(analysis, fn)
            if os.path.exists(fn): os.remove(fn)
        except Exception as e: print("Error " + sym + ": " + str(e))

    # 彙整報告
    rep = "【{} 盤前分析總結】\n\n".format(date_now)
    rep += "🔹 週 KD 金叉: {}\n".format(", ".join(gold) if gold else "無")
    rep += "🔸 週 KD 死叉: {}\n".format(", ".join(dead) if dead else "無")
    rep += "🚀 強勢回測站穩 MA20: {}\n\n".format(", ".join(breakout) if breakout else "無")
    rep += "總結：權值股週線趨勢為觀察重點。報告完畢。"
    send_tg(rep)

if __name__ == "__main__":
    main()
