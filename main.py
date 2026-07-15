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

# --- 1. 配置 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')

# --- 2. 工具函式 ---
def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip().upper()
    if ticker.endswith(('.TW', '.TWO')): return ticker
    # 自動補齊台股後綴
    return f"{ticker}.TWO" if (ticker.endswith(('B', 'C')) or ticker == '009815') else f"{ticker}.TW"

def load_csv_list(url, is_tw=True):
    """讀取 CSV 並強制清理欄位"""
    try:
        if not url: return [] if is_tw else {}
        response = requests.get(url, timeout=30)
        df = pd.read_csv(io.StringIO(response.text), on_bad_lines='skip')
        df.columns = [str(c).strip().replace('\ufeff', '') for c in df.columns]
        
        data = [] if is_tw else {}
        for _, row in df.iterrows():
            ticker = str(row.get('Ticker', '')).strip()
            if not ticker or ticker == 'nan': continue
            name = str(row.get('名稱', '')).strip()
            display_name = name if name and name != 'nan' and name != '' else ticker
            
            if is_tw:
                data.append({'symbol': get_yf_ticker_tw(ticker), 'name': display_name})
            else:
                data[ticker] = display_name
        return data
    except Exception as e:
        print(f"❌ 讀取 CSV 發生嚴重錯誤: {e}")
        return [] if is_tw else {}

def process_target(sym, name):
    try:
        df = yf.download(sym, period="3y", progress=False, threads=False) 
        if df.empty: return None
        # yfinance 舊版與新版 DataFrame 結構相容處理
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Close']].dropna()
        if len(df) < 2: return None
        
        last_p = df['Close'].iloc[-1]
        msg = f"📊 <b>{name} ({sym})</b>\n目前價位: {last_p:.2f}"
        return {'category': '台股' if sym.endswith(('.TW', '.TWO')) else '美股', 'detail_msg': msg}
    except: return None

def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id':TG_CHAT_ID, 'text':msg, 'parse_mode':'HTML'})

def main():
    print(f"DEBUG: Token: {bool(TG_TOKEN)}, ChatID: {bool(TG_CHAT_ID)}")
    
    # 在 main 裡面初始化清單，確保變數一定存在
    TW_CORE = load_csv_list(SHEET_CSV_TW_URL, True)
    US_WATCH = load_csv_list(SHEET_CSV_US_URL, False)
    
    print(f"DEBUG: 清單長度 - TW: {len(TW_CORE)}, US: {len(US_WATCH)}")
    
    if not TW_CORE and not US_WATCH:
        print("❌ 警告：所有清單皆為空，請檢查 GitHub Secrets 的 URL 是否正確。")
        return

    grouped_results = {'台股': [], '美股': []}
    all_targets = [(item['symbol'], item['name']) for item in TW_CORE] + list(US_WATCH.items())

    for sym, name in all_targets:
        res = process_target(sym, name)
        if res: grouped_results[res['category']].append(res)
        time.sleep(0.5)

    send_tg_text("🚀 盤前掃描啟動...")
    for cat in ['台股', '美股']:
        for res in grouped_results[cat]:
            send_tg_text(res['detail_msg'])
    
    send_tg_text(f"🏁 <b>每日掃描完成 ({datetime.now().strftime('%Y/%m/%d')})</b>")

if __name__ == "__main__":
    main()
