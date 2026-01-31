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

# 標的名單
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
    """發送訊息至 Telegram 的核心函式"""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 錯誤：找不到 TOKEN 或 CHAT_ID")
        return
    
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path and os.path.exists(img_path):
            files = {'photo': open(img_path, 'rb')}
            data = {'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}
            requests.post(f"{url_base}/sendPhoto", data=data, files=files)
        else:
            data = {'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'}
            requests.post(f"{url_base}/sendMessage", data=data)
    except Exception as e:
        print(f"❌ Telegram 連線異常: {e}")

def get_data_and_analyze(symbol):
    """抓取數據並執行技術分析"""
    try:
        # 下載 2 年數據
        df = yf.download(symbol, period="2y", interval="1d", progress=False)
        if df.empty or len(df) < 60:
            return None
        
        # 修正 yfinance 多層索引問題
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
        
        # 提取最新數據
        last_row = df.iloc[-1]
        last_week = kd.iloc[-1]
        prev_week = kd.iloc[-2]
        
        # 強勢回測判定 (5日前爆量且目前連5日站穩 MA20)
        vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
        stay_ma20 = (df['Close'].iloc[-5:] >= df['MA20'].iloc[-5:]).all()
        
        return {
            'df': df,
            'price': last_row['Close'],
            'change': (last_row['Close'] / df['Close'].iloc[-2] - 1) * 100,
            'k': last_week['STOCHk_9_3_3'],
            'd': last_week['STOCHd_9_3_3'],
            'pk': prev_week['STOCHk_9_3_3'],
            'pd': prev_week['STOCHd_9_3_3'],
            'macd_h': last_row['MACDh_12_26_9'],
            'vol_break': vol_break,
            'stay_ma20': stay_ma20
        }
    except Exception as e:
        print(f"⚠️ {symbol} 數據處理錯誤: {e}")
        return None

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"=== 啟動分析任務: {report_date} ===")
    
    # 1. 發送啟動通知
    send_telegram(f"🔔 *盤前分析系統啟動* ({report_date})")
    
    # 2. 初始化統計清單
    summary = {'gold': [], 'dead': [], 'breakout': []}
    
    # 3. 逐一處理名單 (並發送個股線圖)
    for item in WATCH_LIST:
        sym = item['symbol']
        name = item['name']
        print(f"正在分析: {name} ({sym})")
        
        data = get_data_and_analyze(sym)
        if not data:
            continue
            
        # 指標判定
        status_txt = "整理"
        if data['k'] > data['d'] and data['pk'] <= data['pd']:
            summary['gold'].append(f"{name}({sym})")
            status_txt = "🔥週KD金叉"
        elif data['k'] < data['d'] and data['pk'] >= data['pd']:
            summary['dead'].append(f"{name}({sym})")
            status_txt = "❄️週KD死叉"
        
        if data['vol_break'] and data['stay_ma20']:
            summary['breakout'].append(f"{name}({sym})")

        # 繪圖 (含 MACD 柱狀圖)
        img_name = f"temp_{sym.replace('.', '_')}.png"
        df_plot = data['df'].tail(60)
        
        # MACD 柱狀顏色 (紅漲綠跌)
        macd_colors = ['red' if val > 0 else 'green' for val in df_plot['MACDh_12_26_9']]
        
        apds = [
            mpf.make_addplot(df_plot['MA20'], color='blue', width=0.8),
            mpf.make_addplot(df_plot['MA60'], color='orange', width=0.8),
            mpf.make_addplot(df_plot['MACDh_12_26_9'], type='bar', panel=1, color=macd_colors, secondary_y=False)
        ]
        
        mpf.plot(df_plot, type='candle', style='charles', addplot=apds, 
                 title=f"{name} ({sym})", savefig=img_name, panel_ratios=(3,1))
        
        # 發送個股報告
        caption = (
            f"📈 *標的分析：{name}*\n"
            f"現價: `{data['price']:.2f}` ({data['change']:+.1f}%)\n"
            f"週KD: {data['k']:.1f} / {data['d']:.1f} ({status_txt})\n"
            f"MACD柱: `{data['macd_h']:.2f}`"
        )
        send_telegram(caption, img_name)
        
        # 刪除暫存圖檔
        if os.path.exists(img_name):
            os.remove(img_name)

    # 4. 生成最終長篇彙整報告
    print("正在生成彙整報告...")
    
    report_text = f"【{report_date} 台股深度篩選分析報告】\n"
    report_text += "本報告聚焦於市場龍頭與高流動性標的，結合週線趨勢與量價回測。\n\n"
    
    report_text += "一、 市值百大與核心標的：技術指標監測\n"
    report_text += "監測「週線」級別的 KD 變化，捕捉中長線趨勢轉折。\n\n"
    
    report_text += "🔹 週 KD 金叉 (轉強)：\n" + (", ".join(summary['gold']) if summary['gold'] else "無") + "\n\n"
    report_text += "🔸 週 KD 死叉 (警戒)：\n" + (", ".join(summary['dead']) if summary['dead'] else "無") + "\n\n"
    
    report_text += "🚀 強勢回測名單 (5 日前帶量突破 + 站穩支撐)：\n"
    if summary['breakout']:
        for b in summary['breakout']:
            report_text += f"- {b}：確認站穩 MA20，符合量縮守支撐特徵。\n"
    else:
        report_text += "今日無顯著符合標的。\n"
    
    report_text += "\n二、 總結與提醒\n"
    report_text += "標的名單分析已完成。若個股出現「週KD死叉」且跌破月線 MA20，建議檢視風險控管。報告完畢。"
    
    send_telegram(report_text)
    print("=== 全部分析任務完成 ===")

if __name__ == "__main__":
    main()
