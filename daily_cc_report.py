import os
import requests
import json
from datetime import datetime, timedelta, timezone

# --- 1. 環境變數 ---
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

def get_daily_strategy():
    # 強制台北時區 (UTC+8)，解決 Telegram/Gmail 日期不一致問題
    tz_taipei = timezone(timedelta(hours=8))
    today = datetime.now(tz_taipei).strftime("%Y-%m-%d (%A)")
    
    # A. 模型嗅探邏輯 (防禦 404)
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = "models/gemini-1.5-flash"
    try:
        m_resp = requests.get(list_url)
        available = [m['name'] for m in m_resp.json().get('models', []) 
                     if 'generateContent' in m.get('supportedGenerationMethods', [])]
        for p in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]:
            if p in available: target_model = p; break
    except: pass

    # B. 核心指令：星巴克與統一集團強化
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張卡片分析今日在桃園中壢與全台的最優策略。
    請檢索過去一年內公佈且有效期包含今日的活動，嚴禁推估。

    【重點店家分析】
    · 星巴克：深度比較使用「中信 uniopen」與其他支付（如 icash Pay 或 CUBE 方案）的優劣。
    · 統一集團（7-11/家樂福）：確認 uniopen 是否為目前最優解，或有更好的點數加碼。
    · 全聯/大江：分析今日（週一）之特定活動效益。

    【卡片清單】
    永豐幣倍、中信uniopen、國泰CUBE JCB、富邦Costco、富邦Momo、富邦J卡、台新Richart。

    【格式】僅限使用 <b> 與 <i>。標題加粗，清單用「·」並換行。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"執行異常: {str(e)}"

def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    requests.post(url, data={"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"})

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
