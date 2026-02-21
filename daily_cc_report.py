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

# --- 2. 核心功能：多路徑備援生成 ---
def get_daily_strategy():
    if not api_key: return "ERROR: 缺少 GOOGLE_API_KEY"

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    # 指令：鎖定 2026 年已公佈之具體活動
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，分析今日在桃園及全台的最優刷卡策略。
    請檢索 2026 年已公佈且延續至今日的具體回饋（如 Richart 2026 權益、大江賀歲慶規則等）。
    【嚴格執行】禁止使用「歷史推估」或「權益以公告為準」等詞彙。

    【分析對象】
    1. 永豐幣倍卡、2. 中信uniopen、3. 國泰CUBE JCB、4. 富邦Costco、5. 富邦Momo、6. 富邦J/J卡、7. 台新Richart卡。

    【核心場景與支付】
    · 全聯：全支付綁定卡片(如Richart 3.8%或CUBE 2%)之週六贈點。
    · 家樂福：家樂福 Pay 或 icash Pay 綁定 uniopen 獲取週末9折券與 Open Point。
    · Costco：Costco Pay 與聯名卡 2026 店內回饋。
    · 百貨：中壢大江賀歲慶(滿1800現抵180) 搭配 LINE Pay 支付。
    · 交通：中油加油最優搭配。

    【格式規範】
    1. 僅限使用 <b> 與 <i> 標籤。
    2. 標題用 <b>加粗</b>，清單用「·」符號開頭並換行。
    3. 語氣堅定，直接給出結論。
    """

    # 嘗試不同的 API 路徑與版本組合 (解決 404 問題)
    endpoints = [
        ("v1beta", "gemini-1.5-flash"),
        ("v1", "gemini-1.5-flash"),
        ("v1beta", "gemini-pro"),
        ("v1", "gemini-pro")
    ]

    for version, model in endpoints:
        log(f"嘗試路徑: {version} -> {model}")
        url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        headers = {'Content-Type': 'application/json'}

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code == 200:
                log(f"成功連線至 {model}")
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                log(f"失敗: {response.status_code}")
        except Exception as e:
            log(f"異常: {str(e)}")

    return "所有 API 路徑均失效，請確認 Google Cloud 專案權限。"

# --- 3. Telegram 傳送 ---
def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
