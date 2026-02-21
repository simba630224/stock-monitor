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
    except Exception: pass

    # B. 請求內容生成 (強化 2026 支付邏輯)
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，精準分析今日在桃園中壢與全台的最優支付策略：
    1. 永豐幣倍卡、2. 中信uniopen、3. 國泰CUBE JCB、4. 富邦Costco、5. 富邦Momo、6. 富邦J/J卡、7. 台新Richart卡。

    【支付工具優先級分析】
    請明確指出使用 LINE Pay、全支付、街口、icash Pay、Apple Pay、Costco Pay、家樂福 Pay 哪種組合回饋最高。

    【核心場景指引】
    · 全聯：比較「全支付」綁Richart(3.8%)或CUBE(切換集精選2%)。
    · 家樂福：必用「家樂福 Pay」或「icash Pay」綁uniopen卡的點數加碼。
    · 中壢大江：針對賀歲慶，比較「LINE Pay」綁Richart卡(13.8%)的現抵優勢。
    · 加油：中油直營店使用實體感應或Apple Pay綁Richart卡(3.3%)。
    · 星巴克：中信uniopen於統一生態系的點數回饋。

    【HTML 格式規範 - 極重要】
    1. 僅限使用 <b> (粗體) 與 <i> (斜體) 標籤。
    2. 禁止使用 <u> (底線), <h3>, <ul>, <li>, <br> 標籤。
    3. 標題請直接用 <b>加粗</b>，清單請用「·」符號並配合換行。
    4. 結尾附上一句今日桃園天氣或生活小撇步。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        return f"Gemini 呼叫失敗 ({response.status_code})"
    except Exception as e:
        return f"執行異常: {str(e)}"

def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id: return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
