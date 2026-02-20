import os
import requests
from google import genai
from datetime import datetime

# --- 1. 環境變數 ---
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- 2. 獲取 Gemini 策略分析 ---
def get_daily_strategy():
    if not api_key:
        return "錯誤：找不到 GOOGLE_API_KEY，請檢查 GitHub Secrets 設定。"
    
    client = genai.Client(api_key=api_key)
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    prompt = f"""
    今天是 {today}。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    永豐幣倍卡、中信uniopen、國泰CUBE JCB卡、富邦Costco、富邦Momo、富邦JCB/J卡、台新Richart 卡。
    
    內容需包含：
    1. 量販超市 (全聯、家樂福)
    2. 百貨 (中壢大江現抵活動、夢時代)
    3. 餐飲交通 (星巴克、中油加油)
    4. 線上購物 (Momo)
    
    請註明：每張卡的最優支付方式與 CUBE/Richart 的方案切換建議。
    格式要求：使用 HTML 標籤（如 <b>, <i>, <u>），結構清晰，末尾附上一句今日小撇步。
    """
    
    # 鎖定 1.5 版本以避開 429 錯誤
    response = client.models.generate_content(
        model="gemini-1.5-flash", 
        contents=prompt
    )
    return response.text

# --- 3. Telegram 傳送函式 (採用您的版本) ---
def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id:
        print("Telegram 設定缺失")
        return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        print(f"傳送失敗：{r.text}")

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
