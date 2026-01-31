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
    {'symbol': 'VT',        'name': 'World ETF'},
]

def send_telegram(text, img_path=None):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            with open(img_path, 'rb') as f:
                r = requests.post(f"{url_base}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            r = requests.post(f"{url_base}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e: print(f"❌ Telegram 發送失敗: {e}")

def get_full_analysis(symbol):
    try:
        # 修正：強制指定下載長度，並加上自動修正
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty or len(df) < 60: return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        
        # 指標計算
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)
        
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        
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
    print(f"=== 分析開始: {report_date} ===")
    
    # 1. 測試連線
    send_telegram(f"📡 盤前自動化診斷：{report_date} 資料處理中...")

    summary = {'gold': [], 'dead': [], 'breakout': []}
    
    # 2. 逐一處理標的
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print(f"正在分析: {name} ({sym})...")
        data = get_full_analysis(sym)
        
        if not data:
            print(f"   ⚠️ {sym} 數據取得失敗")
            continue
        
        # 趨勢判定
        sig = "橫盤"
        if data['k'] > data['d'] and data['pk'] <= data['pd']:
            summary['gold'].append(f"{name}({sym})"); sig = "🔥週KD金叉"
        elif data['k'] < data['d'] and data['pk'] >= data['pd']:
            summary['dead'].append(f"{name}({sym})"); sig = "❄️週KD死叉"
        if data['vol_break'] and data['stay_ma20']: summary['breakout'].append(name)

        # 3. 繪圖 (含 MACD)
        img_name = f"{sym}.png"
        colors = ['red' if x > 0 else 'green' for x in data['df']['MACDh_12_26_9'].tail(60)]
        apds = [
            mpf.make_addplot(data['df']['MA20'].tail(60), color='blue', width=0.8),
            mpf.make_addplot(data['df']['MA60'].tail(60), color='orange', width=0.8),
            mpf.make_addplot(data['df']['MACDh_12_26_9'].tail(60), type='bar', panel=1, color=colors, secondary_y=False)
        ]
        mpf.plot(data['df'].tail(60), type='candle', style='charles', addplot=apds, title=f"{name}", savefig=img_name, panel_ratios=(3,1))
        
        caption = f"📈 *{name} ({sym})*\n價位: `{data['price']:.2f}` ({data['change']:+.1f}%)\n狀態: {sig}\nMACD柱: `{data['macd_h']:.2f}`"
        send_telegram(caption, img_name)
        if os.path.exists(img_name): os.remove(img_name)
        print(f"   ✅ {sym} 發送成功")

    # 4. 彙整總報告
    report = (
        f"【{report_date} 全球標的分析彙整】\n"
        f"一、 市值百大與核心標的：指標監測\n"
        f"🔹 *週 KD 金叉*: {', '.join(summary['gold']) if summary['gold'] else '無'}\n"
        f"🔸 *週 KD 死叉*: {', '.join(summary['dead']) if summary['dead'] else '無'}\n"
        f"🚀 *強勢突破站穩*: {', '.join(summary['breakout']) if summary['breakout'] else '無'}\n\n"
        f"二、 總結\n標的掃描已完成，請留意圖表中 MACD 柱狀體之縮放。報告完畢。"
    )
    send_telegram(report)
    print("=== 全部分析任務完成 ===")

if __name__ == "__main__":
    main()
