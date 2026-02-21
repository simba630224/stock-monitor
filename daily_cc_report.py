import os
import requests
import json
from datetime import datetime

# --- 1. 環境變數檢查 ---
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# --- 2. 獲取可用模型並生成內容 ---
def get_daily_strategy():
    if not api_key:
        return "ERROR: 缺少 GOOGLE_API_KEY"

    # A. 偵測可用模型
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = "models/gemini-1.5-flash" 
    
    try:
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        if "models" in m_data:
            available_models = [m['name'] for m in m_data['models'] if 'generateContent' in m.get('supportedGenerationMethods', [])]
            priority = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]
            for p in priority:
                if p in available_models:
                    target_model = p
                    break
        log(f"選定執行模型: {target_model}")
    except Exception as e:
        log(f"模型偵測異常: {e}")

    # B. 請求內容生成
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    # 強化行動支付比較邏輯，加入 Costco Pay 與 家樂福 Pay
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，分析今日在全台及桃園地區的最優刷卡策略：
    1. 永豐幣倍卡
    2. 中信uniopen (統一集團/家樂福)
    3. 國泰CUBE JCB卡 (需手動切換方案)
    4. 富邦Costco
    5. 富邦Momo
    6. 富邦JCB/J卡 (悠遊卡加值)
    7. 台新Richart 卡 (如 @GoGo 卡)

    【分析核心：行動支付最優搭配】
    請針對每個消費場景，明確比較並推薦應使用哪種支付方式回饋最高：
    - LINE Pay、街口支付 (JKO Pay)
    - 全支付 (PX Pay Plus)、icash Pay
    - 家樂福 Pay (Carrefour Pay)、Costco Pay
    - Apple Pay / 實體刷卡

    【重點場景建議】
    - 家樂福：比較使用「家樂福 Pay」綁定 uniopen 或 Richart 卡的優惠（週末常有9折）。
    - Costco：使用「Costco Pay」或實體刷富邦Costco聯名卡。
    - 全聯：使用「全支付」或「PX Pay」綁定 Richart 或 CUBE 卡的點數加碼。
    - 中壢大江/百貨：比較「LINE Pay」與實體刷卡的現抵活動。
    - 餐飲交通：星巴克、中油加油的最優解。

    【格式規範】
    1. 僅限使用 <b>, <i>, <u>, <code>, <a> HTML 標籤。
    2. 標題用 <b>加粗</b>，清單用「·」符號並換行。
    3. 內容需直觀、精簡，直接告訴我「通路+卡片+支付方式」。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"Gemini 呼叫失敗: {str(e)}"

# --- 3. Telegram 傳送函式 ---
def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id:
        log("缺少 Telegram 設定")
        return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        log(f"HTML 解析失敗，改發純文字。錯誤: {r.text}")
        payload["parse_mode"] = ""
        requests.post(url, data=payload)
    else:
        log("Telegram 訊息已送出")

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
