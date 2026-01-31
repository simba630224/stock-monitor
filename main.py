import yfinance as yf
import pandas as pd
import requests
import os
import mplfinance as mpf
from datetime import datetime

# --- 環境變數讀取 ---
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

WATCH_LIST = [
    {'symbol': '2330.TW',   'name': '台積電'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '元大台灣50'},
    {'symbol': '00830.TW',  'name': '費城半導體'},
    {'symbol': '00757.TW',  'name': '統一FANG+'},
    {'symbol': '009812.TW', 'name': '日本指數'},
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'MSFT',      'name': '微軟'},
    {'symbol': 'GOOGL',     'name': 'GOOGLE'},
    {'symbol': 'QQQ',       'name': '那斯達克'},
    {'symbol': 'VOO',       'name': 'S&P500'},
    {'symbol': 'VT',        'name': '世界ETF'}
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

def calculate_kd(df_w):
    """手動計算 KD 指標 (9,3,3)"""
    low_min = df_w['Low'].rolling(window=9).min()
    high_max = df_w['High'].rolling(window=9).max()
    rsv = (df_w['Close'] - low_min) / (high_max - low_min) * 100
    k = rsv.ewm(com=2, adjust=False).mean() # com=2 等同於 3日平均
    d = k.ewm(com=2, adjust=False).mean()
    return k, d

def main():
    date_now = datetime.now().strftime('%Y/%m/%d')
    print("--- 開始分析任務 ---")
    send_tg("🚀 *盤前監控啟動* ({})".format(date_now))

    gold_list, dead_list, breakout_list = [], [], []

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print("分析標的: " + sym)
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()

            # 1. 計算均線
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()

            # 2. 計算 MACD 柱狀圖 (12, 26, 9)
            ema12 = df['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df['Close'].ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            df['MACDh'] = macd_line - signal_line

            # 3. 計算週線 KD
            df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
            df_w['K'], df_w['D'] = calculate_kd(df_w)
            
            k_val, d_val = df_w['K'].iloc[-1], df_w['D'].iloc[-1]
            pk, pd_v = df_w['K'].iloc[-2], df_w['D'].iloc[-2]
            
            is_gold = (k_val > d_val) and (pk <= pd_v)
            is_dead = (k_val < d_val) and (pk >= pd_v)
            
            if is_gold: gold_list.append(name)
            if is_dead: dead_list.append(name)

            # 4. 強勢回測偵測 (5日前爆量且目前守住 MA20)
            vol_avg = df['Volume'].iloc[-16:-6].mean()
            vol_target = df['Volume'].iloc[-6]
            if vol_target > vol_avg * 1.5 and (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all():
                breakout_list.append(name)

            # 5. 繪圖並發送
            fn = "temp_" + sym.replace('.', '_') + ".png"
            pdf = df.tail(60)
            m_colors = ['red' if x > 0 else 'green' for x in pdf['MACDh']]
            ap = [
                mpf.make_addplot(pdf['MA20'], color='blue', width=0.8),
                mpf.make_addplot(pdf['MA60'], color='orange', width=0.8),
                mpf.make_addplot(pdf['MACDh'], type='bar', panel=1, color=m_colors)
            ]
            mpf.plot(pdf, type='candle', style='charles', addplot=ap, title=name, savefig=fn, panel_ratios=(3,1))
            
            cap = "📈 *{}*\n現價: `{:.1f}`\nMACD柱: `{:.2f}`".format(name, df['Close'].iloc[-1], df['MACDh'].iloc[-1])
            send_tg(cap, fn)
            if os.path.exists(fn): os.remove(fn)

        except Exception as e: print("處理 " + sym + " 出錯: " + str(e))

    # 最終報告組合
    rep = "【{} 盤前分析總結】\n\n".format(date_now)
    rep += "一、 市值百大與核心標的監測\n"
    rep += "🔹 週 KD 金叉: {}\n".format(", ".join(gold_list) if gold_list else "今日無")
    rep += "🔸 週 KD 死叉: {}\n".format(", ".join(dead_list) if dead_list else "今日無")
    rep += "🚀 強勢回測站穩 MA20: {}\n\n".format(", ".join(breakout_list) if breakout_list else "今日無")
    rep += "二、 總結\n標的分析完成。請觀察 MACD 柱狀體變化。報告完畢。"
    
    send_tg(rep)

if __name__ == "__main__":
    main()
