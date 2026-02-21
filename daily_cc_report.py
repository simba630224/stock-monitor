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

# --- 2. 獲取 Gemini 策略分析 ---
def get_daily_strategy():
    if not api_key:
        return "ERROR: 缺少 GOOGLE_API_KEY"

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    # 嘗試多個模型 ID，解決部分帳號找不到特定模型的問題
    model_candidates = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-1.5-pro",
        "gemini-pro"
    ]
    
    last_error = ""
    for model_id in model_candidates:
        log(f"嘗試使用模型: {model_id}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        
        prompt_text = f"""
        今天是 {today}。請針對以下 7 張信用卡，分析今日在全台及桃園中壢地區的最優刷卡策略：
        1. 永豐幣倍卡
        2. 中信uniopen (統一集團/家樂福)
        3. 國泰CUBE JCB卡 (需手動切換方案)
        4. 富邦Costco
        5. 富邦Momo
        6. 富邦JCB/J卡 (悠遊卡加值)
        7. 台新Richart 卡

        【分析核心：行動支付最優搭配】
        請明確推薦以下支付方式的組合：
        - LINE Pay、全支付 (PX Pay Plus)、街口、icash Pay
        - Apple Pay、Costco Pay、家樂福 Pay (Carrefour Pay)

        【重點場景建議】
        - 家樂福：比較使用「家樂福 Pay」或「icash Pay」綁定 uniopen 卡。
        - Costco：使用「Costco Pay」或實體刷富邦Costco卡。
        - 全聯：使用「全支付」或「PX Pay」綁定 Richart 或 CUBE 卡。
        - 中壢大江/百貨：比較「LINE Pay」與實體刷卡的現抵活動。

        【格式規範】
        1. 僅限使用 <b>, <i>, <u>, <code>, <a> HTML 標籤。
        2. 標題用 <b>加粗</b>，清單用「·」符號並換行。
        3. 內容精簡，適合手機閱讀。
        """

        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        headers = {'Content-Type': 'application/json'}

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                data = response.json()
                log(f"成功使用模型: {model_id}")
                return data['candidates'][0]['content']['parts'][0]['text']
            else:
                last_error = f"{response.status_code}: {response.text}"
                log(f"模型 {model_id} 失敗: {last_error}")
        except Exception as e:
            last_error = str(e)
            log(f"模型 {model_id} 異常: {last_error}")

    return f"Gemini 呼叫均失敗。最後錯誤: {last_error}"

# --- 3. Telegram 傳送函式 ---
def send_telegram_notify(msg):
    if not telegram_token or not telegram_chat_id:
        log("缺少 Telegram 設定")
        return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        log(f"Telegram 傳送失敗: {r.text}")
        payload["parse_mode"] = "" # 失敗時改用純文字
        requests.post(url, data=payload)
    else:
        log("Telegram 訊息已成功送出")

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
