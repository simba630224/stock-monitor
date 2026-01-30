import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 配置與變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 市值前 100 大與熱門標的 (縮減演示，可自行擴充)
STOCKS = [
    '2330.TW', '2317.TW', '2454.TW', '2308.TW', '2382.TW', '2303.TW', '2881.TW', '2882.TW', '2412.TW', '3711.TW',
    '2886.TW', '2357.TW', '2891.TW', '2603.TW', '3008.TW', '1301.TW', '1303.TW', '1216.TW', '2892.TW', '2885.TW',
    '2002.TW', '2884.TW', '2379.TW', '2327.TW', '2880.TW', '3045.TW', '2395.TW', '2912.TW', '3034.TW', '2883.TW',
    '2408.TW', '2474.TW', '2887.TW', '1326.TW', '2354.TW', '2890.TW', '3231.TW', '4904.TW', '2345.TW', '2609.TW',
    '2615.TW', '2409.TW', '3481.TW', '1101.TW', '5880.TW', '5871.TW', '2360.TW', '2301.TW', '3037.TW', '6505.TW'
]
ETFS = [
    '0050.TW', '006208.TW', '0056.TW', '00878.TW', '00919.TW', '00929.TW', '00713.TW', '00662.TW', '00646.TW', '00881.TW'
]

def get_weekly_status(df):
    try:
        # 轉換週線
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'})
        if len(df_w) < 10: return "數據不足", 0, 0
        # 週 KD
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        k, d = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3']
        pk, pd_val = kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
        level = "高檔" if k > 80 else "低檔" if k < 20 else "中檔"
        signal = "🔥週KD金叉" if k > d and pk <= pd_val else "❄️週KD死叉" if k < d and pk >= pd_val else ""
        return f"{level} {signal}", k, d
    except: return "計算失敗", 0, 0

def send_telegram(text, img_path):
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        with open(img_path, 'rb') as f:
            requests.post(f"{url_base}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
    except Exception as e: print(f"發送失敗: {e}")

def main():
    print(f"=== 分析啟動: {datetime.now()} ===")
    all_list = STOCKS + ETFS
    
    for sym in all_list:
        try:
            df = yf.download(sym, period="1y", interval="1d", progress=False)
            if df.empty: continue

            # 數據清理 (修復 MultiIndex 問題)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()

            # 指標計算
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            kd_text, k, d = get_weekly_status(df)

            # 帶量突破偵測 (5日前量增 1.5 倍且目前站穩均線)
            vol_check = df['Volume'].iloc[-5] > df['Volume'].iloc[-15:-5].mean() * 1.5
            stay_above = (df['Close'].iloc[-5:] > df['MA20'].iloc[-5:]).all() or (df['Close'].iloc[-5:] > df['MA60'].iloc[-5:]).all()
            
            # 發送條件：技術轉折 或 帶量突破站穩
            if ("叉" in kd_text) or (vol_check and stay_above):
                img_name = f"{sym.replace('.','_')}.png"
                apds = [
                    mpf.make_addplot(df['MA20'].tail(40), color='blue', width=1),
                    mpf.make_addplot(df['MA60'].tail(40), color='orange', width=1)
                ]
                title_txt = f"{sym} (MA20:{df['MA20'].iloc[-1]:.1f}, MA60:{df['MA60'].iloc[-1]:.1f})"
                mpf.plot(df.tail(40), type='candle', style='charles', addplot=apds, title=title_txt, savefig=img_name)

                msg = f"🔔 *標的通知: {sym}*\n週線狀態: {kd_text}\n收盤價: {df['Close'].iloc[-1]:.1f}\n支撐: MA20={df['MA20'].iloc[-1]:.1f}"
                send_telegram(msg, img_name)
                if os.path.exists(img_name): os.remove(img_name)
                print(f"✅ 已發送: {sym}")

        except Exception as e: print(f"❌ 處理 {sym} 出錯: {e}")

if __name__ == "__main__":
    main()
