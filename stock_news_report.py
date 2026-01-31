import yfinance as yf
import requests
import os
import time
from datetime import datetime, timedelta

# --- 1. 配置與環境變數 ---
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

WATCH_LIST = [
    {'symbol': '2330.TW',   'name': '台積電'},
    {'symbol': '2454.TW',   'name': '聯發科'},
    {'symbol': '0050.TW',   'name': '台灣50'},
    {'symbol': '00878.TW',  'name': '國泰永續高股息'},
    {'symbol': '009812.TW', 'name': 'Japan'},
    {'symbol': '00830.TW',  'name': '費城半導體'},
    {'symbol': 'NVDA',      'name': '輝達'},
    {'symbol': 'GOOGL',     'name': 'GOOGLE'},
    {'symbol': 'META',      'name': 'Meta'},
    {'symbol': 'MSFT',      'name': 'MSFT'},
    {'symbol': 'QQQ',       'name': '那斯達克'},
    {'symbol': 'VOO',       'name': 'S&P500'},
    {'symbol': 'VT',        'name': 'World Stock'}
]

def send_tg_msg(text):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'Markdown', 'disable_web_page_preview': False})
    except Exception as e:
        print(f"TG發送異常: {e}")

def main():
    date_now = datetime.now()
    three_days_ago = date_now - timedelta(days=3)
    
    print(f"=== 啟動新聞抓取任務: {date_now.strftime('%Y/%m/%d')} ===")
    
    overall_news_count = 0
    
    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print(f"正在搜尋: {name} ({sym})")
        
        try:
            ticker = yf.Ticker(sym)
            news_list = ticker.news
            
            # 建立該標的的新聞訊息
            stock_report = f"📰 *【{name} 新聞快報】*\n"
            valid_news_found = False
            count = 0
            
            for news in news_list:
                # 轉換新聞發布時間 (Unix timestamp)
                pub_time = datetime.fromtimestamp(news['providerPublishTime'])
                
                # 只取 3 天內的訊息，且單一標最多 3 則
                if pub_time > three_days_ago and count < 3:
                    title = news['title']
                    link = news['link']
                    publisher = news['publisher']
                    
                    stock_report += f"🔹 {title}\n   _({publisher})_ [閱讀原文]({link})\n\n"
                    valid_news_found = True
                    count += 1
                    overall_news_count += 1
            
            if valid_news_found:
                send_tg_msg(stock_report)
                time.sleep(1) # 稍微停頓避免 TG API 頻率限制
            else:
                print(f"   (近 3 日無相關新聞)")

        except Exception as e:
            print(f"抓取 {sym} 新聞出錯: {e}")

    if overall_news_count == 0:
        send_tg_msg("📅 今日觀察標的名單近 3 日暫無重大新聞更新。")
    
    print(f"=== 任務完成，共發送 {overall_news_count} 則新聞 ===")

if __name__ == "__main__":
    main()
