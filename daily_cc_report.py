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

# --- 2. 獲取可用模型並生成內容 ---
def get_daily_strategy():
    if not api_key: return "ERROR: 缺少 GOOGLE_API_KEY"

    # A. 自動偵測可用模型
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = "models/gemini-1.5-flash"
    try:
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        valid_models = [m['name'] for m in m_data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        for pref in ["models/gemini-1.5-flash", "models/gemini-1.5-pro"]:
            if pref in valid_models:
                target_model = pref
                break
        log(f"使用模型: {target_model}")
    except Exception: pass

    # B. 請求內容生成
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    # 調整 Prompt：聚焦於 2026 年已公佈且延續至今的優惠
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，分析今日在桃園及全台的最優刷卡策略。
    請檢索 2026 年已公佈且有效期包含今日的活動資訊，禁止使用「歷史推估」或「需以銀行公告為準」等免責聲明。

    【分析對象】
    1. 永豐幣倍卡
    2. 中信uniopen (統一/家樂福)
    3. 國泰CUBE JCB (需切換方案)
    4. 富邦Costco
    5. 富邦Momo
    6. 富邦J/J卡 (悠遊卡加值)
    7. 台新Richart卡 (如 @GoGo 卡)

    【支付方式最優化】
    請明確指示通路應搭配哪種支付方式：
    LINE Pay、全支付、街口、icash Pay、Apple Pay、Costco Pay、家樂福 Pay。

    【核心場景】
    · 全聯：全支付綁定 Richart (3.8%) 或 CUBE (2%) 的週末贈點。
    · 家樂福：家樂福 Pay 或 icash Pay 綁定 uniopen 點數回饋。
    · Costco：Costco Pay 與聯名卡。
    · 百貨：中壢大江賀歲慶現抵活動 (滿1800現抵180)。
    · 交通：中油加油最優支付。

    【HTML 格式規範】
    1. 僅限使用 <b> 與 <i>。
    2. 禁止使用 <u>, <h3>, <ul>, <li>, <br>。
    3. 標題請直接用 <b>加粗</b>，清單用「·」符號並換行。
    4. 內容要確定、具體，直接給出結論。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"今日優惠連線中，請稍後重試 (Code: {response.status_code})"
    except Exception as e:
        return f"執行異常: {str(e)}"

# --- 3. Telegram 傳送 ---
def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
