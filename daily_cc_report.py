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
    if not api_key:
        return "ERROR: 缺少 GOOGLE_API_KEY"

    # A. 獲取可用清單並過濾可用的生成模型
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = None
    
    try:
        log("正在偵測您的帳號可用模型...")
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        
        if "models" not in m_data:
            log(f"無法取得模型清單: {m_data}")
            return "無法連線至 Gemini 服務"

        # 過濾出支援 generateContent 的模型
        available_models = [
            m['name'] for m in m_data['models'] 
            if 'generateContent' in m.get('supportedGenerationMethods', [])
        ]
        
        # 優先級：1.5-flash > 1.5-pro > gemini-pro (1.0) > 任何清單中第一個
        priority = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]
        for p in priority:
            if p in available_models:
                target_model = p
                break
        
        if not target_model and available_models:
            target_model = available_models[0]
            
        log(f"成功匹配可用模型: {target_model}")
    except Exception as e:
        log(f"模型偵測異常: {e}")
        target_model = "models/gemini-1.5-flash" # 保底強制嘗試

    # B. 呼叫選定的模型路徑
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    # 這裡使用更精簡的路徑構造
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}（農曆正月初五）。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    1. 永豐幣倍卡
    2. 中信uniopen
    3. 國泰CUBE JCB卡
    4. 富邦Costco
    5. 富邦Momo
    6. 富邦JCB/J卡
    7. 台新Richart 卡
    
    分析重點：
    - 量販超市：全聯(週末1300送650點)、家樂福(週末2000享9折)。
    - 百貨：中壢大江(賀歲慶現抵活動最後階段)。
    - 餐飲交通：星巴克春節限定、中油加油。
    
    【格式規範】
    1. 僅限使用 <b>, <i>, <u>, <code>, <a> HTML 標籤。
    2. 標題用 <b>加粗</b>，清單用「·」符號並換行。
    3. 針對桃園中壢地區特色（如大江）提供建議。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            log(f"API 呼叫失敗 ({response.status_code}): {response.text}")
            return f"今日優惠更新中，請稍後再試 (代碼: {response.status_code})"
            
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        log(f"執行異常: {e}")
        return f"系統連線異常: {str(e)}"

# --- 3. Telegram 傳送函式 ---
def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id:
        log("缺少 Telegram 設定")
        return

    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        log("HTML 格式失敗，改發純文字")
        payload["parse_mode"] = ""
        requests.post(url, data=payload)
    else:
        log("Telegram 訊息發送成功")

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
