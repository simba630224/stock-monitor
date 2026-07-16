import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import os
import time
import json
import matplotlib
matplotlib.use('Agg') # 確保在伺服器端無 UI 環境下能正確繪圖
import mplfinance as mpf
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')

# --- 2. 輔助與技術指標函式 ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith(('.TW', '.TWO')): return ticker
    return f"{ticker}.TWO" if (ticker.endswith(('B', 'C')) or ticker == '009815') else f"{ticker}.TW"

def load_csv_list(url, is_tw=True):
    try:
        if not url: return [] if is_tw else {}
        response = requests.get(url, timeout=30)
        df = pd.read_csv(io.StringIO(response.text), on_bad_lines='skip')
        df.columns = [str(c).strip().replace('\ufeff', '').lower() for c in df.columns]
        
        data = [] if is_tw else {}
        for _, row in df.iterrows():
            row_dict = {str(k).strip().lower(): v for k, v in row.items()}
            ticker = str(row_dict.get('ticker') or '').strip()
            name = str(row_dict.get('名稱') or row_dict.get('name') or '').strip()
            if not ticker or ticker.lower() == 'nan': continue
            display_name = name if name and name != 'nan' else ticker
            
            if is_tw:
                data.append({'symbol': get_yf_ticker_tw(ticker), 'name': display_name})
            else:
                data[ticker] = display_name
        return data
    except Exception as e:
        print(f"❌ 讀取 CSV 錯誤: {e}")
        return [] if is_tw else {}

def process_target(sym, name, category):
    try:
        df = yf.download(sym, period="1y", progress=False, threads=False) 
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Open', 'High', 'Low', 'Close']].dropna()
        if len(df) < 60: return None
        
        last_p = df['Close'].iloc[-1]
        
        # --- 指標計算 ---
        # 日線 KD
        low_min = df['Low'].rolling(9, min_periods=1).min()
        high_max = df['High'].rolling(9, min_periods=1).max()
        rsv = (df['Close'] - low_min) / (high_max - low_min + 1e-9) * 100
        df['K_d'] = rsv.ewm(com=2, adjust=False).mean()
        df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
        
        # 日線 MACD
        df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        # 週線資料重採樣
        df_w = df.resample('W-FRI').agg({'Open':'first', 'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        if len(df_w) >= 2:
            low_min_w = df_w['Low'].rolling(9, min_periods=1).min()
            high_max_w = df_w['High'].rolling(9, min_periods=1).max()
            rsv_w = (df_w['Close'] - low_min_w) / (high_max_w - low_min_w + 1e-9) * 100
            df_w['K_w'] = rsv_w.ewm(com=2, adjust=False).mean()
            df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
            
            df_w['EMA12'] = df_w['Close'].ewm(span=12, adjust=False).mean()
            df_w['EMA26'] = df_w['Close'].ewm(span=26, adjust=False).mean()
            df_w['MACD'] = df_w['EMA12'] - df_w['EMA26']
            df_w['MACD_Signal'] = df_w['MACD'].ewm(span=9, adjust=False).mean()
        else:
            df_w = pd.DataFrame(columns=['K_w', 'D_w', 'MACD', 'MACD_Signal'])
        
        # --- 判斷金叉與死叉 ---
        def is_gold(fast, slow):
            if len(fast) < 2: return False
            return (fast.iloc[-1] > slow.iloc[-1]) and (fast.iloc[-2] <= slow.iloc[-2])
            
        def is_death(fast, slow):
            if len(fast) < 2: return False
            return (fast.iloc[-1] < slow.iloc[-1]) and (fast.iloc[-2] >= slow.iloc[-2])

        w_macd_gold = is_gold(df_w['MACD'], df_w['MACD_Signal']) if not df_w.empty else False
        w_kd_gold = is_gold(df_w['K_w'], df_w['D_w']) if not df_w.empty else False
        d_macd_gold = is_gold(df['MACD'], df['MACD_Signal'])
        d_kd_gold = is_gold(df['K_d'], df['D_d'])

        w_macd_death = is_death(df_w['MACD'], df_w['MACD_Signal']) if not df_w.empty else False
        w_kd_death = is_death(df_w['K_w'], df_w['D_w']) if not df_w.empty else False
        d_macd_death = is_death(df['MACD'], df['MACD_Signal'])
        d_kd_death = is_death(df['K_d'], df['D_d'])
        
        # --- 判斷破線 (跌破季線) ---
        season_len = 60 if category == '台股' else 50
        df['MA_season'] = df['Close'].rolling(season_len).mean()
        is_break = False
        if len(df) >= 2 and pd.notna(df['MA_season'].iloc[-2]):
            is_break = (df['Close'].iloc[-1] < df['MA_season'].iloc[-1]) and (df['Close'].iloc[-2] >= df['MA_season'].iloc[-2])

        # --- 取得本益比 ---
        try:
            info = yf.Ticker(sym).info
            pe = info.get('trailingPE') or info.get('forwardPE', 999)
        except:
            pe = 999
            
        # --- 生成精準標籤 ---
        tags = []
        if w_macd_gold: tags.append("週MACD金叉")
        if w_kd_gold: tags.append("週KD金叉")
        if d_macd_gold: tags.append("日MACD金叉")
        if d_kd_gold: tags.append("日KD金叉")
        
        if w_macd_death: tags.append("週MACD死叉")
        if w_kd_death: tags.append("週KD死叉")
        if d_macd_death: tags.append("日MACD死叉")
        if d_kd_death: tags.append("日KD死叉")
        if is_break: tags.append("破季線")

        # --- 技術面評分 (權重：週>日, MACD>KD) ---
        bull_score = (w_macd_gold * 4) + (w_kd_gold * 3) + (d_macd_gold * 2) + (d_kd_gold * 1)
        bear_score = (w_macd_death * 4) + (w_kd_death * 3) + (d_macd_death * 2) + (d_kd_death * 1) + (is_break * 1)
        
        return {
            'sym': sym, 'name': name, 'category': category, 
            'pe': pe, 'pe_str': f"{pe:.1f}" if pe != 999 else "無PE",
            'tags': tags, 'bull_score': bull_score, 'bear_score': bear_score,
            'last_p': last_p,
            'df': df.tail(100) # 儲存最近 100 天供後續畫圖使用
        }
    except Exception as e:
        print(f"❌ 處理 {sym} 時錯誤: {e}")
        return None

# --- 3. Telegram 傳送模組 ---
def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                  data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})

def send_tg_album(buffers, caption=""):
    if not TG_TOKEN or not TG_CHAT_ID or not buffers: return
    
    # 如果只有一張圖，需使用 sendPhoto API
    if len(buffers) == 1:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        files = {'photo': ('chart.png', buffers[0], 'image/png')}
        data = {'chat_id': TG_CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
        requests.post(url, data=data, files=files)
        return

    # 多張圖使用相簿 sendMediaGroup API
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMediaGroup"
    media = []
    files = {}
    for i, buf in enumerate(buffers):
        filename = f"image{i}.png"
        media_dict = {"type": "photo", "media": f"attach://{filename}"}
        if i == 0 and caption:
            media_dict["caption"] = caption
            media_dict["parse_mode"] = "HTML"
        media.append(media_dict)
        files[filename] = (filename, buf, 'image/png')
    
    data = {"chat_id": TG_CHAT_ID, "media": json.dumps(media)}
    requests.post(url, data=data, files=files)

# --- 4. 繪製技術線圖 ---
def generate_chart(item):
    try:
        df = item['df'].copy()
        
        # 計算繪圖所需指標
        macd = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        
        low_min = df['Low'].rolling(9, min_periods=1).min()
        high_max = df['High'].rolling(9, min_periods=1).max()
        rsv = (df['Close'] - low_min) / (high_max - low_min + 1e-9) * 100
        k = rsv.ewm(com=2, adjust=False).mean()
        d = k.ewm(com=2, adjust=False).mean()
        
        # 設定綠漲紅跌樣式 (配合台股習慣)
        mc = mpf.make_marketcolors(up='r', down='g', edge='inherit', wick='inherit', volume='in')
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle=':')
        
        macd_colors = ['r' if val >= 0 else 'g' for val in hist]
        
        # 添加附圖
        apds = [
            mpf.make_addplot(df['Close'].rolling(20).mean(), color='blue', width=1),
            mpf.make_addplot(k, panel=1, color='blue', ylabel='KD'),
            mpf.make_addplot(d, panel=1, color='orange'),
            mpf.make_addplot(macd, panel=2, color='blue', ylabel='MACD'),
            mpf.make_addplot(signal, panel=2, color='orange'),
            mpf.make_addplot(hist, type='bar', panel=2, color=macd_colors)
        ]
        
        # 繪圖並存入記憶體
        buf = io.BytesIO()
        title = f"{item['name']} ({item['sym']}) - {'+'.join(item['tags'])}"
        mpf.plot(df, type='candle', addplot=apds, figscale=1.0, figratio=(10, 8), 
                 title=title, style=s, savefig=dict(fname=buf, dpi=120, bbox_inches='tight'))
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"❌ 繪圖失敗 {item['name']}: {e}")
        return None

# --- 5. 主程式 ---
def main():
    TW_CORE = load_csv_list(SHEET_CSV_TW_URL, True)
    US_WATCH = load_csv_list(SHEET_CSV_US_URL, False)
    if not TW_CORE and not US_WATCH: return

    all_targets = [(item['symbol'], item['name'], '台股') for item in TW_CORE] + [(sym, name, '美股') for sym, name in US_WATCH.items()]
    
    # 存放分類結果
    categorized = {'台股': {'bull_strong':[], 'bull_daily':[], 'bear':[]}, 
                   '美股': {'bull_strong':[], 'bull_daily':[], 'bear':[]}}
    
    top_chart_candidates = [] # 收集所有可用於繪圖的強勢標的

    for sym, name, cat in all_targets:
        res = process_target(sym, name, cat)
        if not res: continue
        
        # 互斥分流與計分歸類
        if res['bear_score'] >= 3:
            categorized[cat]['bear'].append(res)
        elif res['bull_score'] >= 3:
            categorized[cat]['bull_strong'].append(res)
            top_chart_candidates.append(res)
        elif res['bear_score'] > 0:
            categorized[cat]['bear'].append(res)
        elif res['bull_score'] > 0:
            categorized[cat]['bull_daily'].append(res)
            top_chart_candidates.append(res)
            
        time.sleep(0.5) # 避免 API 頻率過高

    # --- 傳送文字摘要 ---
    send_tg_text("🚀 <b>盤後亮點摘要與警示 (Top 10)</b>")
    
    def format_items(items):
        if not items: return "無"
        return "\n".join([f"• <b>{x['name']} (PE:{x['pe_str']})</b>\n  └ <code>[{', '.join(x['tags'])}]</code>" for x in items])

    for cat in ['台股', '美股']:
        data = categorized[cat]
        # 排序：技術分數(降冪)優先，本益比(升冪)其次，取 Top 10
        b_strong = sorted(data['bull_strong'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        b_daily = sorted(data['bull_daily'], key=lambda x: (-x['bull_score'], x['pe']))[:10]
        bear = sorted(data['bear'], key=lambda x: (-x['bear_score'], x['pe']))[:10]
        
        if not b_strong and not b_daily and not bear: continue
        
        msg = f"📁 <b>【{cat}】技術掃描</b>\n\n"
        if b_strong: msg += f"🔥 <b>週線級別 (波段強勢區)</b>\n{format_items(b_strong)}\n\n"
        if b_daily: msg += f"📈 <b>日線級別 (短線轉折區)</b>\n{format_items(b_daily)}\n\n"
        if bear: msg += f"⚠️ <b>空方風險警示 (破線/死叉)</b>\n{format_items(bear)}\n"
        
        send_tg_text(msg)

    # --- 傳送 Top 3 技術線圖相簿 ---
    # 從所有強勢標的中，嚴選 Top 3
    top_chart_candidates = sorted(top_chart_candidates, key=lambda x: (-x['bull_score'], x['pe']))[:3]
    
    if top_chart_candidates:
        image_buffers = []
        chart_names = []
        for item in top_chart_candidates:
            buf = generate_chart(item)
            if buf:
                image_buffers.append(buf)
                chart_names.append(item['name'])
        
        if image_buffers:
            caption = f"📊 <b>本日最強勢 Top {len(image_buffers)} 技術線圖</b>\n" + ", ".join(chart_names)
            send_tg_album(image_buffers, caption)

    send_tg_text(f"🏁 <b>每日掃描完成 ({datetime.now().strftime('%Y/%m/%d')})</b>")

if __name__ == "__main__":
    main()
