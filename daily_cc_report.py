import os, requests, json
from datetime import datetime, timedelta, timezone

# --- 1. 環境變數 ---
API_KEY = os.environ.get("GOOGLE_API_KEY")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_strategy():
    # 強制台北時區 (UTC+8)
    tz_tw = timezone(timedelta(hours=8))
    now = datetime.now(tz_tw)
    today_str = now.strftime("%Y-%m-%d, %A")

    # A. 自動模型偵測 (防 404)
    try:
        m_list = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}").json()
        available = [m['name'] for m in m_list.get('models', []) if 'generateContent' in m['supportedGenerationMethods']]
        target = next((x for x in ["models/gemini-1.5-flash", "models/gemini-1.5-pro"] if x in available), available[0])
    except: target = "models/gemini-1.5-flash"

    # B. 核心指令 (包含星巴克、統一、大江、全聯、蝦皮)
    prompt = f"""
    今天是 {today_str}。請針對以下 7 張卡片，分析今日在桃園中壢與全台的最優策略。
    卡片：永豐幣倍、中信uniopen、國泰CUBE、富邦Costco、富邦Momo、富邦J卡、台新Richart。
    
    【格式規範】
    標題：今日最佳策略分析 ({today_str})
    請務必分為以下章節：
    1. 星巴克週一專場 (比較 uniopen 買一送一與 icash Pay)
    2. 統一集團消費 (7-11、家樂福：分析 uniopen 與 icash Pay 效益)
    3. 全聯/大全聯 (分析週一平日之點數或支付最優選，如全支付搭配卡片)
    4. 蝦皮購物 (分析週一銀行日折扣碼或數位支付回饋，如 CUBE 玩數位或 Richart 3.8%)
    5. 中壢大江購物中心 (賀歲慶 1800現抵180 搭配 LINE Pay 分析)
    6. 其他卡片與考量 (Costco、Momo 卡之當日適用性)
    7. 總結建議

    注意：
    · 僅限用 <b> 與 <i> 標籤。
    · 標題加粗，清單用「·」並換行。
    · 嚴禁歷史推估，需確認 2026 年當日有效權益。
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
