import yfinance as yf
import pandas as pd
import requests
import os
import mplfinance as mpf
from datetime import datetime

# 嘗試載入 pandas_ta，失敗時不報錯
try:
    import pandas_ta as ta
except ImportError:
    print("❌ 警告: 找不到 pandas_ta 套件")

# --- 環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

WATCH_LIST = [
    {'symbol': '2330.TW',   'name': '台積電'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '元大台灣50'},
    {'symbol': '00830.TW',  'name': '費城半導體'},
    {'symbol': '00757.TW',  'name': '統一FANG+'},
    {'symbol': '009812.TW', 'name': '日本指數'},
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'MSFT',      'name': 'MSFT'},
    {'symbol': 'GOOGL',     'name': 'GOOGLE'},
    {'symbol': 'QQQ',       'name': '那斯達克'},
    {'symbol': 'VOO',       'name': 'S&P500'},
    {'symbol': 'VT',        'name': 'World ETF'}
]

def send_tg(msg, img=None):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img and os.path.exists(img):
            with open(img, 'rb') as f:
                requests.post(f"{url}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': msg, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"{url}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})
    except Exception as e: print(f"TG Error: {e}")

def main():
    date_str = datetime.now().strftime('%Y/%m/%d')
    print(f"--- 分析啟動: {date_str} ---")
    send_tg(f"🚀 *系統啟動：開始掃描標的名單 ({date_str})*")

    gold, dead, breakout = [], [], []

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print(f"處理中: {sym}")
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
            
            # 指標計算
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            
            # MACD 柱狀圖 (手動計算避免套件報錯)
            ema12 = df['Close'].ewm(span=12, adjust=False).mean()
            ema26 = df['Close'].ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            df['MACDh'] = macd_line - signal_line
            
            # 週線 KD (使用 pandas_ta 如果可用)
            is_gold, is_dead = False, False
            try:
                df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
                kd = df_w.ta.stoch(k=9, d=3, smooth_k=3)
                k, d = kd.iloc[-1][0], kd.iloc[-1][1]
                pk, pd_v = kd.iloc[-2][0], kd.iloc[-2][1]
                is_gold = k > d and pk <= pd_v
                is_dead = k < d and pk >= pd_v
                if is_gold: gold.append(f"{name}({sym})")
                if is_dead: dead.append(f"{name}({sym})")
            except: pass

            # 強勢回測
            if df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean()*1.5 and (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all():
                breakout.append(f"{name}({sym})")

            # 繪圖
            fn = f"temp_{sym.replace('.','_')}.png"
            p_df = df.tail(60)
            mc = ['red' if x > 0 else 'green' for x in p_df['MACDh']]
            ap = [
                mpf.make_addplot(p_df['MA20'], color='blue', width=0.8),
                mpf.make_addplot(p_df['MA60'], color='orange', width=0.8),
                mpf.make_addplot(p_df['MACDh'], type='bar', panel=1, color=mc)
            ]
            mpf.plot(p_df, type='candle', style='charles', addplot=ap, title=name, savefig=fn, panel_ratios=(3,1))
            
            txt = f"📈 *{name}*\n價: `{df['Close'].iloc[-1]:.1f}`\nMACD柱: `{df['MACDh'].iloc[-1]:.2f}`"
            send_tg(txt, fn)
            if os.path.exists(fn): os.remove(fn)
        except Exception as e: print(f"Error {sym}: {e}")

    # 彙整報告
    rep = f"【{date_str} 盤前篩選報告】\n\n"
    rep += "一、 市值百大與核心監測\n"
    rep += f"🔹 週金叉: {', '.join(gold) if gold else '無'}\n"
    rep += f"🔸 週死叉: {', '.join(dead) if dead else '無'}\n"
    rep += f"🚀 強勢回測: {', '.join(breakout) if breakout else '無'}\n\n"
    rep += "二、 總結\n報告完成。請觀察 MACD 柱狀體。報告完畢。"
    send_tg(rep)

if __name__ == "__main__":
    main()
