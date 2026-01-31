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

# 您指定的監控清單
WATCH_LIST = [
    # --- 台股 ---
    {'symbol': '2330.TW',   'name': '台積電'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '元大台灣50'},
    {'symbol': '00830.TW',  'name': '國泰費城半導體'},
    {'symbol': '00757.TW',  'name': '統一FANG+'},
    {'symbol': '009812.TW', 'name': '日本指數'},
    
    # --- 美股 ---
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'MSFT',      'name': 'MSFT'},
    {'symbol': 'GOOGL',     'name': 'GOOGLE'},
    {'symbol': 'QQQ',       'name': '那斯達克ETF'},
    {'symbol': 'VOO',       'name': 'S&P500 ETF'},
    {'symbol': 'VT',        'name': 'World ETF'},
]

def get_stock_data(symbol):
    """抓取數據、修復格式並計算技術指標"""
    try:
        # 下載 2 年數據以穩定計算週線 KD
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty: return None
        
        # 修正 yfinance MultiIndex 問題
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        
        # 1. 日線均線
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        
        # 2. 週線轉換與指標
        df_w = df.resample('W-FRI').agg({
            'Open':'first', 'High':'max', 'Low':'min', 'Close':'last', 'Volume':'sum'
        }).dropna()
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        k, d = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3']
        pk, pd_val = kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
        
        # 3. 強勢回測偵測 (5日前量增 1.5 倍且目前連 5 日站穩 MA20)
        # 5日前索引為 -6
        vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
        stay_ma20 = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
        
        return {
            'df': df, 
            'price': df['Close'].iloc[-1], 
            'change': (df['Close'].iloc[-1] / df['Close'].iloc[-2] - 1) * 100,
            'k': k, 'd': d, 'pk': pk, 'pd': pd_val,
            'vol_break': vol_break, 'stay_ma20': stay_ma20,
            'ma20': df['MA20'].iloc[-1], 'ma60': df['MA60'].iloc[-1]
        }
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def send_to_telegram(text, img_path=None):
    """發送訊息或圖片到 Telegram"""
    if not TG_TOKEN or not TG_CHAT_ID: return
    base_url = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            url = f"{base_url}/sendPhoto"
            with open(img_path, 'rb') as f:
                requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            url = f"{base_url}/sendMessage"
            requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e:
        print(f"Telegram發送異常: {e}")

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"--- 啟動盤前分析報告: {report_date} ---")
    
    # 儲存報告分類結果
    results = {'gold': [], 'dead': [], 'breakout': []}
    
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        data = get_stock_data(sym)
        if not data: continue
        
        # A. 判斷週線趨勢
        status_txt = "趨勢中"
        if data['k'] > data['d'] and data['pk'] <= data['pd']:
            results['gold'].append(f"{name}({sym})")
            status_txt = "🔥週線金叉"
        elif data['k'] < data['d'] and data['pk'] >= data['pd']:
            results['dead'].append(f"{name}({sym})")
            status_txt = "❄️週線死叉"
            
        # B. 判斷強勢回測 (僅針對百大標的)
        if data['vol_break'] and data['stay_ma20']:
            results['breakout'].append(f"{name}({sym})：1/21帶量突破且目前站穩MA20")

        # C. 繪圖並發送個股狀態
        img_name = f"{sym}.png"
        apds = [
            mpf.make_addplot(data['df']['MA20'].tail(60), color='blue', width=0.8), 
            mpf.make_addplot(data['df']['MA60'].tail(60), color='orange', width=0.8)
        ]
        mpf.plot(data['df'].tail(60), type='candle', style='charles', addplot=apds, 
                 title=f"{name} ({sym})", savefig=img_name)
        
        caption = (
            f"📊 *{name} ({sym})*\n"
            f"💰 收盤: `{data['price']:.2f}` ({data['change']:+.2f}%)\n"
            f"📈 指標: {status_txt}\n"
            f"📏 週線 KD: K={data['k']:.1f} / D={data['d']:.1f}\n"
            f"🛡️ 支撐: MA20={data['ma20']:.1f}"
        )
        send_to_telegram(caption, img_name)
        if os.path.exists(img_name): os.remove(img_name)

    # --- D. 組合最終總結報告 ---
    report = f"【{report_date} 台股深度篩選分析報告】\n"
    report += "根據您的設定，本報告聚焦於市場龍頭與高流動性標的，並透過週線級別（中長期趨勢）與量價形態進行篩選。\n\n"
    
    report += "一、 市值百大個股：週線技術指標監測\n"
    report += "監測「週線」級別的 KD 變化，並觀察突破後回測之強勢標的。\n\n"
    
    report += f"🔹 *週 KD 黃金交叉 (轉強)*：\n{', '.join(results['gold']) if results['gold'] else '今日無'}\n\n"
    report += f"🔸 *週 KD 死亡交叉 (警戒)*：\n{', '.join(results['dead']) if results['dead'] else '今日無'}\n\n"
    
    report += "🚀 *強勢回測名單 (5 日前帶量突破 + 站穩支撐)*：\n"
    report += "\n".join(results['breakout']) if results['breakout'] else "今日無顯著回測標的"
    
    report += "\n\n二、 總結與提醒\n"
    report += "目前核心標的的週線趨勢仍是關鍵。若個股出現「死亡交叉」且跌破月線 MA20，應留意風險控管。報告完畢。"
    
    send_to_telegram(report)

if __name__ == "__main__":
    main()
