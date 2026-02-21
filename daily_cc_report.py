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

# --- 2. 獲取 2026 年度權益與活動報告 ---
def get_daily_strategy():
    if not api_key: return "ERROR: 缺少 GOOGLE_API_KEY"

    # 使用 v1 官方穩定路徑，直接指定模型名稱，避開 v1beta 的 404 問題
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    # 指令優化：聚焦於 2026 年已公佈並延續至今的具體回饋
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，分析今日在桃園及全台的最優刷卡組合。
    請依據 2026 年已公佈且適用於今日的權益、週末常規加碼與賀歲專案進行分析。
    【禁止】使用「歷史推估」或「權益以銀行公告為準」等詞彙。

    【分析對象】
    1. 永豐幣倍卡、2. 中信uniopen、3. 國泰CUBE JCB、4. 富邦Costco、5. 富邦Momo、6. 富邦J/J卡、7. 台新Richart卡。

    【支付工具最優搭配】
    請明確指示通路應搭配哪種支付方式回饋最高：
    LINE Pay、全支付、街口、icash Pay、Apple Pay、Costco Pay、家樂福 Pay。

    【核心場景指引】
    · 全聯：今日(週六)使用全支付綁定卡片(如Richart 3.8%或CUBE 2%)之週末贈點效益。
    · 家樂福：家樂福 Pay 或 icash Pay 綁定 uniopen 獲取週末9折券與點數加碼。
    · Costco：Costco Pay 與聯名卡 2026 權益。
    · 百貨：中壢大江賀歲慶現抵活動 (單筆滿1800現抵180) 搭配 LINE Pay 回饋。
    · 交通：中油加油最優支付組合。

    【格式規範】
    1. 僅限使用 <b> 與 <i> 標籤。
    2. 禁止使用 <u>, <h3>, <ul>, <li>, <br> 標籤。
    3. 標題用 <b>加粗</b>，清單用「·」符號開頭並換行。
    4. 語氣需堅定具體，直接給出刷卡建議。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            log(f"API 失敗: {response.status_code} - {response.text}")
            return f"今日優惠資訊彙整中 (Code: {response.status_code})"
    except Exception as e:
        return f"執行異常: {str(e)}"

# --- 3. Telegram 傳送函式 ---
def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
