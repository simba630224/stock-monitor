import os
import requests
from google import genai
from datetime import datetime

# --- 1. 環境變數 ---
# 注意：新版 SDK 預設會讀取 GOOGLE_API_KEY
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- 2. 獲取策略分析 (使用新版 SDK) ---
def get_daily_strategy():
    if not api_key:
        return "錯誤：找不到 API Key，請檢查 GitHub Secrets 設定。"
    
    client = genai.Client(api_key=api_key)
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    prompt = f"""
    今天是 {today}。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    永豐幣倍卡、中信uniopen、國泰CUBE JCB卡、富邦Costco、富邦Momo、富邦JCB/J卡、台新Richart 卡。
    
    內容包含：
    1. 量販超市 (全聯、家樂福)
    2. 百貨 (中壢大江現抵活動)
    3. 餐飲交通 (星巴克、中油加油)
    4. 線上購物 (Momo)
    
    請註明：最優支付方式與 CUBE/Richart 的方案切換建議。
    格式要求：使用 HTML 標籤 (<b>, <i>, <u>)，結構清晰。
    """
    
    # 使用新版 SDK 的生成語法
    response = client.models.generate_content(
        model="gemini-2.0-flash", # 使用 2026 最新主流模型
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
