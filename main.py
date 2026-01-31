import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 配置設定 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 您指定的監控清單
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

def get_stock_data(symbol):
    """下載數據並計算指標"""
    try:
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty: return None
        # 修正 MultiIndex 問題
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        
        # 均線
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        
        # 週線計算
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        k, d = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3']
        pk, pd_val = kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
        
        # 突破偵測 (5日前量增且站穩)
        vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
        stay_ma20 = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
        
        return {
            'df': df, 'price': df['Close'].iloc[-1], 'change': (df['Close'].iloc[-1]/df['Close'].iloc[-2]-1)*100,
            'k': k, 'd': d, 'pk': pk, 'pd': pd_val,
            'vol_break': vol_break, 'stay_ma20': stay_ma20,
            'ma20': df['MA20'].iloc[-1], 'ma60': df['MA60'].iloc[-1]
        }
    except: return None

def send_to_telegram(text, img_path=None):
    base_url = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            with open(img_path, 'rb') as f:
                requests.post(f"{base_url}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"{base_url}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e: print(f"Telegram Error: {e}")

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"--- 開始盤前分析 {report_date} ---")
    
    results = {'gold': [], 'dead': [], 'breakout': []}
    
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        data = get_stock_data(sym)
        if not data: continue
        
        # 分類邏輯
        status_txt = ""
        if data['k'] > data['d'] and data['pk'] <= data['pd']:
            results['gold'].append(f"{name}({sym})")
            status_txt = "🔥週線金叉"
        elif data['k'] < data['d'] and data['pk'] >= data['pd']:
            results['dead'].append(f"{name}({sym})")
            status_txt = "❄️週線死叉"
            
        if data['vol_break'] and data['stay_ma20']:
            results['breakout'].append(f"{name}({sym})：站穩月線續強")

        # 繪圖並發送
        img_file = f"{sym}.png"
        apds = [mpf.make_addplot(data['df']['MA20'].tail(60), color='blue'), 
                mpf.make_addplot(data['df']['MA60'].tail(60), color='orange')]
        mpf.plot(data['df'].tail(60), type='candle', style='charles', addplot=apds, title=f"{name} ({sym})", savefig=img_file)
        
        cap = f"📊 *{name} ({sym})*\n收盤: `{data['price']:.2f}` ({data['change']:+.2f}%)\n指標: {status_txt or '趨勢中'}\n週K: {data['k']:.1f} / D: {data['d']:.1f}\nMA20: {data['ma20']:.1f}"
        send_to_telegram(cap, img_file)
        if os.path.exists(img_file): os.remove(img_file)

    # --- 組合最終彙整報告 ---
    report = f"【{report_date} 全球市場盤前深度篩選】\n"
    report += "一、 市值百大與核心標的：技術指標監測\n"
    report += f"🔹 *週 KD/MACD 金叉轉強*：\n{', '.join(results['gold']) if results['gold'] else '無'}\n"
    report += f"🔸 *週 KD/MACD 死叉警戒*：\n{', '.join(results['dead']) if results['dead'] else '無'}\n"
    report += f"🚀 *強勢突破回測站穩*：\n{', '.join(results['breakout']) if results['breakout'] else '無符合標的'}\n\n"
    
    report += "二、 總結與提醒\n本報告聚焦於 WATCH_LIST 核心標的。若週線死叉且跌破 MA20，建議檢視風險。報告完畢。"
    
    send_to_telegram(report)

if __name__ == "__main__":
    main()
