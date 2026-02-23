import os, requests, json
from datetime import datetime, timedelta, timezone

# --- 1. 環境變數 ---
API_KEY = os.environ.get("GOOGLE_API_KEY")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_strategy():
    # 強制台北時區 (UTC+8)
    tz_tw = timezone(timedelta(hours=8))
    today_str = datetime.now(tz_tw).strftime("%Y-%m-%d, %A")

    # A. 自動模型偵測 (防 404)
    try:
        m_list = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}").json()
        available = [m['name'] for m in m_list.get('models', []) if 'generateContent' in m['supportedGenerationMethods']]
        target = next((x for x in ["models/gemini-1.5-flash", "models/gemini-1.5-pro"] if x in available), available[0])
    except: target = "models/gemini-1.5-flash"

    # B. 核心指令：支付方式深度分析 (排除 HTML Header)
    prompt = f"""
    今天是 {today_str}。請分析以下 7 張卡片今日在全台及桃園中壢的最優策略。
    卡片：永豐幣倍、中信uniopen、國泰CUBE、富邦Costco、富邦Momo、富邦J卡、台新Richart。

    【核心指令】
    1. 針對每個通路，必須明確分析「哪種支付方式」(如 Apple Pay, LINE Pay, icash Pay, 家樂福 Pay, 全支付, 或實體卡) 最划算。
    2. 通路包含：星巴克(週一專場)、統一集團(7-11/家樂福)、全聯/大全聯、蝦皮購物、中壢大江。
    3. 深度比較：
       · 星巴克：uniopen 實體卡買一送一 vs icash Pay 10% 點數回饋。
       · 統一集團：uniopen 聯名權益 vs icash Pay 加碼。
       · 全聯：全支付綁定不同卡片的點數效益。
       · 蝦皮：週一銀行日折扣碼與數位支付加碼。

    【格式規範 - 嚴格遵守】
    · 標題：<b>今日最佳策略分析 ({today_str})</b>
    · 禁止使用任何 HTML Header 標籤 (如 <h1>, <h2>, <h3>, <header>)。
    · 僅限使用 <b> 與 <i> 進行排版。
    · 通路名稱請加粗，並以「·」開頭清單。
    · 內容需包含「最優支付」、「推薦卡片」與「分析」三個重點。
    """

    url = f"https://generativelanguage.googleapis.com/v1beta/{target}:generateContent?key={API_KEY}"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        return res['candidates'][0]['content']['parts'][0]['text']
    except: return "⚠️ 系統產生訊息異常，請檢查 API 狀態。"

def send_tg(msg):
    if not (TG_TOKEN and TG_CHAT_ID): return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"})

if __name__ == "__main__":
    report = get_strategy()
    send_tg(report)
