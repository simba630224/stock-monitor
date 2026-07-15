import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import time
import json
import matplotlib
matplotlib.use('Agg') 
import mplfinance as mpf
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')

# --- 2. 輔助讀取清單 ---
def load_csv_list(url, is_tw=True):
    try:
        if not url: return [] if is_tw else {}
        df = pd.read_csv(url, on_bad_lines='skip')
        data = [] if is_tw else {}
        for _, row in df.iterrows():
            ticker = str(row.get('Ticker', '')).strip()
            if not ticker or ticker == 'nan': continue
            name = str(row.get('名稱', '')).strip()
            if is_tw:
                data.append({'symbol': ticker, 'name': name if name and name != 'nan' else ticker})
            else:
                data[ticker] = name if name and name != 'nan' else ticker
        return data
    except Exception as e:
        print(f"❌ 讀取 CSV 發生錯誤: {e}")
        return [] if is_tw else {}

TW_CORE = load_csv_list(SHEET_CSV_TW_URL, True)
US_WATCH = load_csv_list(SHEET_CSV_US_URL, False)

# --- 3. 分析函式 ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith('.TW') or ticker.endswith('.TWO'): return ticker
    if ticker.endswith('B') or ticker.endswith('C') or ticker == '009815': return f"{ticker}.TWO"
    return f"{ticker}.TW"

def analyze_ma_relation(price, ma_s1, ma_s2, ma_l1, ma_l2, market):
    short_term_name = "月/季線" if pd.notna(ma_s1) and ma_s2 != ma_l1 else "短中線"
    status = ""
    if pd.notna(ma_s1) and pd.notna(ma_s2) and ma_s1 > 0 and ma_s2 > 0:
        if price > ma_s1 and price > ma_s2: status += f"🟢 站穩 {short_term_name}"
        elif price < ma_s1 and price < ma_s2: status += f"🔴 {short_term_name} 之下"
        elif price > ma_s2 and price < ma_s1: status += f"🟡 守季線，受月線壓"
        elif price > ma_s1 and price < ma_s2: status += f"🔵 站月線，臨季線壓"
    status += " | "
    if pd.notna(ma_l1) and pd.notna(ma_l2) and ma_l1 > 0 and ma_l2 > 0:
        if price > ma_l1 and price > ma_l2: status += f"🟢 長線多頭"
        elif price < ma_l1 and price < ma_l2: status += f"🔴 長線空頭"
        else: status += f"🟡 中長期盤整"
    return status

def calculate_indicators(df, market):
    if market == '台股':
        df['MA_S1'] = df['Close'].rolling(20, min_periods=1).mean()
        df['MA_S2'] = df['Close'].rolling(60, min_periods=1).mean()
        df['MA_L1'] = df['Close'].rolling(120, min_periods=1).mean()
        df['MA_L2'] = df['Close'].rolling(240, min_periods=1).mean()
    else:
        df['MA_S1'] = df['Close'].rolling(20, min_periods=1).mean()
        df['MA_S2'] = df['Close'].rolling(50, min_periods=1).mean()
        df['MA_L1'] = df['Close'].rolling(100, min_periods=1).mean()
        df['MA_L2'] = df['Close'].rolling(200, min_periods=1).mean()
        
    ln_d = df['Low'].rolling(9, min_periods=1).min()
    hn_d = df['High'].rolling(9, min_periods=1).max()
    rsv_d = (df['Close'] - ln_d) / (hn_d - ln_d + 1e-9) * 100
    df['K_d'] = rsv_d.ewm(com=2, adjust=False).mean()
    df['D_d'] = df['K_d'].ewm(com=2, adjust=False).mean()
    
    df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
    ln_w = df_w['Low'].rolling(9, min_periods=1).min()
    hn_w = df_w['High'].rolling(9, min_periods=1).max()
    rsv_w = (df_w['Close'] - ln_w) / (hn_w - ln_w + 1e-9) * 100
    df_w['K_w'] = rsv_w.ewm(com=2, adjust=False).mean()
    df_w['D_w'] = df_w['K_w'].ewm(com=2, adjust=False).mean()
    return df, df_w

def fmt_val(val): return f"{val:.2f}" if pd.notna(val) else "無"

def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'HTML', 'disable_web_page_preview':True})

def send_tg_album(image_paths):
    if not TG_TOKEN or not TG_CHAT_ID or not image_paths: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMediaGroup"
    for i in range(0, len(image_paths), 10):
        chunk = image_paths[i:i+10]
        media, files = [], {}
        for j, path in enumerate(chunk):
            file_key = f"photo_{j}"
            media.append({"type": "photo", "media": f"attach://{file_key}"})
            files[file_key] = open(path, 'rb')
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'media': json.dumps(media)}, files=files)
        for f in files.values(): f.close()
        time.sleep(1)

def send_grouped_messages_and_charts(category_name, results_list):
    if not results_list: return
    current_chunk = f"📁 <b>【{category_name}】監控彙整報告</b>\n\n"
    for res in results_list:
        msg = res['detail_msg']
        if len(current_chunk) + len(msg) > 3800:
            send_tg_text(current_chunk); time.sleep(1); current_chunk = f"📁 <b>【{category_name}】監控彙整報告 (續)</b>\n\n"
        current_chunk += msg + "\n\n"
    if current_chunk.strip(): send_tg_text(current_chunk); time.sleep(1)
    chart_fns = [res['chart_fn'] for res in results_list if res['chart_fn'] and os.path.exists(res['chart_fn'])]
    if chart_fns:
        send_tg_album(chart_fns)
        for fn in chart_fns: os.remove(fn)

def process_target(sym, name):
    try:
        df_raw = yf.download(sym, period="3y", progress=False, threads=False) 
        if df_raw.empty: return None
        if isinstance(df_raw.columns, pd.MultiIndex): df_raw.columns = df_raw.columns.get_level_values(0)
        df_raw.index = df_raw.index.tz_localize(None) if df_raw.index.tz else df_raw.index
        df = df_raw[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna(subset=['Close'])
        if len(df) < 2: return None
        market = '台股' if sym.endswith(('.TW', '.TWO')) else '美股'
        df, df_w = calculate_indicators(df, market)
        
        last_p = df['Close'].iloc[-1]
        kd_d = f"K:{df['K_d'].iloc[-1]:.1f}/D:{df['D_d'].iloc[-1]:.1f}"
        kd_w = f"K:{df_w['K_w'].iloc[-1]:.1f}/D:{df_w['D_w'].iloc[-1]:.1f}"
        
        msg = f"📊 <b>{name} ({sym})</b>\n目前價位: {last_p:.2f}\n日KD: {kd_d}\n週KD: {kd_w}"
        return {'name': name, 'category': market, 'detail_msg': msg, 'chart_fn': None}
    except: return None

def main():
    print(f"DEBUG: Token: {bool(TG_TOKEN)}, ChatID: {bool(TG_CHAT_ID)}")
    if not TG_TOKEN or not TG_CHAT_ID: return
    
    now_str = datetime.now().strftime('%Y/%m/%d')
    grouped_results = {'台股': [], '美股': []}
    all_targets = [(get_yf_ticker_tw(item['symbol']), item['name']) for item in TW_CORE] + list(US_WATCH.items())

    for sym, name in all_targets:
        res = process_target(sym, name)
        if res: grouped_results[res['category']].append(res)
        time.sleep(0.5)

    send_grouped_messages_and_charts("台股", grouped_results['台股'])
    send_grouped_messages_and_charts("美股", grouped_results['美股'])
    send_tg_text(f"🏁 <b>每日掃描完成 ({now_str})</b>")

if __name__ == "__main__":
    main()
