import yfinance as yf
import pandas as pd
import requests
import os
from datetime import datetime

# --- 1. 環境變數讀取 (整合防錯機制) ---
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- 2. 資產清單與名稱對照 ---
# 這裡建議放您實際持有的標的或核心追蹤標的
MY_PORTFOLIO = [
    '2330.TW', '2317.TW', '2454.TW', '0050.TW', 
    '00662.TW', '00646.TW', '00949.TW'  # 包含您感興趣的日本市場 ETF
]

NAME_MAP = {
    '2330.TW': '台積電', '2317.TW': '鴻海', '2454.TW': '聯發科',
    '0050.TW': '元大台灣50', '00662.TW': '富邦NASDAQ', 
    '00646.TW': '元大S&P500', '00949.TW': '復華日本龍頭'
}

def send_telegram_msg(text):
    """發送純文字報告"""
    if not TOKEN or not CHAT_ID:
        print("❌ 錯誤：找不到環境變數 (TOKEN/CHAT_ID)")
        return
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'Markdown'
    }
    try:
        r = requests.post(url, data=payload)
        if r.status_code == 200:
            print("✅ 盤後資產報告發送成功")
        else:
            print(f"❌ 發送失敗，狀態碼: {r.status_code}, 原因: {r.text}")
    except Exception as e:
        print(f"❌ Telegram 連線異常: {e}")

def main():
    today_str = datetime.now().strftime('%Y/%m/%d')
    print(f"=== 啟動盤後資產彙總: {today_str} ===")
    
    report_body = f"✨ *【{today_str} 台北盤後資產監測報告】*\n"
    report_body += "------------------------------------------\n"
    
    total_items = 0
    up_count = 0
    down_count = 0

    for sym in MY_PORTFOLIO:
        try:
            # 下載最新兩日數據以計算漲跌
            df = yf.download(sym, period="5d", interval="1d", progress=False)
            if df.empty: continue
            
            # 處理 yfinance 的 MultiIndex 問題
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            df = df[['Open', 'High', 'Low', 'Close']].astype(float).dropna()
            
            now_price = df['Close'].iloc[-1]
            prev_price = df['Close'].iloc[-2]
            change = now_price - prev_price
            change_pct = (change / prev_price) * 100
            
            name = NAME_MAP.get(sym, sym)
            
            # 決定漲跌符號
            if change > 0:
                mark = "🔴"
                up_count += 1
            elif change < 0:
                mark = "🟢"
                down_count += 1
            else:
                mark = "⚪"

            report_body += f"{mark} *{name}* ({sym[:4]})\n"
            report_body += f"   現價: `{now_price:.2f}` | 漲跌: `{change:+.2f}` (`{change_pct:+.2f}%`)\n"
            total_items += 1

        except Exception as e:
            print(f"❌ 處理 {sym} 時出錯: {e}")

    # --- 總結部分 ---
    report_body += "------------------------------------------\n"
    report_body += f"📊 *今日盤後統計*：\n"
    report_body += f"掃描標的: {total_items} 檔\n"
    report_body += f"上漲: {up_count} / 下跌: {down_count} / 持平: {total_items - up_count - down_count}\n\n"
    report_body += "💡 *筆記*：本報告僅供參考，請留意美股盤前走勢對明日台股之影響。"

    send_telegram_msg(report_body)

if __name__ == "__main__":
    main()
