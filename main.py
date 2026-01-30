import os
import yfinance as yf
import pandas_ta as ta
import mplfinance as mpf
import requests

# 這裡的變數名稱一定要和你在 GitHub Settings 設的一模一樣
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') 
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


# 1. 簡化測試清單 (建議先用這幾檔測試成功後再擴充)
STOCKS = ['2330.TW', '2317.TW', '2454.TW', '2303.TW', '2603.TW']
ETFS = ['0050.TW', '00662.TW', '00646.TW']

def get_weekly_status(df):
    try:
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'})
        if len(df_w) < 5: return "數據不足", 0, 0
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
        k = kd.iloc[-1]['STOCHk_9_3_3']
        d = kd.iloc[-1]['STOCHd_9_3_3']
        pk = kd.iloc[-2]['STOCHk_9_3_3']
        pd = kd.iloc[-2]['STOCHd_9_3_3']
        level = "高檔" if k > 80 else "低檔" if k < 20 else "中檔"
        signal = "🔥金叉" if k > d and pk <= pd else "❄️死叉" if k < d and pk >= pd else "趨勢中"
        return f"{level} ({signal}), K:{k:.1f}/D:{d:.1f}", k, d
    except:
        return "計算錯誤", 0, 0

def send_telegram(text, img_path):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("錯誤：找不到 Telegram Token 或 Chat ID，請檢查 Secrets 設定")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    with open(img_path, 'rb') as f:
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})

def main():
    print("分析開始...")
    for sym in STOCKS + ETFS:
        try:
            df = yf.download(sym, period="1y", interval="1d")
            if df.empty: continue
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            
            kd_text, k_val, d_val = get_weekly_status(df)
            
            # 簡化判斷條件：只要有交叉就發圖
            if "叉" in kd_text or sym in ['2330.TW', '00662.TW']:
                img_name = f"{sym.replace('.', '_')}.png"
                apds = [
                    mpf.make_addplot(df['MA20'].tail(40), color='blue'),
                    mpf.make_addplot(df['MA60'].tail(40), color='orange')
                ]
                mpf.plot(df.tail(40), type='candle', addplot=apds, title=f"{sym} Daily", savefig=img_name)
                
                msg = f"🔔 *標的: {sym}*\n週線: {kd_text}\nMA20: {df['MA20'].iloc[-1]:.1f}"
                send_telegram(msg, img_name)
                if os.path.exists(img_name): os.remove(img_name)
                print(f"已發送: {sym}")
        except Exception as e:
            print(f"處理 {sym} 時出錯: {e}")

if __name__ == "__main__":
    main()
