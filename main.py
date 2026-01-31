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

def get_stock_analysis(symbol):
    """抓取數據並執行技術面分析"""
    try:
        # 下載 2 年數據以確保週線指標與均線計算精確
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty: return None
        
        # 修正 yfinance MultiIndex 問題
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        
        # 1. 均線計算
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        
        # 2. 週線指標 (KD 與 MACD)
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        macd = ta.macd(df_w['Close'])
        
        k, d = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3']
        pk, pd_val = kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
        m_hist = macd.iloc[-1]['MACDh_12_26_9']
        pm_hist = macd.iloc[-2]['MACDh_12_26_9']
        
        # 3. 強勢回測偵測 (5日前量增 1.5 倍且目前連 5 日站穩 MA20)
        vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
        stay_ma20 = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
        
        return {
            'df': df, 'price': df['Close'].iloc[-1], 
            'change': (df['Close'].iloc[-1]/df['Close'].iloc[-2]-1)*100,
            'k': k, 'd': d, 'pk': pk, 'pd': pd_val,
            'm_hist': m_hist, 'pm_hist': pm_hist,
            'vol_break': vol_break, 'stay_ma20': stay_ma20,
            'ma20': df['MA20'].iloc[-1], 'ma60': df['MA60'].iloc[-1]
        }
    except: return None

def send_telegram(text, img_path=None):
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            with open(img_path, 'rb') as f:
                requests.post(f"{url_base}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"{url_base}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e: print(f"Telegram Error: {e}")

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"=== 啟動深度分析: {report_date} ===")
    
    # 統計彙整
    summary = {'gold': [], 'dead': [], 'breakout': []}
    
    # --- 第一階段：逐一掃描並發送線圖分析 ---
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        data = get_stock_analysis(sym)
        if not data: continue
        
        # 判斷信號
        signal_txt = "持穩"
        if data['k'] > data['d'] and data['pk'] <= data['pd']:
            summary['gold'].append(f"{name}({sym})")
            signal_txt = "🔥週KD金叉"
        elif data['k'] < data['d'] and data['pk'] >= data['pd']:
            summary['dead'].append(f"{name}({sym})")
            signal_txt = "❄️週KD死叉"
            
        if data['vol_break'] and data['stay_ma20']:
            summary['breakout'].append(f"{name}({sym})")

        # 繪製線圖 (MA20藍, MA60橘)
        img_name = f"{sym}.png"
        apds = [mpf.make_addplot(data['df']['MA20'].tail(60), color='blue', width=0.8),
                mpf.make_addplot(data['df']['MA60'].tail(60), color='orange', width=0.8)]
        mpf.plot(data['df'].tail(60), type='candle', style='charles', addplot=apds, title=f"{name} ({sym})", savefig=img_name)
        
        # 個股訊息
        caption = (
            f"📈 *標的分析：{name} ({sym})*\n"
            f"💰 收盤價: `{data['price']:.2f}` ({data['change']:+.2f}%)\n"
            f"📊 週線指標: {signal_txt} (K:{data['k']:.1f}/D:{data['d']:.1f})\n"
            f"🛡️ 支撐水位: MA20=`{data['ma20']:.1f}` / MA60=`{data['ma60']:.1f}`"
        )
        send_telegram(caption, img_name)
        if os.path.exists(img_name): os.remove(img_name)

    # --- 第二階段：組合最終深度分析長報告 ---
    report = f"【{report_date} 台股深度篩選分析報告】\n"
    report += "根據您的設定，本報告聚焦於市場龍頭與高流動性標的，並透過週線級別（中長期趨勢）與量價形態進行篩選。\n\n"
    
    report += "一、 市值百大與核心標的：技術指標監測\n"
    report += "針對標的名單監測「週線」級別的 KD 變化，捕捉中長線趨勢轉折，並追蹤突破後之回測表現。\n\n"
    
    report += f"🔹 *週 KD 黃金交叉 (轉強)*：\n{', '.join(summary['gold']) if summary['gold'] else '今日無'}\n\n"
    report
