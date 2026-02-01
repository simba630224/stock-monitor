import yfinance as yf
import requests
import os
import time
from datetime import datetime, timedelta

TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# 標的名單
WATCH_LIST = ['2330.TW', '2454.TW', '0050.TW', '00878.TW', 'NVDA', 'GOOGL', 'META', 'MSFT', 'QQQ', 'VOO']

def send_news(text):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown', 'disable_web_page_preview': False})

def main():
    limit_time = datetime.now() - timedelta(days=3)
    print("--- 開始新聞抓取 ---")
    
    for sym in WATCH_LIST:
        try:
            ticker = yf.Ticker(sym)
            news_data = ticker.news
            if not news_data: continue
            
            report = f"📰 *【{sym} 相關新聞】*\n"
            found = False
            for n in news_data[:3]: # 取前 3 則
                p_time = datetime.fromtimestamp(n.get('providerPublishTime', 0))
                if p_time > limit_time:
                    title = n.get('title', '無標題')
                    link = n.get('link', '#')
                    source = n.get('publisher', '未知來源')
                    report += f"🔹 {title}\n   _({source})_ [點此閱讀]({link})\n\n"
                    found = True
            
            if found:
                send_news(report)
                time.sleep(1) # 防 API 限制
        except Exception as e:
            print(f"新聞抓取錯誤 {sym}: {e}")

if __name__ == "__main__":
    main()
