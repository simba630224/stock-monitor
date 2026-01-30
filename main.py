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

# 建立中文名稱對照表 (針對熱門標的，其餘顯示代號)
NAME_MAP = {
    '2330.TW': '台積電', '2317.TW': '鴻海', '2454.TW': '聯發科', '2308.TW': '台達電', 
    '2382.TW': '廣達', '2303.TW': '聯電', '2881.TW': '富邦金', '2882.TW': '國泰金', 
    '2603.TW': '長榮', '0050.TW': '元大台灣50', '006208.TW': '富邦台50', 
    '00662.TW': '富邦NASDAQ', '00646.TW': '元大S&P500', '00878.TW': '國泰永續高股息',
    '00919.TW': '群益台灣精選高股息', '00929.TW': '復華台灣科技優息'
}

# --- 2. 核心功能函數 ---

def get_weekly_status(df):
    """計算週線指標，確保穩定性"""
    try:
        # 轉換為週線 (W-FRI 代表以週五為結算)
        df_w = df.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        
        if len(df_w) < 15: return "數據分析中", 0, 0
        
        # 計算週 KD
        kd = ta.stoch(df_w['High'], df_w['Low'], df_w['Close'], k=9, d=3, smooth_k=3)
        k = kd.iloc[-1]['STOCHk_9_3_3']
        d = kd.iloc[-1]['STOCHd_9_3_3']
        pk = kd.iloc[-2]['STOCHk_9_3_3']
        pd_val = kd.iloc[-2]['STOCHd_9_3_3']
        
        level = "🟢 低檔進場區" if k < 25 else "🔴 高檔警戒區" if k > 75 else "🟡 中檔整理"
        signal = ""
        if k > d and pk <= pd_val: signal = "【🔥 週線金叉】"
        elif k < d and pk >= pd_val: signal = "【❄️ 週線死叉】"
        
        return f"{level} {signal} (K:{k:.1f} / D:{d:.1f})", k, d
    except Exception as e:
        return f"指標計算失敗: {str(e)}", 0, 0

def send_telegram(text, img_path=None):
    url_base = f"https://api.telegram.org/bot{TG_TOKEN}"
    try:
        if img_path:
            with open(img_path, 'rb') as f:
                requests.post(f"{url_base}/sendPhoto", data={'chat_id': TG_CHAT_ID, 'caption': text, 'parse_mode': 'Markdown'}, files={'photo': f})
        else:
            requests.post(f"{url_base}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown'})
    except Exception as e:
        print(f"Telegram 發送異常: {e}")

def main():
    print(f"=== 盤前全方位監控啟動: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    
    # 使用您關注的標的名單
    TARGET_LIST = [
        '2330.TW', '2317.TW', '2454.TW', '2382.TW', '2603.TW', 
        '0050.TW', '006208.TW', '00662.TW', '00646.TW', '00878.TW'
    ]
    
    for sym in TARGET_LIST:
        try:
            # 下載兩年資料以確保週線指標計算正確
            df = yf.download(sym, period="2y", interval="1d", progress=False)
            if df.empty: continue

            # 數據清理
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float).dropna()

            # --- 豐富分析內容 ---
            # 1. 均線與價格關係
            df['MA20'] = df['Close'].rolling(20).mean()
            df['MA60'] = df['Close'].rolling(60).mean()
            now_price = df['Close'].iloc[-1]
            change_pct = ((now_price - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
            
            # 2. 量能分析
            avg_vol = df['Volume'].iloc[-21:-1].mean()
            vol_ratio = df['Volume'].iloc[-1] / avg_vol
            
            # 3. 週線狀態
            kd_text, k_val, d_val = get_weekly_status(df)

            # --- 篩選條件 (只要有特徵就報警，增加豐富度) ---
            is_gold_cross = "金叉" in kd_text
            is_breakout = vol_ratio > 1.5 and now_price > df['Open'].iloc[-1]
            is_near_ma = abs(now_price - df['MA20'].iloc[-1]) / now_price < 0.01  # 靠近月線
            
            if is_gold_cross or is_breakout or is_near_ma or (sym in ['2330.TW', '00662.TW']):
                
                # 繪圖
                img_name = f"{sym.replace('.','_')}.png"
                apds = [
                    mpf.make_addplot(df['MA20'].tail(60), color='blue', width=1, label='MA20'),
                    mpf.make_addplot(df['MA60'].tail(60), color='orange', width=1, label='MA60')
                ]
                comp_name = NAME_MAP.get(sym, sym)
                title_txt = f"{comp_name} ({sym})\nPrice: {now_price:.1f} ({change_pct:+.1f}%)"
                mpf.plot(df.tail(60), type='candle', style='charles', addplot=apds, title=title_txt, savefig=img_name)

                # 組合豐富的分析報告
                report = (
                    f"📊 *盤前監控報告: {comp_name} ({sym})*\n"
                    f"----------------------------\n"
                    f"💰 當前股價: `{now_price:.1f}` ({change_pct:+.2f}%)\n"
                    f"📈 週線趨勢: {kd_text}\n"
                    f"🔥 成交量比: `{vol_ratio:.2f}x` (對比20日均量)\n"
                    f"🛡️ 關鍵支撐: MA20=`{df['MA20'].iloc[-1]:.1f}` / MA60=`{df['MA60'].iloc[-1]:.1f}`\n"
                    f"💡 分析結論: "
                )
                
                if is_breakout: report += "「帶量突破特徵」 "
                if is_gold_cross: report += "「週線轉強信號」 "
                if is_near_ma: report += "「股價回測月線」 "
                if not (is_breakout or is_gold_cross or is_near_ma): report += "「日常追蹤」"

                send_telegram(report, img_name)
                if os.path.exists(img_name): os.remove(img_name)
                print(f"✅ 已發送報告: {comp_name}")

        except Exception as e:
            print(f"❌ 處理 {sym} 出錯: {e}")

if __name__ == "__main__":
    main()
