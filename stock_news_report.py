import yfinance as yf
import requests, os, time
from datetime import datetime, timedelta

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
WATCH_LIST = ['2330.TW', '2454.TW', '0050.TW', 'NVDA', 'GOOGL', 'META', 'MSFT']

def main():
    limit_time = datetime.now() - timedelta(days=3)
    for sym in WATCH_LIST:
        try:
            news = yf.Ticker(sym).news
            if not news: continue
            report = f"📰 *【{sym} 相關新聞】*\n"
            found = False
            for n in news[:3]:
                if datetime.fromtimestamp(n.get('providerPublishTime', 0)) > limit_time:
                    report += f"🔹 {n.get('title')}\n   [閱讀]({n.get('link')})\n\n"
                    found = True
            if found:
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data={'chat_id': TG_CHAT_ID, 'text': report, 'parse_mode': 'Markdown'})
                time.sleep(1)
        except Exception as e: print(f"News Error {sym}: {e}")

if __name__ == "__main__": main()
