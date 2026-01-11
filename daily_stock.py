import os
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz

# =======================================================
# 每日自動選股監控 (GitHub Actions + Telegram 版)
# =======================================================

# --- 1. 監控清單 ---
WATCH_LIST = [
    # --- 台股 ---
    {'symbol': '2330.TW',   'name': '台積電'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '元大台灣50'},
    {'symbol': '00922.TW',  'name': '國泰領袖50'},
    {'symbol': '00830.TW',  'name': '國泰費城半導體'},
    {'symbol': '00646.TW',  'name': '元大S&P500'},
    {'symbol': '00757.TW',  'name': '統一FANG+'},
    {'symbol': '00662.TW',  'name': '富邦NASDAQ'},
    {'symbol': '00981.TW',  'name': '富邦公用'},
    
    # --- 美股 ---
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'QQQ',       'name': '那斯達克ETF'},
]

# --- 2. Telegram 通知功能 ---
def send_telegram_notify(msg):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ 錯誤：Secrets 設定未完成")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": msg, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"發送失敗: {e}")

# --- 3. 核心檢查邏輯 ---
def check_market_status():
    print("🚀 開始執行盤後檢查...")
    messages = []
    
    tw_tz = pytz.timezone('Asia/Taipei')
    today = datetime.now(tw_tz).strftime('%Y-%m-%d')
    
    messages.append(f"📅 <b>{today} 盤後監控報告</b>")
    messages.append(f"(策略：MA均線 & 高點回檔)\n")
    
    has_alert = False 
    
    for item in WATCH_LIST:
        ticker = item['symbol']
        name = item['name']
        
        try:
            stock = yf.Ticker(ticker)
            # 抓取 1 年資料
            df = stock.history(period="1y")
            
            if df.empty or len(df) < 120:
                print(f"⚠️ {ticker} 資料不足")
                continue

            current_price = df['Close'].iloc[-1]
            
            # 計算指標
            ma20  = df['Close'].rolling(window=20).mean().iloc[-1]
            ma60  = df['Close'].rolling(window=60).mean().iloc[-1]
            ma120 = df['Close'].rolling(window=120).mean().iloc[-1]
            
            year_high = df['High'].max()
            # 防呆：避免除以零
            if year_high <= 0: year_high = current_price
            
            drop_pct = (year_high - current_price) / year_high
            
            # 判斷訊號
            alert_signals = []
            
            # A. 跌破均線
            if pd.notna(ma20) and current_price < ma20: alert_signals.append("破MA20")
            if pd.notna(ma60) and current_price < ma60: alert_signals.append("破MA60")
            if pd.notna(ma120) and current_price < ma120: alert_signals.append("破MA120")
                
            # B. 高點回檔
            if drop_pct >= 0.10:
                alert_signals.append(f"🔴 高點回落 {drop_pct*100:.1f}%")
            elif drop_pct >= 0.05:
                alert_signals.append(f"🟠 高點回落 {drop_pct*100:.1f}%")
            
            # 組合訊息
            if alert_signals:
                has_alert = True
                msg_row = f"<b>{name} ({ticker.replace('.TW', '')})</b>\n"
                msg_row += f"現價: {current_price:.2f}\n"
                msg_row += f"⚠️ 狀態: {' / '.join(alert_signals)}\n"
                messages.append(msg_row)

        except Exception as e:
            print(f"Error {ticker}: {e}")

    # 發送結果
    if has_alert:
        send_telegram_notify("\n".join(messages))
        print("✅ 通知已發送")
    else:
        # 當日平安無事也報平安
        safe_msg = f"📅 <b>{today} 盤後報告</b>\n\n✅ 監控標的皆強勢！\n(無跌破MA且回檔皆 < 5%)"
        send_telegram_notify(safe_msg)
        print("今日無觸發訊號")

if __name__ == "__main__":
    check_market_status()
