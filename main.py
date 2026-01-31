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
    {'symbol': '00830.TW',  'name': '國泰費城半導體'},
    {'symbol': '00757.TW',  'name': '統一FANG+'},
    {'symbol': '009812.TW', 'name': '日本指數'},
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'MSFT',      'name': 'MSFT'},
    {'symbol': 'GOOGL',     'name': 'GOOGLE'},
    {'symbol': 'QQQ',       'name': '那斯達克ETF'},
    {'symbol': 'VOO',       'name': 'S&P500 ETF'},
    {'symbol': 'VT',        'name': 'World ETF'},
]

def send_telegram(text, img_path=None):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 錯誤：找不到環境變數 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")
        return
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            with open(img_path, 'rb') as f:
                r = requests.post(f"{url_base}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            r = requests.post(f"{url_base}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
        
        if r.status_code != 200:
            print(f"❌ Telegram 發送失敗: {r.text}")
    except Exception as e:
        print(f"❌ Telegram 連線異常: {e}")

def get_full_analysis(symbol):
    try:
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        
        # 1. 指標計算
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        
        # MACD (日線)
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)
        
        # 週線 KD
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        
        # 2. 數據提取
        return {
            'df': df, 'price': df['Close'].iloc[-1], 
            'change': (df['Close'].iloc[-1]/df['Close'].iloc[-2]-1)*100,
            'k': kd.iloc[-1]['STOCHk_9_3_3'], 'd': kd.iloc[-1]['STOCHd_9_3_3'],
            'pk': kd.iloc[-2]['STOCHk_9_3_3'], 'pd': kd.iloc[-2]['STOCHd_9_3_3'],
            'macd_h': df['MACDh_12_26_9'].iloc[-1],
            'vol_break': df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5,
            'stay_ma20': (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
        }
    except: return None

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"=== 偵錯模式啟動: {report_date} ===")
    
    # --- 強制連線測試 ---
    send_telegram(f"🚀 *機器人連線測試*\n時間: {report_date}\n如果看到此訊息，代表連線正常！")

    summary = {'gold': [], 'dead': [], 'breakout': []}
    
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        data = get_full_analysis(sym)
        if not data:
            print(f"❌ 警告: {sym} 無法取得數據")
            continue
        
        # 判斷趨勢
        sig = "持穩"
        if data['k'] > data['d'] and data['pk'] <= data['pd']:
            summary['gold'].append(f"{name}({sym})")
            sig = "🔥週KD金叉"
        elif data['k'] < data['d'] and data['pk'] >= data['pd']:
            summary['dead'].append(f"{name}({sym})")
            sig = "❄️週KD死叉"
        if data['vol_break'] and data['stay_ma20']: summary['breakout'].append(name)

        # 繪圖 (含 MACD 柱狀圖)
        img_name = f"{sym}.png"
        colors = ['red' if x > 0 else 'green' for x in data['df']['MACDh_12_26_9'].tail(60)]
        apds = [
            mpf.make_addplot(data['df']['MA20'].tail(60), color='blue', width=0.8),
            mpf.make_addplot(data['df']['MA60'].tail(60), color='orange', width=0.8),
            mpf.make_addplot(data['df']['MACDh_12_26_9'].tail(60), type='bar', panel=1, color=colors, secondary_y=False)
        ]
        mpf.plot(data['df'].tail(60), type='candle', style='charles', addplot=apds, title=f"{name}", savefig=img_name, panel_ratios=(3,1))
        
        caption = f"📈 *{name} ({sym})*\n現價: `{data['price']:.2f}` ({data['change']:+.2f}%)\n指標: {sig}\nMACD柱: `{data['macd_h']:.2f}`"
        send_telegram(caption, img_name)
        if os.path.exists(img_name): os.remove(img_name)

    # --- 最終彙整報告 ---
    report = (
        f"【{report_date} 台股深度篩選分析報告】\n"
        f"一、 市值百大與核心標的：技術指標監測\n"
        f"🔹 *週 KD 金叉*: {', '.join(summary['gold']) if summary['gold'] else '無'}\n"
        f"🔸 *週 KD 死叉*: {', '.join(summary['dead']) if summary['dead'] else '無'}\n"
        f"🚀 *強勢回測站穩*: {', '.join(summary['breakout']) if summary['breakout'] else '無'}\n\n"
        f"二、 總結與提醒\n目前 WATCH_LIST 標的已分析完畢。請留意 MACD 柱狀圖縮放情況與週線支撐。報告完畢。"
    )
    send_telegram(report)

if __name__ == "__main__":
    main()
