import os
import requests
import yfinance as yf
import pandas as pd
import mplfinance as mpf  # 引入繪圖套件
from datetime import datetime
import pytz
import io # 用於在記憶體中處理圖片

# =======================================================
# 每日自動選股監控 (GitHub Actions + Telegram + K線圖版)
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

# --- 2. Telegram 通知功能 (文字) ---
def send_telegram_text(msg):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": msg, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    requests.post(url, data=payload)

# --- 3. Telegram 傳送圖片功能 (新增) ---
def send_telegram_photo(caption, photo_buffer):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    
    # 準備圖片檔案
    photo_buffer.seek(0) # 將指標指回起點
    files = {'photo': photo_buffer}
    
    payload = {
        "chat_id": chat_id,
        "caption": caption, # 圖片下方的文字說明
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, data=payload, files=files)
        print("✅ 圖片發送成功")
    except Exception as e:
        print(f"❌ 圖片發送失敗: {e}")

# --- 4. 繪製 K 線圖功能 (新增) ---
def plot_stock_chart(df, ticker, name):
    # 設定圖表樣式
    mc = mpf.make_marketcolors(up='r', down='g', inherit=True) # 台股習慣：紅漲綠跌
    s  = mpf.make_mpf_style(base_mpf_style='yahoo', marketcolors=mc)
    
    # 建立記憶體緩衝區 (不存硬碟，直接存記憶體)
    buf = io.BytesIO()
    
    # 只畫最近 120 天，讓 K 線看清楚一點
    plot_data = df.tail(120)
    
    # 繪圖
    # mav=(20, 60, 120) 會自動畫出月線、季線、半年線
    mpf.plot(
        plot_data, 
        type='candle', 
        mav=(20, 60, 120), 
        volume=True, 
        title=f"\n{name} ({ticker.replace('.TW', '')})",
        style=s,
        savefig=buf # 存入緩衝區
    )
    return buf

# --- 5. 核心檢查邏輯 ---
def check_market_status():
    print("🚀 開始執行盤後檢查...")
    
    tw_tz = pytz.timezone('Asia/Taipei')
    today = datetime.now(tw_tz).strftime('%Y-%m-%d')
    
    # 先發送一個開頭標題
    header_msg = f"📅 <b>{today} 盤後監控報告</b>\n(附 K 線圖檢視)"
    send_telegram_text(header_msg)
    
    has_alert = False 
    
    for item in WATCH_LIST:
        ticker = item['symbol']
        name = item['name']
        
        try:
            stock = yf.Ticker(ticker)
            # 抓取 1 年資料 (計算半年線 MA120 需要)
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
            
            # --- 觸發處理 ---
            if alert_signals:
                has_alert = True
                print(f"⚡ {name} 觸發訊號，正在繪圖...")
                
                # 1. 準備文字說明
                caption = f"<b>{name} ({ticker.replace('.TW', '')})</b>\n"
                caption += f"現價: {current_price:.2f}\n"
                caption += f"⚠️ 狀態: {' / '.join(alert_signals)}"
                
                # 2. 畫圖
                chart_img = plot_stock_chart(df, ticker, name)
                
                # 3. 傳送圖片 + 文字
                send_telegram_photo(caption, chart_img)
            
            else:
                # 沒事就不傳送，避免洗版
                pass

        except Exception as e:
            print(f"Error {ticker}: {e}")

    if not has_alert:
        send_telegram_text("✅ 今日監控標的皆強勢 (無跌破MA且回檔 < 5%)")
        print("今日無觸發訊號")

if __name__ == "__main__":
    check_market_status()
