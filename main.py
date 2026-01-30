import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 讀取環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram(text, img_path=None):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 錯誤：找不到環境變數設定")
        return
    
    # 基本文字發送
    if img_path is None:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'}
        r = requests.post(url, data=payload)
    else:
        # 圖片發送
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
        with open(img_path, 'rb') as f:
            r = requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
    
    # --- 重要：印出 Telegram 的回覆 ---
    if r.status_code == 200:
        print(f"✅ Telegram 發送成功！")
    else:
        print(f"❌ Telegram 發送失敗！狀態碼: {r.status_code}")
        print(f"❌ 錯誤原因: {r.text}")

def main():
    print(f"=== 啟動分析 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    # --- 動作 A: 強制發送測試訊息 (不論條件) ---
    send_telegram("🚀 機器人連線測試：如果您看到這條訊息，代表連線完全正常！")

    # --- 動作 B: 分析標的 ---
    # 為了測試，我們先只看台積電
    sym = '2330.TW'
    try:
        df = yf.download(sym, period="1y", interval="1d")
        if not df.empty:
            # 強制產生一張圖表發送，確保繪圖功能正常
            img_name = "test_chart.png"
            mpf.plot(df.tail(40), type='candle', style='charles', title=f"Test: {sym}", savefig=img_name)
            
            send_telegram(f"📊 測試圖表發送: {sym}", img_name)
            if os.path.exists(img_name): os.remove(img_name)
    except Exception as e:
        print(f"❌ 分析過程出錯: {e}")

if __name__ == "__main__":
    main()
