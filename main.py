import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 環境變數檢查 ---
# 確保這裡的名稱與 GitHub Secrets 一模一樣
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def get_weekly_status(df):
    try:
        # 確保為週資料
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'})
        if len(df_w) < 5: return "數據不足", 0, 0
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        k, d = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3']
        pk, pd_val = kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
        level = "高檔" if k > 80 else "低檔" if k < 20 else "中檔"
        signal = "🔥金叉" if k > d and pk <= pd_val else "❄️死叉" if k < d and pk >= pd_val else "趨勢中"
        return f"{level} ({signal}), K:{k:.1f}/D:{d:.1f}", k, d
    except Exception as e:
        return f"指標計算失敗:{str(e)}", 0, 0

def send_telegram(text, img_path):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 錯誤：找不到 TELEGRAM 設定 (TOKEN 或 CHAT_ID)")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(img_path, 'rb') as f:
            requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f}, timeout=20)
    except Exception as e:
        print(f"發送 Telegram 失敗: {e}")

def main():
    if not TG_TOKEN:
        print("❌ 錯誤：找不到 TELEGRAM 設定，請檢查 GitHub Secrets 是否設定為 TELEGRAM_BOT_TOKEN")
        return

    # 測試名單
    TEST_LIST = ['2330.TW', '2317.TW', '00662.TW', '00646.TW']
    print(f"分析開始... 執行時間: {datetime.now()}")

    for sym in TEST_LIST:
        try:
            # 下載數據
            df = yf.download(sym, period="1y", interval="1d")
            if df.empty: continue

            # --- 重點修復：處理 yfinance 數據類型問題 ---
            # 1. 移除多層索引 (如果有的話)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # 2. 強制轉換為浮點數並移除空值
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()
            
            if len(df) < 60: continue

            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            
            kd_text, k_val, d_val = get_weekly_status(df)
            
            # 條件：包含測試標的或有金死叉
            if "叉" in kd_text or sym in ['2330.TW', '00662.TW']:
                img_name = f"{sym.replace('.', '_')}.png"
                
                # 繪圖設定
                apds = [
                    mpf.make_addplot(df['MA20'].tail(40), color='blue', width=1),
                    mpf.make_addplot(df['MA60'].tail(40), color='orange', width=1)
                ]
                
                title_txt = f"{sym}\nMA20:{df['MA20'].iloc[-1]:.1f} (Blue) / MA60:{df['MA60'].iloc[-1]:.1f} (Orange)"
                mpf.plot(df.tail(40), type='candle', addplot=apds, title=title_txt, style='charles', savefig=img_name)
                
                msg = f"🔔 *標的通知: {sym}*\n週線狀態: {kd_text}\n收盤價: {df['Close'].iloc[-1]:.1f}"
                send_telegram(msg, img_name)
                if os.path.exists(img_name): os.remove(img_name)
                print(f"✅ 已成功處理並發送: {sym}")

        except Exception as e:
            print(f"處理 {sym} 時出錯: {str(e)}")

if __name__ == "__main__":
    main()
