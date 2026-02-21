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

# --- 2. 動態偵測模型並生成內容 ---
def get_daily_strategy():
    if not api_key: return "ERROR: 缺少 GOOGLE_API_KEY"

    # A. 偵測可用模型清單 (徹底解決 404 問題)
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = None
    try:
        log("正在向 Google 查詢您的帳號可用模型...")
        m_resp = requests.get(list_url)
        m_data = m_resp.json()
        
        # 篩選出支援生成內容且名稱中包含 gemini 的模型
        available = [
            m['name'] for m in m_data.get('models', []) 
            if 'generateContent' in m.get('supportedGenerationMethods', [])
        ]
        
        # 優先順序：1.5-flash > 1.5-pro > 1.0-pro
        priority = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]
        for p in priority:
            if p in available:
                target_model = p
                break
        
        if not target_model and available:
            target_model = available[0]
            
        log(f"成功偵測到可用模型: {target_model}")
    except Exception as e:
        log(f"模型偵測異常: {e}")
        target_model = "models/gemini-1.5-flash" # 保底嘗試

    # B. 請求內容生成
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}（農曆正月初五）。請針對以下 7 張信用卡，分析今日在桃園及全台的最優刷卡策略：
    1. 永豐幣倍卡、2. 中信uniopen、3. 國泰CUBE JCB、4. 富邦Costco、5. 富邦Momo、6. 富邦J/J卡、7. 台新Richart卡。

    【支付方式最優化比較】
    請明確指示在不同通路應使用哪種支付方式回饋最高：
    · LINE Pay / 全支付 / 街口支付 / icash Pay
    · Apple Pay / Costco Pay / 家樂福 Pay (Carrefour Pay)

    【核心場景指引】
    · 全聯：全支付綁定 Richart 或 CUBE 方案比較。
    · 家樂福：必用「家樂福 Pay」或「icash Pay」綁定 uniopen 卡。
    · Costco：Costco Pay 與聯名卡搭配。
    · 百貨：中壢大江賀歲慶現抵活動 (LINE Pay 搭配卡片加碼)。
    · 交通/餐飲：星巴克、中油加油 (實體感應或行動支付)。

    【格式規範】
    1. 僅限使用 <b> 與 <i> 標籤。
    2. 禁止使用 <u>, <h3>, <ul>, <li>, <br> 等標籤。
    3. 標題請直接用 <b>加粗</b>，清單請用「·」符號開頭並換行。
    4. 內容要精確且適合手機快速閱讀。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            log(f"生成內容失敗 ({response.status_code}): {response.text}")
            return f"Gemini 服務目前不可用 (Code: {response.status_code})"
    except Exception as e:
        return f"執行異常: {str(e)}"

# --- 3. Telegram 傳送 ---
def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id:
        log("錯誤: 缺少 Telegram 設定")
        return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        log(f"HTML 發送失敗，嘗試純文字。原因: {r.text}")
        payload["parse_mode"] = ""
        requests.post(url, data=payload)
    else:
        log("Telegram 報告發送成功！")

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
