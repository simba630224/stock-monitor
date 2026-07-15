import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import os
import time
import json
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SHEET_CSV_TW_URL = os.getenv('SHEET_CSV_TW_URL')
SHEET_CSV_US_URL = os.getenv('SHEET_CSV_US_URL')

# --- 2. 技術指標與輔助計算 ---
def get_yf_ticker_tw(ticker):
    """確保台股代號格式正確，並自動補足後綴"""
    ticker = str(ticker).strip().upper()
    if ticker.endswith(('.TW', '.TWO')): 
        return ticker
    # 債權/認購/部分特定商品若以 B, C 結尾，或是 009815，使用 .TWO
    if (ticker.endswith(('B', 'C')) or ticker == '009815'):
        return f"{ticker}.TWO"
    return f"{ticker}.TW"

def check_macd_gc(df):
    """計算 MACD 並檢查最新一筆是否為黃金交叉 (快線由下往上穿過慢線)"""
    if len(df) < 35: 
        return False
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    # 判斷黃金交叉：當前柱狀圖大於 0，而前一交易日小於等於 0
    return (hist.iloc[-1] > 0) and (hist.iloc[-2] <= 0)

def load_csv_list(url, is_tw=True):
    """透過 requests 下載 Google Sheets 發布的 CSV，並寬鬆清理欄位名稱"""
    try:
        if not url: return [] if is_tw else {}
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        df = pd.read_csv(io.StringIO(response.text), on_bad_lines='skip')
        # 去除 BOM 符號、空白並轉為小寫
        df.columns = [str(c).strip().replace('\ufeff', '').lower() for c in df.columns]
        
        data = [] if is_tw else {}
        for _, row in df.iterrows():
            row_dict = {str(k).strip().lower(): v for k, v in row.items()}
            ticker = str(row_dict.get('ticker') or '').strip()
            name = str(row_dict.get('名稱') or row_dict.get('name') or '').strip()
            
            if not ticker or ticker.lower() == 'nan': 
                continue
            display_name = name if name and name != 'nan' and name != '' else ticker
            
            if is_tw:
                data.append({'symbol': get_yf_ticker_tw(ticker), 'name': display_name})
            else:
                data[ticker] = display_name
        
        print(f"DEBUG: 成功解析 {len(data)} 筆資料 (TW={is_tw})")
        return data
    except Exception as e:
        print(f"❌ 讀取 CSV 發生嚴重錯誤: {e}")
        return [] if is_tw else {}

def process_target(sym, name):
    """下載歷史行情，計算日週 MACD 金叉狀態與 PE，並回傳評分"""
    try:
        # 下載至少 1 年數據確保 MACD 週線計算正確
        df = yf.download(sym, period="1y", progress=False, threads=False) 
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): 
            df.columns = df.columns.get_level_values(0)
        df = df[['Close']].dropna()
        if len(df) < 35: return None
        
        # 1. 計算日線 MACD 金叉
        daily_gc = check_macd_gc(df)
        
        # 2. 計算週線 MACD 金叉
        df_w = df.resample('W-FRI').agg({'Close':'last'}).dropna()
        weekly_gc = check_macd_gc(df_w) if len(df_w) >= 35 else False
        
        # 3. 取得 PE (本益比)
        try:
            info = yf.Ticker(sym).info
            pe = info.get('trailingPE') or info.get('forwardPE', 999)
        except:
            pe = 999  # 若查無 PE (例如 ETF)，給予最大值使其在同評分下排到最後面
            
        # 4. 符合程度評分評估 (評分越高越優先)
        score = 0
        if daily_gc and weekly_gc:
            score = 3
            status_text = "🔥 雙重金叉 (日+週)"
        elif weekly_gc:
            score = 2
            status_text = "📊 週線金叉"
        elif daily_gc:
            score = 1
            status_text = "📈 日線金叉"
        else:
            score = 0
            status_text = "⚪ 無特定金叉訊號"
            
        last_p = df['Close'].iloc[-1]
        pe_str = f"{pe:.1f}" if pe != 999 else "N/A"
        
        return {
            'sym': sym,
            'name': name,
            'category': '台股' if sym.endswith(('.TW', '.TWO')) else '美股',
            'score': score,
            'pe': pe,
            'pe_str': pe_str,
            'status': status_text,
            'last_p': last_p
        }
    except Exception as e:
        print(f"❌ 處理 {sym} 時出錯: {e}")
        return None

def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})

# --- 3. 主程式流程 ---
def main():
    print(f"DEBUG: Token: {bool(TG_TOKEN)}, ChatID: {bool(TG_CHAT_ID)}")
    
    TW_CORE = load_csv_list(SHEET_CSV_TW_URL, True)
    US_WATCH = load_csv_list(SHEET_CSV_US_URL, False)
    
    print(f"DEBUG: 清單長度 - TW: {len(TW_CORE)}, US: {len(US_WATCH)}")
    
    if not TW_CORE and not US_WATCH:
        print("❌ 警告：所有清單皆為空，請檢查 Google Sheets 是否已成功公開為 CSV。")
        return

    grouped_results = {'台股': [], '美股': []}
    all_targets = [(item['symbol'], item['name']) for item in TW_CORE] + list(US_WATCH.items())

    for sym, name in all_targets:
        res = process_target(sym, name)
        if res: 
            grouped_results[res['category']].append(res)
        time.sleep(0.5)

    send_tg_text("🚀 <b>盤後亮點摘要與狀態警示</b>")
    
    for cat in ['台股', '美股']:
        cat_data = grouped_results[cat]
        if not cat_data: continue
        
        # 核心排序：依分數 score 降冪排序，再依 pe 升冪排序
        sorted_data = sorted(cat_data, key=lambda x: (-x['score'], x['pe']))
        
        msg_chunk = f"📁 <b>【{cat}】監控彙整</b>\n"
        current_status = ""
        has_highlights = False
        
        for item in sorted_data:
            # 只顯示有亮點 (score > 0) 的標的
            if item['score'] == 0: continue 
            has_highlights = True
            
            # 分組標題
            if item['status'] != current_status:
                current_status = item['status']
                msg_chunk += f"\n<b>{current_status}</b>\n"
                
            msg_chunk += f"• {item['name']} ({item['sym']}) | 價: {item['last_p']:.2f} | PE: {item['pe_str']}\n"
            
        if has_highlights:
            send_tg_text(msg_chunk)
        else:
            send_tg_text(f"📁 <b>【{cat}】今日無特殊技術面亮點。</b>")
            
    send_tg_text(f"🏁 <b>每日掃描完成 ({datetime.now().strftime('%Y/%m/%d')})</b>")

if __name__ == "__main__":
    main()
