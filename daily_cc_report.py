import os
import requests
import json
from datetime import datetime

# --- 1. 環境變數檢查 ---
# 這些變數應設定於 GitHub Repo > Settings > Secrets and variables > Actions
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# --- 2. 獲取 Gemini 策略分析 ---
def get_daily_strategy():
    if not api_key:
        return "ERROR: 缺少 GOOGLE_API_KEY"

    # A. 偵測可用模型 (避免 404 錯誤)
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        available_models = [m['name'] for m in m_data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        # 優先順序: 1.5-flash > 1.5-pro > gemini-pro
        target_model = "models/gemini-1.5-flash"
        for candidate in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]:
            if candidate in available_models:
                target_model = candidate
                break
        log(f"選定模型: {target_model}")
    except Exception as e:
        log(f"模型偵測異常: {e}")
        target_model = "models/gemini-1.5-flash"

    # B. 請求內容生成
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    # 嚴格限制 HTML 標籤以符合 Telegram 規範
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    1. 永豐幣倍卡
    2. 中信uniopen
    3. 國泰CUBE JCB卡
    4. 富邦Costco
    5. 富邦Momo
    6. 富邦JCB/J卡
    7. 台新Richart 卡
    
    分析重點：
    - 量販超市：全聯(週末1300送650點)、家樂福(週末2000享9折)。
    - 百貨：中壢大江(賀歲慶現抵活動)。
    - 餐飲交通：星巴克、中油加油。
    
    【格式規範 - 非常重要】
    1. 僅限使用 <b>, <i>, <u>, <code>, <a> 這五種 HTML 標籤。
    2. 禁止使用 <h3>, <h2>, <h1>, <ul>, <li> 等標籤。
    3. 標題請用 <b>加粗</b> 表示，清單請用「·」符號開頭並換行。
    4. 內容要精簡、易讀，適合手機查看。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            log(f"API 錯誤: {response.text}")
            return f"Gemini 呼叫失敗 ({response.status_code})"
            
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"執行異常: {str(e)}"

# --- 3. Telegram 傳送函式 (整合版) ---
def send_telegram_notify(msg):
    log("準備傳送 Telegram 訊息...")
    if not telegram_token or not telegram_chat_id:
        log("錯誤: 缺少 Telegram 設定")
        return

    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id": telegram_chat_id, 
        "text": msg, 
        "parse_mode": "HTML"
    }
    
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        log(f"HTML 傳送失敗，嘗試純文字模式... 錯誤: {r.text}")
        payload["parse_mode"] = ""
        requests.post(url, data=payload)
    else:
        log("訊息發送成功！")

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
