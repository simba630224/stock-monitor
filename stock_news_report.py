import yfinance as yf
import requests
import os
import time
from datetime import datetime, timedelta

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 標的名單 (針對新聞抓取進行了 Ticker 優化)
# 註：台股 .TW 標的在 Yahoo 國際版新聞較少，建議同時觀察美股 ADR
WATCH_LIST = [
    {'symbol': 'TSM',       'name': '台積電(ADR)'}, # 改用 ADR 確保 100% 有國際新聞
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '台灣50'},
    {'symbol': '00878.TW',  'name': '國泰高股息'},
    {'symbol': '009812.TW', 'name': '日本指數'},
    {'symbol': '00830.TW',  'name': '費城半導體'},
    {'symbol': 'GOOGL',     'name': 'GOOGLE'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'MSFT',      'name': '微軟'},
    {'symbol': 'QQQ',       'name': '那斯達克'},
    {'symbol': 'VOO',       'name': 'S&P500'},
    {'symbol': 'VT',        'name': '世界股市'}
]

def send_tg_msg(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 錯誤：找不到環境變數")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        'chat_id': TG_CHAT_ID,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    try:
        r = requests.post(url, data=payload)
        if r.status_code != 200:
            print(f"❌ Telegram 發送失敗: {r.text}")
    except Exception as e:
        print(f"❌ Telegram 連線異常: {e}")

def main():
    # 取得當前 Unix 時間戳記 (秒)
    current_ts = time.time()
    # 定義 7 天的秒數 (7天 * 24小時 * 3600秒)
    seven_days_seconds = 7 * 24 * 3600
    
    print(f"=== 🔍 啟動一週新聞監測 (強制抓取版) ===")
    
    overall_sent_count = 0

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print(f"正在搜尋: {name} ({sym})...")
        
        try:
            ticker = yf.Ticker(sym)
            raw_news = ticker.news
            
            if not raw_news:
                print(f"   ⚠️ {sym} Yahoo API 未回傳任何新聞數據")
                continue
            
            print(f"   找到 {len(raw_news)} 則原始數據，開始過濾時間...")
            
            valid_news = []
            for n in raw_news:
                # 取得新聞時間戳記，若無則設為 0
                news_ts = n.get('providerPublishTime', 0)
                
                # --- 核心邏輯：直接比較時間戳記數值，避免時區轉換錯誤 ---
                if (current_ts - news_ts) < seven_days_seconds:
                    title = n.get('title', '無標題')
                    link = n.get('link', '#')
                    source = n.get('publisher', '來源未知')
                    
                    # 簡單清理標題避免 Markdown 錯誤
                    clean_title = title.replace('*','').replace('_','').replace('[','(').replace(']',')')
                    valid_news.append(f"🔹 {clean_title}\n   _({source})_ [閱讀原文]({link})")

            if valid_news:
                report = f"📰 *【{name} 一週焦點】*\n\n" + "\n\n".join(valid_news[:3])
                send_tg_msg(report)
                overall_sent_count += 1
                print(f"   ✅ 成功發送 {len(valid_news[:3])} 則新聞")
                time.sleep(1) # 防頻率限制
            else:
                print(f"   ℹ️ {sym} 的所有新聞均超過 7 天")

        except Exception as e:
            print(f"❌ 處理 {sym} 出錯: {e}")

    if overall_sent_count == 0:
        send_tg_msg("📅 *新聞匯報*：清單標的近 7 日暫無國際重大新聞更新。")

if __name__ == "__main__":
    main()
