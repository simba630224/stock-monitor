import os
import requests
import json
from datetime import datetime

# --- 1. 環境變數 ---
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- 2. 獲取 Gemini 策略分析 ---
def get_daily_strategy():
    if not api_key:
        return "錯誤：找不到 GOOGLE_API_KEY，請檢查 GitHub Secrets。"
    
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    # 修正後的 v1beta URL，這是目前支援 gemini-1.5-flash 最穩定的路徑
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    永豐幣倍卡、中信uniopen、國泰CUBE JCB卡、富邦Costco、富邦Momo、富邦JCB/J卡、台新Richart 卡。
    
    分析重點：
    1. 量販超市：全聯（國泰CUBE 2%）、家樂福（中信uniopen 4%）。
    2. 百貨商場：中壢大江（賀歲慶現抵 10% 倒數中）。
    3. 餐飲交通：星巴克週五外送買一送一、中油加油。
    4. 線上購物：Momo 購物。
    
    請註明：每張卡最優支付方式與 CUBE/Richart 的方案切換建議。
    格式要求：使用 HTML 標籤（如 <b>, <i>, <u>），避免使用 Markdown 星號，確保 Telegram 顯示美觀。
    """

    payload = {
        "contents": [{
            "parts": [{"text": prompt_text}]
        }]
    }
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        # 增加詳細錯誤回報，若 404 則顯示完整回應
        if response.status_code != 200:
            return f"Gemini API 呼叫失敗: {response.status_code}\n{response.text}"
            
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"程式執行異常: {str(e)}"

# --- 3. Telegram 傳送函式 ---
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
