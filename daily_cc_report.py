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

    # A. 嘗試列出可用模型，確保不踩 404
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = None
    try:
        log("正在向伺服器查詢您的可用模型清單...")
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        
        # 篩選出支援生成內容的模型
        valid_models = [
            m['name'] for m in m_data.get('models', []) 
            if 'generateContent' in m.get('supportedGenerationMethods', [])
        ]
        
        # 優先級排序
        for pref in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]:
            if pref in valid_models:
                target_model = pref
                break
        
        if not target_model and valid_models:
            target_model = valid_models[0]
            
        if not target_model:
            log("警告: 清單為空，嘗試保底路徑")
            target_model = "models/gemini-1.5-flash"
            
        log(f"最終選定呼叫路徑: {target_model}")
    except Exception as e:
        log(f"清單查詢異常: {e}")
        target_model = "models/gemini-1.5-flash"

    # B. 呼叫生成
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}（農曆正月初五）。請針對以下 7 張信用卡，分析今日在桃園及全台的最優刷卡策略：
    1. 永豐幣倍卡、2. 中信uniopen、3. 國泰CUBE JCB、4. 富邦Costco、5. 富邦Momo、6. 富邦J/J卡、7. 台新Richart卡。

    【支付方式最優化】
    請明確指出使用 LINE Pay、全支付、街口、icash pay、Apple Pay、Costco Pay 或 家樂福Pay (Carrefour Pay) 哪種最划算。

    【核心場景】
    · 全聯：比較「全支付」綁Richart或CUBE方案。
    · 家樂福：使用「家樂福 Pay」或「icash Pay」搭配 uniopen 效益。
    · Costco：推薦「Costco Pay」與聯名卡。
    · 百貨：中壢大江賀歲慶現抵活動（LINE Pay搭配卡片回饋）。
    · 交通：中油加油(Apple Pay或實體感應)。

    【格式規範】
    1. 僅限使用 <b>, <i>, <u>, <code>, <a> HTML 標籤。
    2. 標題用 <b>加粗</b>，清單用「·」符號並換行。
    3. 針對桃園中壢特色提供建議，格式需精簡。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"Gemini 呼叫失敗 ({response.status_code}): {response.text}"
    except Exception as e:
        return f"執行異常: {str(e)}"

# --- 3. Telegram 傳送 ---
def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id: return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        # 失敗時嘗試純文字
        payload["parse_mode"] = ""
        requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
