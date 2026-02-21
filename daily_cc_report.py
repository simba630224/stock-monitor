import os
import requests
import json
from datetime import datetime

# --- 1. 環境變數 ---
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def get_daily_strategy():
    if not api_key: return "ERROR: 缺少 GOOGLE_API_KEY"

    # 動態偵測模型
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = "models/gemini-1.5-flash"
    try:
        m_resp = requests.get(list_url)
        available = [m['name'] for m in m_resp.json().get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        for p in ["models/gemini-1.5-flash", "models/gemini-pro"]:
            if p in available: target_model = p; break
    except: pass

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    # 指令優化：明確要求實時數據
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張卡片，檢索並分析「當日實際公告」的最優支付策略，禁止使用「歷史推估」或「常態優惠」等字眼。
    卡片：1.永豐幣倍 2.中信uniopen 3.國泰CUBE 4.富邦Costco 5.富邦Momo 6.富邦J卡 7.台新Richart卡。

    【支付分析要求】
    1. 比較 LINE Pay, 全支付, 街口, icash Pay, Apple Pay, Costco/家樂福 Pay。
    2. 必須包含今日(週六)的具體加碼：如全聯/家樂福的週末滿額贈點。
    3. 中壢大江「馬年賀歲慶」的現抵 180 元活動必須納入計算。

    【格式與語氣】
    1. 僅限 <b>, <i> 標籤。標題加粗。
    2. 內容必須是「確定的當日活動」，非推測資訊。
    3. 語氣要堅定、專業。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        return "暫時無法獲取實時優惠資訊，請稍後再試。"

def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    requests.post(url, data={"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"})

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
