import yfinance as yf
import pandas as pd
import requests, os, mplfinance as mpf
from datetime import datetime

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

WATCH_LIST = [
    {'symbol': '2330.TW', 'name': '台積電'}, {'symbol': '2454.TW', 'name': '聯發科'},
    {'symbol': '0050.TW', 'name': '台灣50'}, {'symbol': '00878.TW', 'name': '國泰永續高股息'},
    {'symbol': '009812.TW', 'name': 'Japan'}, {'symbol': '00830.TW', 'name': '費城半導體'},
    {'symbol': 'NVDA', 'name': '輝達'}, {'symbol': 'GOOGL', 'name': 'GOOGLE'},
    {'symbol': 'META', 'name': 'Meta'}, {'symbol': 'MSFT', 'name': 'MSFT'},
    {'symbol': 'QQQ', 'name': '那斯達克'}, {'symbol': 'VOO', 'name': 'S&P500'}, {'symbol': 'VT', 'name': 'World Stock'}
]

def calculate_all(df):
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()
    ema12, ema26 = df['Close'].ewm(span=12).mean(), df['Close'].ewm(span=26).mean()
    df['MACDh'] = ema12 - ema26 - (ema12 - ema26).ewm(span=9).mean()
    # 週KD
    df_w = df.resample('W-FRI').agg({'High':'max','Low':'min','Close':'last'}).dropna()
    low_min, high_max = df_w['Low'].rolling(9).min(), df_w['High'].rolling(9).max()
    rsv = (df_w['Close'] - low_min) / (high_max - low_min) * 100
    df_w['K'] = rsv.ewm(com=2).mean(); df_w['D'] = df_w['K'].ewm(com=2).mean()
    return df, df_w

def send_tg(msg, img=None):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/"
    if img: requests.post(url+"sendPhoto", data={'chat_id':TG_CHAT_ID, 'caption':msg, 'parse_mode':'Markdown'}, files={'photo':open(img,'rb')})
    else: requests.post(url+"sendMessage", data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'Markdown'})

def main():
    date_now = datetime.now().strftime('%Y/%m/%d')
    send_tg(f"🔔 *深度分析啟動* ({date_now})")
    gold, dead = [], []
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df, df_w = calculate_all(df.astype(float).dropna())
            k, d, pk, pd_v = df_w['K'].iloc[-1], df_w['D'].iloc[-1], df_w['K'].iloc[-2], df_w['D'].iloc[-2]
            status = "金叉轉強" if k > d and pk <= pd_v else "死叉警戒" if k < d and pk >= pd_v else "整理"
            if "金叉" in status: gold.append(name)
            if "死叉" in status: dead.append(name)
            fn = f"temp_{sym.replace('.','_')}.png"
            ap = [mpf.make_addplot(df['MA20'].tail(60), color='blue'), mpf.make_addplot(df['MA60'].tail(60), color='orange'),
                  mpf.make_addplot(df['MACDh'].tail(60), type='bar', panel=1, color=['red' if x > 0 else 'green' for x in df['MACDh'].tail(60)])]
            mpf.plot(df.tail(60), type='candle', style='charles', addplot=ap, title=name, savefig=fn)
            msg = f"📈 *{name} ({sym})*\n現價: `{df['Close'].iloc[-1]:.2f}`\n週線KD: `K:{k:.1f}/D:{d:.1f}` ({status})"
            send_tg(msg, fn)
            if os.path.exists(fn): os.remove(fn)
        except Exception as e: print(f"Error {sym}: {e}")
    send_tg(f"【總結】\n🔹 週金叉: {', '.join(gold)}\n🔸 週死叉: {', '.join(dead)}")

if __name__ == "__main__": main()
