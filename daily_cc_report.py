import os
import requests
import google.generativeai as genai
from datetime import datetime

# --- 1. 環境變數 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# --- 2. 獲取策略分析 ---
def get_daily_strategy():
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    prompt = f"""
    今天是 {today}。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    永豐幣倍卡、中信uniopen、國泰CUBE JCB卡、富邦Costco、富邦Momo、富邦JCB/J卡、台新Richart 卡。
    
    內容包含：
    1. 量販超市 (全聯、家樂福)
    2. 百貨 (中壢大江現抵活動)
    3. 餐飲交通 (星巴克週五外送買一送一、中油加油)
    4. 線上購物 (Momo)
    
    請註明：最優支付方式與 CUBE/Richart 的方案切換建議。
    格式要求：使用 HTML 標籤 (<b>, <i>, <u>)，結構清晰。
    """
    
    response = model.generate_content(prompt)
    return response.text

# --- 3. Telegram 傳送函式 (採用您的版本) ---
def send_telegram_notify(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
