import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 配置與環境變數 ---
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

def send_telegram(text, img_path=None):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 找不到變數")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path and os.path.exists(img_path):
            with open(img_path, 'rb') as f:
                requests.post(f"{url}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"{url}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e:
        print(f"❌ Telegram 失敗: {e}")

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"=== 啟動分析: {report_date} ===")
    send_telegram(f"🔔 *系統啟動：開始掃描標的名單 ({report_date})*")

    gold, dead, breakout = [], [], []

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
            
            # 指標計算
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            macd = ta.macd(df['Close'])
            df = pd.concat([df, macd], axis=1)
            df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
            kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
            
            # 數據特徵
            last_p = df['Close'].iloc[-1]
            k, d, pk, pd_v = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3'], kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
            m_h = df['MACDh_12_26_9'].iloc[-1]
            
            # 判斷信號
            is_gold = k > d and pk <= pd_v
            is_dead = k < d and pk >= pd_v
            vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
            stay_ma = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()

            if is_gold: gold.append(f"{name}({sym})")
            if is_dead: dead.append(f"{name}({sym})")
            if vol_break and stay_ma: breakout.append(f"{name}({sym})")

            # 繪圖 (含 MACD 柱狀圖)
            img = f"{sym.replace('.','_')}.png"
            p_df = df.tail(60)
            colors = ['red' if x > 0 else 'green' for x in p_df['MACDh_12_26_9']]
            apds = [
                mpf.make_addplot(p_df['MA20'], color='blue', width=0.8),
                mpf.make_addplot(p_df['MA60'], color='orange', width=0.8),
                mpf.make_addplot(p_df['MACDh_12_26_9'], type='bar', panel=1, color=colors, secondary_y=False)
            ]
            mpf.plot(p_df, type='candle', style='charles', addplot=apds, title=name, savefig=img, panel_ratios=(3,1))
            
            msg = f"📈 *{name}*\n現價: `{last_p:.1f}`\n指標: {'週金叉轉強' if is_gold else '週死叉警戒' if is_dead else '整理中'}\nMACD柱: `{m_h:.2f}`"
            send_telegram(msg, img)
            if os.path.exists(img): os.remove(img)
        except Exception as e: print(f"Error {sym}: {e}")

    # 組合總結報告
    report = "【" + report_date + " 盤前篩選分析報告】\n"
    report += "一、 市值百大與核心標的監測\n\n"
    report += "🔹 *週 KD 金叉 (轉強)*：\n" + (", ".join(gold) if gold else "無") + "\n\n"
    report += "🔸 *週 KD 死叉 (警戒)*：\n" + (", ".join(dead) if dead else "無") + "\n\n"
    report += "🚀 *強勢回測站穩 MA20*：\n" + (", ".join(breakout) if breakout else "今日無符合標的") + "\n\n"
    report += "二、 總結\n報告掃描完成。請觀察 MACD 柱狀圖縮放。報告完畢。"
    send_telegram(report)

if __name__ == "__main__":
    main()
