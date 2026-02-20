import os
import requests
import json
from datetime import datetime

# --- 1. 環境變數 ---
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# --- 2. 自動選擇模型並獲取策略 ---
def get_daily_strategy():
    if not api_key:
        return "錯誤：找不到 GOOGLE_API_KEY，請檢查 GitHub Secrets。"
    
    # A. 先獲取可用模型列表
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        models = [m['name'] for m in m_data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        # 優先順序：1.5-flash > 1.5-pro > gemini-pro (1.0)
        target_model = None
        for m_id in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]:
            if m_id in models:
                target_model = m_id
                break
        
        if not target_model:
            target_model = models[0] if models else "models/gemini-pro"
            
    except Exception:
        target_model = "models/gemini-1.5-flash" # 保底

    # B. 呼叫選定的模型
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    永豐幣倍卡、中信uniopen、國泰CUBE JCB卡、富邦Costco、富邦Momo、富邦JCB/J卡、台新Richart 卡。
    
    分析重點：
    1. 量販超市：全聯(國泰CUBE 2%)、家樂福(中信uniopen 4%)。
    2. 百貨：中壢大江(賀歲慶現抵 10% 倒數中)。
    3. 餐飲交通：星巴克週五外送買一送一、中油加油。
    4. 線上購物：Momo 購物。
    
    請註明：最優支付方式與 CUBE/Richart 的方案切換建議。
    格式要求：使用 HTML 標籤(<b>, <i>, <u>)，結構清晰美觀。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"Gemini 呼叫失敗 ({target_model}): {str(e)}"

def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id: return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
