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

# --- 2. 核心功能：具體錯誤回報生成 ---
def get_daily_strategy():
    if not api_key: return "ERROR: 缺少 GOOGLE_API_KEY，請檢查 GitHub Secrets 設定。"

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    
    # 嚴格指令：基於 2026 年既有權益，禁止模糊推估
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，分析今日在桃園及全台的最優刷卡策略。
    請檢索 2026 年已公佈之具體活動（如 Richart 2026 權益、大江賀歲慶規章）。
    【絕對禁止】使用「歷史推估」或「權益以公告為準」等詞彙。

    卡片：1.永豐幣倍 2.中信uniopen 3.國泰CUBE 4.富邦Costco 5.富邦Momo 6.富邦J卡 7.台新Richart。
    支付：LINE Pay, 全支付, 街口, icash Pay, Apple Pay, Costco Pay, 家樂福 Pay。
    
    分析重點：
    · 全聯：週六全支付加碼 650 點活動。
    · 家樂福：週末滿 2000 元 9 折與 uniopen 搭配。
    · 百貨：中壢大江賀歲慶滿 1800 現抵 180。

    格式：僅限使用 <b> 與 <i> 標籤。標題加粗，清單用「·」開頭並換行。
    """

    # 嘗試最標準的兩個模型路徑
    endpoints = [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        "https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent"
    ]

    error_logs = []
    for url_base in endpoints:
        full_url = f"{url_base}?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        
        try:
            response = requests.post(full_url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                # 擷取具體的錯誤原因
                err_msg = response.json().get('error', {}).get('message', '未知錯誤')
                error_logs.append(f"路徑 {url_base.split('/')[-2]} 失敗 ({response.status_code}): {err_msg}")
        except Exception as e:
            error_logs.append(f"連線異常: {str(e)}")

    # 如果全數失敗，將詳細原因回傳給 Telegram 進行最後偵錯
    debug_report = "<b>❌ API 呼叫全數失敗</b>\n\n" + "\n".join(error_logs)
    return debug_report

def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
