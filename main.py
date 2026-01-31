import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

WATCH_LIST = [
    {'symbol': '2330.TW',   'name': '台積電'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '元大台灣50'},
    {'symbol': '00830.TW',  'name': '國泰費城半導體'},
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

def send_telegram(text, img_path=None):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 變數缺失")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path and os.path.exists(img_path):
            with open(img_path, 'rb') as f:
                r = requests.post(f"{url}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            r = requests.post(f"{url}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
        print(f"Telegram Response: {r.status_code}")
    except Exception as e:
        print(f"Telegram Error: {e}")

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"--- 分析啟動: {report_date} ---")
    send_telegram(f"🔔 *系統啟動：開始掃描標的名單 ({report_date})*")

    gold_list, dead_list, breakout_list = [], [], []

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print(f"處理: {sym}")
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
            
            # 指標：MA, MACD, 週線KD
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            macd = ta.macd(df['Close'])
            df = pd.concat([df, macd], axis=1)
            df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
            kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
            
            # 信號判斷
            k, d, pk, pd_v = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3'], kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
            is_gold = k > d and pk <= pd_v
            is_dead = k < d and pk >= pd_v
            vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
            stay_ma20 = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()

            if is_gold: gold_list.append(f"{name}({sym})")
            if is_dead: dead_list.append(f"{name}({sym})")
            if vol_break and stay_ma20: breakout_list.append(f"{name}({sym})")

            # 繪圖 (含 MACD 柱狀圖)
            img_name = f"{sym.replace('.','_')}.png"
            plot_df = df.tail(60)
            colors = ['red' if x > 0 else 'green' for x in plot_df['MACDh_12_26_9']]
            apds = [
                mpf.make_addplot(plot_df['MA20'], color='blue', width=0.8),
                mpf.make_addplot(plot_df['MA60'], color='orange', width=0.8),
                mpf.make_addplot(plot_df['MACDh_12_26_9'], type='bar', panel=1, color=colors, secondary_y=False)
            ]
            mpf.plot(plot_df, type='candle', style='charles', addplot=apds, title=f"{name}", savefig=img_name, panel_ratios=(3,1))
            
            msg = f"📈 *{name} ({sym})*\n價位: `{df['Close'].iloc[-1]:.1f}`\n指標: {'金叉轉強' if is_gold else '死叉警戒' if is_dead else '盤整'}\nMACD柱: `{plot_df['MACDh_12_26_9'].iloc[-1]:.2f}`"
            send_telegram(msg, img_name)
            if os.path.exists(img_name): os.remove(img_name)
        except Exception as e: print(f"Error {sym}: {e}")

    # 彙整總報告
    report = "【" + report_date + " 台股深度篩選分析報告】\n"
    report += "一、 市值百大個股：技術指標監測\n\n"
    report += "🔹 *週 KD 金叉 (轉強)*：\n" + (", ".join(gold_list) if gold_list else "無") + "\n\n"
    report += "🔸 *週 KD 死叉 (警戒)*：\n" + (", ".join(dead_list) if dead_list else "無") + "\n\n"
    report += "🚀 *強勢回測名單 (5 日前帶量突破 + 站穩支撐)*：\n"
    report += ("\n".join(breakout_list) if breakout_list else "今日無符合標的") + "\n\n"
    report += "二、 總結與提醒\n若個股跌破 MA20 且 MACD 柱狀圖轉綠縮短，應注意回檔。報告完畢。"
    send_telegram(report)

if __name__ == "__main__":
    main()
