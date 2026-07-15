import yfinance as yf
import pandas as pd
import requests
import io
import os
import time
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

def check_macd_gc(df):
    if len(df) < 35: return False
    macd = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return (hist.iloc[-1] > 0) and (hist.iloc[-2] <= 0)

def process_target(sym, name):
    try:
        df = yf.download(sym, period="1y", progress=False, threads=False) 
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df[['Close', 'High', 'Low']].dropna()
        if len(df) < 60: return None
        
        is_tw = sym.endswith(('.TW', '.TWO'))
        category = '台股' if is_tw else '美股'
        last_p = df['Close'].iloc[-1]
        
        # MACD 計算
        daily_gc = check_macd_gc(df)
        df_w = df.resample('W-FRI').agg({'Close':'last'}).dropna()
        weekly_gc = check_macd_gc(df_w) if len(df_w) >= 35 else False
        
        # 均線狀態與 20 日高回檔 (台股 60/120/240, 美股 50/100/200)
        ma_m = df['Close'].rolling(60 if is_tw else 50).mean().iloc[-1]
        high_20 = df['High'].rolling(20).max().iloc[-1]
        pullback_alert = "⚠️ 創20日高後回檔" if (high_20 - last_p) / high_20 > 0.05 else ""
        ma_status = f"🟢 站上季線" if last_p > ma_m else f"🔴 季線之下"
        
        try:
            pe = yf.Ticker(sym).info.get('trailingPE') or yf.Ticker(sym).info.get('forwardPE', 999)
        except:
            pe = 999
            
        score = 3 if (daily_gc and weekly_gc) else (2 if weekly_gc else (1 if daily_gc else 0))
        status_text = "🔥 雙重金叉" if score == 3 else ("📊 週線金叉" if score == 2 else ("📈 日線金叉" if score == 1 else ma_status))
        
        return {
            'sym': sym, 'name': name, 'category': category, 'score': score, 
            'pe': pe, 'pe_str': f"{pe:.1f}" if pe != 999 else "N/A", 
            'status': status_text, 'last_p': last_p, 'pullback': pullback_alert
        }
    except: return None

def send_tg_text(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                  data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})

# --- 3. 主程式 ---
def main():
    TW_CORE = load_csv_list(SHEET_CSV_TW_URL, True)
    US_WATCH = load_csv_list(SHEET_CSV_US_URL, False)
    if not TW_CORE and not US_WATCH: return

    results = {'台股': [], '美股': []}
    for sym, name in [(item['symbol'], item['name']) for item in TW_CORE] + list(US_WATCH.items()):
        res = process_target(sym, name)
        if res: results[res['category']].append(res)
        time.sleep(0.5)

    send_tg_text("🚀 <b>盤後亮點摘要與狀態警示</b>")
    
    for cat in ['台股', '美股']:
        cat_data = results[cat]
        if not cat_data: continue
        
        # 分流：有亮點的去 highlights，沒亮點的去 general_alerts
        highlights = [r for r in cat_data if r['score'] > 0]
        general_alerts = [r for r in cat_data if r['score'] == 0]
        
        # 1. 發送亮點
        if highlights:
            msg = f"🎯 <b>【{cat}】技術亮點摘要</b>\n"
            highlights = sorted(highlights, key=lambda x: (-x['score'], x['pe']))
            for item in highlights:
                msg += f"• {item['status']} | {item['name']} ({item['sym']}) | 價: {item['last_p']:.2f} | PE: {item['pe_str']}\n"
            send_tg_text(msg)
            
        # 2. 發送常規警示
        if general_alerts:
            msg = f"⚠️ <b>【{cat}】常規狀態追蹤</b>\n"
            for item in sorted(general_alerts, key=lambda x: x['status']):
                pb_text = f" | {item['pullback']}" if item['pullback'] else ""
                msg += f"• {item['status']} | {item['name']} ({item['sym']}) | 價: {item['last_p']:.2f}{pb_text}\n"
            send_tg_text(msg)

    send_tg_text(f"🏁 <b>每日掃描完成 ({datetime.now().strftime('%Y/%m/%d')})</b>")

if __name__ == "__main__":
    main()
