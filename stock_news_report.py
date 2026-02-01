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

def clean_markdown(text):
    """清理標題中的特殊字元，避免 Telegram Markdown 解析錯誤"""
    if not text: return ""
    return text.replace('_', ' ').replace('*', ' ').replace('[', '(').replace(']', ')')

def send_tg_msg(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("❌ 錯誤：找不到環境變數")
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        'chat_id': TG_CHAT_ID,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': False
    }
    try:
        r = requests.post(url, data=payload)
        if r.status_code != 200:
            print(f"❌ Telegram 發送失敗: {r.text}")
    except Exception as e:
        print(f"❌ Telegram 連線異常: {e}")

def main():
    now = datetime.now()
    # --- 修改點：擴大至 7 天 (168 小時) ---
    one_week_ago = now - timedelta(days=7)
    
    print(f"=== 🔍 啟動一週新聞監測: {now.strftime('%Y/%m/%d %H:%M')} ===")
    
    # 發送啟動訊號
    send_tg_msg(f"📡 *一週新聞情報系統啟動*\n正在掃描 {len(WATCH_LIST)} 檔標的近 **7 天** 重大新聞...")

    news_count = 0

    for item in WATCH_LIST:
        sym, name = item['symbol'], item['name']
        print(f"正在搜尋: {name} ({sym}) ...")
        
        try:
            ticker = yf.Ticker(sym)
            raw_news = ticker.news
            
            if not raw_news:
                print(f"   ⚠️ {sym} 無新聞數據")
                continue
            
            valid_stock_news = []
            for n in raw_news:
                p_time = datetime.fromtimestamp(n.get('providerPublishTime', 0))
                
                # 過濾一週內的新聞
                if p_time > one_week_ago:
                    title = clean_markdown(n.get('title', '無標題'))
                    link = n.get('link', '#')
                    source = n.get('publisher', '來源未知')
                    
                    valid_stock_news.append(f"🔹 {title}\n   _({source})_ [閱讀原文]({link})")
            
            if valid_stock_news:
                # 每一檔標的一則訊息，最多取最新 3 則以免洗版
                report = f"📰 *【{name} 近一週焦點】*\n\n" + "\n\n".join(valid_stock_news[:3])
                send_tg_msg(report)
                news_count += 1
                print(f"   ✅ 找到 {len(valid_stock_news)} 則新聞，已發送訊息")
                time.sleep(1) # 防頻率限制
            else:
                print(f"   ℹ️ {sym} 7天內暫無新消息")

        except Exception as e:
            print(f"❌ 處理 {sym} 時發生錯誤: {e}")

    print(f"=== ✅ 任務完成，共處理 {news_count} 個標的新聞 ===")
    if news_count == 0:
        send_tg_msg("📅 *新聞結報*：觀察清單近 7 日暫無重大新聞更新。")

if __name__ == "__main__":
    main()
