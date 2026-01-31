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
    """發送訊息至 Telegram"""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 環境變數缺失")
        return
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            url = f"{url_base}/sendPhoto"
            with open(img_path, 'rb') as f:
                r = requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            url = f"{url_base}/sendMessage"
            r = requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
        
        if r.status_code != 200:
            print(f"❌ Telegram 發送失敗: {r.text}")
    except Exception as e:
        print(f"❌ Telegram 連線異常: {e}")

def get_full_analysis(symbol):
    """抓取數據並分析指標"""
    try:
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty or len(df) < 60:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        
        # 均線與 MACD
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()
        macd = ta.macd(df['Close'])
        df = pd.concat([df, macd], axis=1)
        
        # 週線 KD
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        
        # 強勢回測判定
        vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
        stay_ma20 = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
        
        return {
            'df': df, 
            'price': df['Close'].iloc[-1], 
            'change': (df['Close'].iloc[-1]/df['Close'].iloc[-2]-1)*100,
            'k': kd.iloc[-1]['STOCHk_9_3_3'], 
            'd': kd.iloc[-1]['STOCHd_9_3_3'],
            'pk': kd.iloc[-2]['STOCHk_9_3_3'], 
            'pd': kd.iloc[-2]['STOCHd_9_3_3'],
            'macd_h': df['MACDh_12_26_9'].iloc[-1],
            'vol_break': vol_break, 
            'stay_ma20': stay_ma20
        }
    except Exception as e:
        print(f"解析 {symbol} 出錯: {e}")
        return None

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"=== 分析開始: {report_date} ===")
    
    # 測試連線
    send_telegram(f"🔔 *盤前分析啟動* ({report_date})")

    summary = {'gold': [], 'dead': [], 'breakout': []}
    
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print(f"正在分析: {name} ({sym})")
        data = get_full_analysis(sym)
        
        if not data:
            print(f"   ⚠️ {sym} 數據取得失敗")
            continue
        
        # 趨勢判定
        sig = "橫盤"
        if data['k'] > data['d'] and data['pk'] <= data['pd']:
            summary['gold'].append(f"{name}({sym})")
            sig = "🔥週KD金叉"
        elif data['k'] < data['d'] and data['pk'] >= data['pd']:
            summary['dead'].append(f"{name}({sym})")
            sig = "❄️週KD死叉"
        
        if data['vol_break'] and data['stay_ma20']:
            summary['breakout'].append(f"{name}({sym})")

        # 繪製線圖 (含 MACD 柱狀圖)
        img_name = f"{sym.replace('.', '_')}.png"
        colors = ['red' if x > 0 else 'green' for x in data['df']['MACDh_12_26_9'].tail(60)]
        apds = [
            mpf.make_addplot(data['df']['MA20'].tail(60), color='blue', width=0.8),
            mpf.make_addplot(data['df']['MA60'].tail(60), color='orange', width=0.8),
            mpf.make_addplot(data['df']['MACDh_12_26_9'].tail(60), type='bar', panel=1, color=colors, secondary_y=False)
        ]
        mpf.plot(data['df'].tail(60), type='candle', style='charles', addplot=apds, title=f"{name}", savefig=img_name, panel_ratios=(3,1))
        
        caption = f"📈 *{name} ({sym})*\n價位: `{data['price']:.2f}` ({data['change']:+.1f}%)\n指標: {sig}\nMACD柱: `{data['macd_h']:.2f}`"
        send_telegram(caption, img_name)
        
        if os.path.exists(img_name):
            os.remove(img_name)
        print(f"   ✅ {sym} 發送完成")

    # 彙整報告內容
    report_text = f"【{report_date} 全球標的分析彙整】\n\n"
    report_text += "一、 市值百大與核心標的：指標監測\n"
    report_text += f"🔹 *週 KD 金叉*: {', '.join(summary['gold']) if summary['gold'] else '無'}\n"
    report_text += f"🔸 *週 KD 死叉*: {', '.join(summary['dead']) if summary['dead'] else '無'}\n"
    report_text += f"🚀 *強勢突破站穩*: {', '.join(summary['breakout']) if summary['breakout'] else '無'}\n\n"
    report_text += "二、 總結\n標的掃描已完成，請留意圖表 MACD 柱狀體之縮放。報告完畢。"
    
    send_telegram(report_text)
    print("=== 分析任務全部完成 ===")

if __name__ == "__main__":
    main()
