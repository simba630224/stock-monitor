import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import time
import json
import traceback
import matplotlib
matplotlib.use('Agg') # 避免無頭伺服器繪圖報錯
import mplfinance as mpf
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- 2. 觀察清單更新 ---
TW_CORE = [
    # 台股權值股 Top 10 (純電子/半導體/網通/光電)
    {'symbol': '2330.TW', 'name': '台積電'},
    {'symbol': '2317.TW', 'name': '鴻海'},
    {'symbol': '2454.TW', 'name': '聯發科'},
    {'symbol': '2382.TW', 'name': '廣達'},
    {'symbol': '2308.TW', 'name': '台達電'},
    {'symbol': '3711.TW', 'name': '日月光投控'},
    {'symbol': '2303.TW', 'name': '聯電'},
    {'symbol': '6669.TW', 'name': '緯穎'},
    {'symbol': '3008.TW', 'name': '大立光'},
    {'symbol': '3231.TW', 'name': '緯創'},
    
    # 台股 ETF 
    {'symbol': '0050.TW', 'name': '元大台灣50'},
    {'symbol': '00878.TW', 'name': '國泰永續高股息'},
    {'symbol': '00713.TW', 'name': '元大台灣高息低波'},
    {'symbol': '00919.TW', 'name': '群益台灣精選高息'},
    {'symbol': '009812.TW', 'name': '野村日本東證ETF'},
    {'symbol': '00922.TW', 'name': '國泰台灣領袖50'},
    {'symbol': '00923.TW', 'name': '群益台灣ESG低碳'},
    {'symbol': '00830.TW', 'name': '國泰費城半導體'},
    {'symbol': '00981A.TW', 'name': '野村日本龍頭企業'},
    {'symbol': '00988A.TW', 'name': '復華日本龍頭'},
    {'symbol': '009815.TW', 'name': '野村日經225'}
]

US_WATCH = {
    'NVDA': '輝達 Nvidia',
    'MSFT': '微軟 Microsoft',
    'GOOGL': '谷歌 Google',
    'VOO': '標普500 VOO',
    'QQQ': '納斯達克 QQQ'
}

# --- 3. 輔助功能 ---
def analyze_ma_relation(price, ma_s1, ma_s2, ma_l1, ma_l2, market):
    short_term_name = "月/季線"
    status = ""
    if pd.notna(ma_s1) and pd.notna(ma_s2):
        if price > ma_s1 and price > ma_s2: status += f"🟢 站穩 {short_term_name} (強勢)"
        elif price < ma_s1 and price < ma_s2: status += f"🔴 位於 {short_term_name} 之下 (偏空)"
        elif price > ma_s2 and price < ma_s1: status += f"🟡 守住季線，受月線壓制"
        elif price > ma_s1 and price < ma_s2: status += f"🔵 站上月線，臨季線挑戰"
    else:
        status += "中短均線資料不足"
    status += " | "
    if pd.notna(ma_l1) and pd.notna(ma_l2):
        if price > ma_l1 and price > ma_l2: status += f"🟢 長線多頭"
        elif price < ma_l1 and price < ma_l2: status += f"🔴 長線空頭"
        elif price > ma_l2 and price < ma_l1: status += f"🟡 守年線，受半年線壓"
        elif price > ma_l1 and price < ma_l2: status += f"🔵 站半年線，臨年線壓"
    else:
        status += "長線均線資料不足"
    return status

def calculate_indicators(df, market):
    if market == '台股':
        df['MA_S1'] = df['Close'].rolling(20).mean()
        df['MA_S2'] = df['Close'].rolling(60).mean()
        df['MA_L1'] = df['Close'].rolling(120).mean()
        df['MA_L2'] = df['Close'].rolling(240).mean()
    else:
        df['MA_S1'] = df['Close'].rolling(20).mean()
        df['MA_S2'] = df['Close'].rolling(50).mean()
        df['MA_L1'] = df['Close'].rolling(100).mean()
        df['MA_L2'] = df['Close'].rolling(200).mean()
    ln_d = df['Low'].rolling(9).min()
    hn_d = df['High'].rolling(9).max()
    rsv_d = (df['Close'] - ln_d) / (hn_d - ln_d) * 100
    df['K_d'] = rsv_d.ewm(com=2, adjust=False).mean()
    df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    ln_w = df_w['Low'].rolling(9).min()
    hn_w = df_w['High'].rolling(9).max()
    rsv_w = (df_w['Close'] - ln_w) / (hn_w - ln_w) * 100
    df_w['K_w'] = rsv_w.ewm(com=2, adjust=False).mean()
    df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
    return df, df_w

def fmt_val(val):
    return f"{val:.2f}" if pd.notna(val) else "無"

def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'HTML', 'disable_web_page_preview':True})
    except Exception as e:
        print(f"❌ Telegram 文字發送失敗: {e}")

def send_tg_album(image_paths):
    if not TG_TOKEN or not TG_CHAT_ID or not image_paths: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMediaGroup"
    for i in range(0, len(image_paths), 10):
        chunk = image_paths[i:i+10]
        media = []
        files = {}
        for j, path in enumerate(chunk):
            file_key = f"photo_{j}"
            media.append({"type": "photo", "media": f"attach://{file_key}"})
            files[file_key] = open(path, 'rb')
        try:
            requests.post(url, data={'chat_id': TG_CHAT_ID, 'media': json.dumps(media)}, files=files)
        except Exception as e:
            print(f"❌ Telegram 圖片發送失敗: {e}")
        finally:
            for f in files.values(): f.close()
        time.sleep(1)

def send_grouped_messages_and_charts(category_name, results_list):
    if not results_list: return
    current_chunk = f"📁 <b>【{category_name}】監控彙整報告</b>\n\n"
    for res in results_list:
        msg = res['detail_msg']
        if len(current_chunk) + len(msg) > 3800:
            send_tg_text(current_chunk)
            time.sleep(1)
            current_chunk = f"📁 <b>【{category_name}】監控彙整報告 (續)</b>\n\n"
        current_chunk += msg + "\n\n"
    if current_chunk.strip():
        send_tg_text(current_chunk)
        time.sleep(1)
    chart_fns = [res['chart_fn'] for res in results_list if res['chart_fn'] and os.path.exists(res['chart_fn'])]
    if chart_fns:
        send_tg_album(chart_fns)
        for fn in chart_fns:
            try: os.remove(fn)
            except: pass

def classify_target(sym):
    if sym.endswith('.TW') or sym.endswith('.TWO'): return '台股'
    return '美股'

def process_target(sym, name):
    try:
        df_raw = yf.download(sym, period="3y", progress=False) 
        if df_raw.empty: return None
        if isinstance(df_raw.columns, pd.MultiIndex): 
            df_raw.columns = df_raw.columns.get_level_values(0)
        df_raw.index = df_raw.index.tz_localize(None)
        df_raw.index.name = 'Date'
        df = df_raw[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
        if len(df) < 60: return None
        market = classify_target(sym)
        df, df_w = calculate_indicators(df, market)
        if len(df_w) < 2: return None
        
        t_pe, t_pe_str, f_pe_str = None, "無", "無"
        try:
            ticker_obj = yf.Ticker(sym)
            info = ticker_obj.info
            t_pe = info.get('trailingPE')
            f_pe = info.get('forwardPE')
            if isinstance(t_pe, (int, float)): t_pe_str = f"{t_pe:.2f}"
            if isinstance(f_pe, (int, float)): f_pe_str = f"{f_pe:.2f}"
        except: pass 
        
        last_p = df['Close'].iloc[-1]
        ma_s1, ma_s2 = df['MA_S1'].iloc[-1], df['MA_S2'].iloc[-1]
        ma_l1, ma_l2 = df['MA_L1'].iloc[-1], df['MA_L2'].iloc[-1]
        ma_status = analyze_ma_relation(last_p, ma_s1, ma_s2, ma_l1, ma_l2, market)
        
        if market == '台股':
            ma_val_str = f"MA20: {fmt_val(ma_s1)} | MA60: {fmt_val(ma_s2)}\nMA120: {fmt_val(ma_l1)} |
