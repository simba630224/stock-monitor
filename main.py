import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 環境變數 ---
# 注意：Secret 內容請確保「不含」bot 字眼，僅保留 12345:ABC...
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram(text, img_path=None):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 找不到變數")
        return
    
    # 這裡確保 URL 格式正確
    base_url = f"https://api.telegram.org/bot{TG_TOKEN}"
    
    try:
        if img_path:
            url = f"{base_url}/sendPhoto"
            with open(img_path, 'rb') as f:
                r = requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            url = f"{base_url}/sendMessage"
            r = requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
        
        if r.status_code != 200:
            print(f"❌ Telegram 失敗: {r.text}")
        else:
            print("✅ Telegram 發送成功")
    except Exception as e:
        print(f"❌ 連線異常: {e}")

def main():
    print(f"=== 啟動分析: {datetime.now()} ===")
    
    # 測試標的
    sym = '2330.TW'
    
    try:
        # 下載數據
        df = yf.download(sym, period="1y", interval="1d")
        if df.empty:
            print("❌ 抓不到數據")
            return

        # --- 重要：修復 MultiIndex 與數據類型問題 ---
        # 1. 如果有複數層級的欄位，只取最底層 (例如 'Close')
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 2. 強制選取需要的欄位並轉為 float
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        df = df.astype(float).dropna()

        # 3. 計算均線
        df['MA20'] = df['Close'].rolling(20).mean()
        df['MA60'] = df['Close'].rolling(60).mean()

        # 繪圖測試
        img_name = "report.png"
        apds = [
            mpf.make_addplot(df['MA20'].tail(40), color='blue'),
            mpf.make_addplot(df['MA60'].tail(40), color='orange')
        ]
        mpf.plot(df.tail(40), type='candle', style='charles', addplot=apds, title=f"{sym} Daily", savefig=img_name)
        
        # 發送
        send_telegram(f"📊 {sym} 盤前分析測試成功！\n收盤價: {df['Close'].iloc[-1]:.1f}", img_name)
        
        if os.path.exists(img_name):
            os.remove(img_name)

    except Exception as e:
        print(f"❌ 程式執行失敗: {e}")

if __name__ == "__main__":
    main()
