import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
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
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') # 改回你確認設定的名稱
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')

# --- 2. 強制抓取 CSV 的讀取函式 ---
def load_csv_list(url, is_tw=True):
    try:
        if not url: return [] if is_tw else {}
        response = requests.get(url, timeout=30)
        df = pd.read_csv(io.StringIO(response.text), on_bad_lines='skip')
        
        # 強制清理所有欄位名稱，避免隱形符號
        df.columns = [str(c).strip().replace('\ufeff', '') for c in df.columns]
        
        data = [] if is_tw else {}
        for _, row in df.iterrows():
            # 強制讀取 Ticker 欄位，並補上 .TW 後綴 (如果是台股)
            ticker = str(row.get('Ticker', '')).strip()
            if not ticker or ticker == 'nan': continue
            
            # 處理名稱，如果該欄位為空，則直接用 Ticker 代替
            name = str(row.get('名稱', '')).strip()
            display_name = name if name and name != 'nan' and name != '' else ticker
            
            if is_tw:
                # 自動補齊台股後綴
                final_ticker = get_yf_ticker_tw(ticker)
                data.append({'symbol': final_ticker, 'name': display_name})
            else:
                data[ticker] = display_name
        return data
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return [] if is_tw else {}

# --- 3. 其他功能 (保持不變) ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith('.TW') or ticker.endswith('.TWO'): return ticker
    if ticker.endswith('B') or ticker.endswith('C') or ticker == '009815': return f"{ticker}.TWO"
    return f"{ticker}.TW"

def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'HTML', 'disable_web_page_preview':True})

def process_target(sym, name):
    try:
        df_raw = yf.download(sym, period="3y", progress=False, threads=False) 
        if df_raw.empty: return None
        if isinstance(df_raw.columns, pd.MultiIndex): df_raw.columns = df_raw.columns.get_level_values(0)
        df_raw.index = df_raw.index.tz_localize(None) if df_raw.index.tz else df_raw.index
        df = df_raw[['Close']].astype(float).dropna()
        if len(df) < 2: return None
        
        last_p = df['Close'].iloc[-1]
        msg = f"📊 <b>{name} ({sym})</b>\n目前價位: {last_p:.2f}"
        return {'name': name, 'category': '台股' if sym.endswith(('.TW', '.TWO')) else '美股', 'detail_msg': msg}
    except: return None

def main():
    print(f"DEBUG: Token: {bool(TG_TOKEN)}, ChatID: {bool(TG_CHAT_ID)}")
    print(f"DEBUG: 清單長度 - TW: {len(TW_CORE)}, US: {len(US_WATCH)}")
    
    if not TW_CORE and not US_WATCH:
        print("❌ 清單為空，程式停止。")
        return

    grouped_results = {'台股': [], '美股': []}
    all_targets = [(get_yf_ticker_tw(item['symbol']), item['name']) for item in TW_CORE] + list(US_WATCH.items())

    for sym, name in all_targets:
        res = process_target(sym, name)
        if res: grouped_results[res['category']].append(res)
        time.sleep(0.5)

    # 簡單發送測試
    send_tg_text("🚀 盤前掃描啟動...")
    for cat in ['台股', '美股']:
        for res in grouped_results[cat]:
            send_tg_text(res['detail_msg'])
    
    send_tg_text(f"🏁 <b>每日掃描完成 ({datetime.now().strftime('%Y/%m/%d')})</b>")

if __name__ == "__main__":
    main()
