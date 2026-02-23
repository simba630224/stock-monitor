import os
import requests
import json
from datetime import datetime
import pytz

# --- 1. 環境變數與時區設定 ---
# 請確保 GitHub Secrets 已設定這些變數
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

# 強制台北時區，解決 Telegram/Gmail 日期不一致問題
tw_tz = pytz.timezone('Asia/Taipei')

def log(msg):
    print(f"[{datetime.now(tw_tz).strftime('%H:%M:%S')}] {msg}")

def get_daily_strategy():
    if not api_key: return "ERROR: 缺少 API Key"

    # A. 自動嗅探可用模型 (解決 404)
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    target_model = "models/gemini-1.5-flash"
    try:
        m_resp = requests.get(list_url)
        available = [m['name'] for m in m_resp.json().get('models', []) 
                     if 'generateContent' in m.get('supportedGenerationMethods', [])]
        priority = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]
        for p in priority:
            if p in available:
                target_model = p
                break
    except: pass

    # B. 生成內容 (強化星巴克與 uniopen 分析)
    today = datetime.now(tw_tz).strftime("%Y-%m-%d (%A)")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，分析今日在桃園中壢與全台的最優策略。
    請僅檢索 2026 年或近一年內公佈且目前有效的活動，嚴禁推估。

    【核心任務】
    1. 比較「中信 uniopen」在統一企業通路(星巴克、7-11、家樂福)的優勢。
    2. 確認今日(週一)星巴克是否有特定支付加碼(如 icash Pay 10% 或 CUBE 3%)。
    3. 分析大江賀歲慶(滿1800現抵180)搭配 LINE Pay 的即時效益。
    
    【卡片名單】
    永豐幣倍、中信uniopen、國泰CUBE JCB、富邦Costco、富邦Momo、富邦J卡、台新Richart。

    【格式規範】
    · 僅限使用 <b> 與 <i>。
    · 標題加粗，清單用「·」開頭並換行。
    · 語氣專業、直接給結論。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"資訊產出異常: {str(e)}"

def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    # 加入 HTML 標籤容錯處理
    payload = {"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        requests.post(url, data={"chat_id": telegram_chat_id, "text": msg})

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
