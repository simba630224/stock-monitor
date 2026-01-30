import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 配置設定 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 1. 市值前 100 大個股清單
STOCKS = [
    '2330.TW', '2317.TW', '2454.TW', '2308.TW', '2382.TW', '2303.TW', '2881.TW', '2882.TW', '2412.TW', '3711.TW',
    '2886.TW', '2357.TW', '2891.TW', '2603.TW', '3008.TW', '1301.TW', '1303.TW', '1216.TW', '2892.TW', '2885.TW',
    '2002.TW', '2884.TW', '2379.TW', '2327.TW', '2880.TW', '3045.TW', '2395.TW', '2912.TW', '3034.TW', '2883.TW',
    '2408.TW', '2474.TW', '2887.TW', '1326.TW', '2354.TW', '2890.TW', '3231.TW', '4904.TW', '2345.TW', '2609.TW',
    '2615.TW', '2409.TW', '3481.TW', '1101.TW', '5880.TW', '5871.TW', '2360.TW', '2301.TW', '3037.TW', '6505.TW',
    '2801.TW', '4938.TW', '2376.TW', '2377.TW', '2458.TW', '1504.TW', '2105.TW', '2352.TW', '1402.TW', '2618.TW',
    '2610.TW', '2834.TW', '9904.TW', '1102.TW', '2353.TW', '2449.TW', '2498.TW', '2356.TW', '2812.TW', '5269.TW',
    '6669.TW', '6415.TW', '3661.TW', '5274.TW', '3532.TW', '6409.TW', '2383.TW', '3035.TW', '3189.TW', '3017.TW',
    '2368.TW', '6239.TW', '1513.TW', '1519.TW', '1503.TW', '2049.TW', '8299.TW', '5483.TWO', '6488.TWO'
]

# 2. 市值前 50 大 ETF (含國際型)
ETFS = [
    '0050.TW', '006208.TW', '0056.TW', '00878.TW', '00919.TW', '00929.TW', '00940.TW', '00713.TW', '00662.TW', '00646.TW',
    '00881.TW', '00918.TW', '00915.TW', '0052.TW', '00631L.TW', '00679B.TW', '00751B.TW', '00720B.TW', '00882.TW', '00850.TW'
]

def get_weekly_status(df):
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'})
    if len(df_w) < 5: return "數據不足", 0, 0
    kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
    k, d = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3']
    pk, pd = kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
    level = "高檔" if k > 80 else "低檔" if k < 20 else "中檔"
    signal = "🔥金叉" if k > d and pk <= pd else "❄️死叉" if k < d and pk >= pd else "趨勢中"
    return f"{level} ({signal}), K:{k:.1f}/D:{d:.1f}", k, d

def send_telegram(text, img_path):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    with open(img_path, 'rb') as f:
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})

def main():
    for sym in STOCKS + ETFS:
        try:
            df = yf.download(sym, period="1y", interval="1d")
            if df.empty: continue
            df['MA20'], df['MA60'] = df['Close'].rolling(20).mean(), df['Close'].rolling(60).mean()
            kd_text, k, d = get_weekly_status(df)
            
            # 條件：週線轉折 OR 5日前帶量突破且目前站穩
            vol_check = df['Volume'].iloc[-5] > df['Volume'].iloc[-15:-5].mean() * 1.5
            stay_above = (df['Close'].iloc[-5:] > df['MA20'].iloc[-5:]).all() or (df['Close'].iloc[-5:] > df['MA60'].iloc[-5:]).all()
            
            if ("叉" in kd_text) or (vol_check and stay_above):
                img_name = f"{sym}.png"
                title = f"{sym} MA20:{df['MA20'].iloc[-1]:.1f} MA60:{df['MA60'].iloc[-1]:.1f}"
                apds = [mpf.make_addplot(df['MA20'].tail(40), color='blue'), mpf.make_addplot(df['MA60'].tail(40), color='orange')]
                mpf.plot(df.tail(40), type='candle', addplot=apds, title=title, savefig=img_name)
                
                msg = f"🔔 *標的: {sym}*\n週線: {kd_text}\n支撐: MA20={df['MA20'].iloc[-1]:.1f}"
                send_telegram(msg, img_name)
                os.remove(img_name)
        except: continue

if __name__ == "__main__":
    main()
