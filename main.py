import yfinance as yf
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import requests
import os
from datetime import datetime

# --- 1. 配置與變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 中文名稱對照表
NAME_MAP = {
    '2330.TW': '台積電', '2317.TW': '鴻海', '2454.TW': '聯發科', '2303.TW': '聯電', 
    '2603.TW': '長榮', '3711.TW': '日月光投控', '2308.TW': '台達電', '2382.TW': '廣達',
    '0050.TW': '元大台灣50', '006208.TW': '富邦台50', '00662.TW': '富邦NASDAQ', 
    '00646.TW': '元大S&P500', '00878.TW': '國泰永續高股息'
}

# 監控名單 (市值前100與前50 ETF)
STOCKS = ['2330.TW', '2317.TW', '2454.TW', '2303.TW', '2603.TW', '3711.TW', '2308.TW', '2382.TW']
ETFS = ['0050.TW', '006208.TW', '00662.TW', '00646.TW', '00878.TW']

def send_telegram(text, img_path=None):
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            with open(img_path, 'rb') as f:
                requests.post(f"{url_base}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"{url_base}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e: print(f"發送失敗: {e}")

def main():
    report_date = datetime.now().strftime('%Y/%m/%d')
    print(f"=== {report_date} 深度分析啟動 ===")
    
    # 用於儲存報告內容的清單
    summary_data = {
        'weekly_up': [],    # 週線轉強 (金叉)
        'weekly_down': [],  # 週線轉弱 (死叉)
        'etf_obs': [],      # ETF 觀察
        'breakout': []      # 帶量突破追蹤
    }

    for sym in STOCKS + ETFS:
        try:
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()

            # 指標計算 (日線 MA)
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            
            # 指標計算 (週線 KD & MACD)
            df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
            kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'])
            macd = ta.macd(df_w['Close'])
            
            # 取得最新與前一期數值
            k, d = kd.iloc[-1]['STOCHk_9_3_3'], kd.iloc[-1]['STOCHd_9_3_3']
            pk, pd_val = kd.iloc[-2]['STOCHk_9_3_3'], kd.iloc[-2]['STOCHd_9_3_3']
            m_hist = macd.iloc[-1]['MACDh_12_26_9']
            pm_hist = macd.iloc[-2]['MACDh_12_26_9']
            
            name = NAME_MAP.get(sym, sym)
            price = df['Close'].iloc[-1]

            # 1. 判斷週線轉折
            is_gold = k > d and pk <= pd_val
            is_dead = k < d and pk >= pd_val
            macd_up = m_hist > 0 and pm_hist <= 0
            
            if sym in STOCKS:
                if is_gold or macd_up:
                    summary_data['weekly_up'].append(f"{name}({sym[:4]})：週線轉強，MACD翻紅或KD金叉。")
                elif is_dead:
                    summary_data['weekly_down'].append(f"{name}({sym[:4]})：週線死叉，需留意修正壓力。")
            
            # 2. ETF 觀察
            if sym in ETFS:
                level_txt = "超買區" if k > 80 else "強勢" if k > 50 else "整理"
                summary_data['etf_obs'].append(f"{name}({sym[:5]})：週線{level_txt}，目前價位 {price:.1f}。")

            # 3. 帶量突破 5 日追蹤 (假設 5 日前是 df.iloc[-6])
            vol_break = df['Volume'].iloc[-6] > df['Volume'].iloc[-16:-6].mean() * 1.5
            stay_above = (df['Close'].iloc[-5:] > df['MA20'].iloc[-5:]).all()
            if vol_break and stay_above:
                summary_data['breakout'].append(f"{name}({sym[:4]})：5日前放量突破，已連5日站穩月線。")

            # 4. 個別圖表發送 (僅限有重要信號的)
            if is_gold or (vol_break and stay_above):
                img_name = f"{sym}.png"
                mpf.plot(df.tail(60), type='candle', style='charles', title=f"{name}", savefig=img_name)
                send_telegram(f"🔍 *技術偵測：{name}*", img_name)
                os.remove(img_name)

        except Exception as e: print(f"Error {sym}: {e}")

    # --- 生成總結報告 ---
    report = f"【{report_date} 台股深度篩選分析報告】\n\n"
    
    report += "1️⃣ *市值百大個股：週線監測*\n"
    report += "*轉強：*\n" + ("\n".join(summary_data['weekly_up']) if summary_data['weekly_up'] else "無") + "\n"
    report += "*警戒：*\n" + ("\n".join(summary_data['weekly_down']) if summary_data['weekly_down'] else "無") + "\n\n"
    
    report += "2️⃣ *熱門 ETF (含國際型) 觀察*\n"
    report += "\n".join(summary_data['etf_obs']) + "\n\n"
    
    report += "3️⃣ *帶量突破且站穩支撐名單*\n"
    report += "\n".join(summary_data['breakout']) if summary_data['breakout'] else "今日無符合標的"
    
    report += "\n\n4️⃣ *每日總結*\n今日系統掃描完成，建議優先關注週線轉強且站穩 MA20 之龍頭股。"
    
    # 發送最終報告
    send_telegram(report)

if __name__ == "__main__":
    main()
