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
    if not api_key: return "ERROR: 缺少 API Key"

    # A. 先抓取該 Key 真正能用的模型清單
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = None
    try:
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        # 尋找支援生成內容的模型
        valid_models = [m['name'] for m in m_data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        # 優先級：1.5-flash > 1.5-pro > gemini-pro
        for m in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]:
            if m in valid_models:
                target_model = m
                break
        if not target_model and valid_models:
            target_model = valid_models[0]
            
        if not target_model:
            return "您的 API Key 目前未分配到任何生成模型，請至 AI Studio 確認配額。"
    except:
        target_model = "models/gemini-pro" # 最後保底

    # B. 呼叫生成
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張卡片，分析今日在桃園及全台的最優策略。
    請依據 2026 年已公佈之具體權益，禁止使用「歷史推估」或「權益以公告為準」。

    卡片：1.永豐幣倍 2.中信uniopen 3.國泰CUBE 4.富邦Costco 5.富邦Momo 6.富邦J卡 7.台新Richart。
    重點：中壢大江賀歲慶現抵活動、全聯週六贈點、家樂福週末9折。
    支付：LINE Pay, 全支付, 街口, icash Pay, Apple Pay, Costco/家樂福 Pay。

    格式：僅限使用 <b> 與 <i> 標籤。標題加粗，清單用「·」並換行。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"生成失敗: {str(e)}"

def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    requests.post(url, data={"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"})

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
