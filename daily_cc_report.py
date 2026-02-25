import os, requests, json
from datetime import datetime, timedelta, timezone

# --- 1. 環境變數 ---
API_KEY = os.environ.get("GOOGLE_API_KEY")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_strategy():
    tz_tw = timezone(timedelta(hours=8))
    today_str = datetime.now(tz_tw).strftime("%Y-%m-%d, %A")

    # A. 模型偵測
    try:
        m_list = requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}").json()
        available = [m['name'] for m in m_list.get('models', []) if 'generateContent' in m['supportedGenerationMethods']]
        target = next((x for x in ["models/gemini-1.5-flash", "models/gemini-1.5-pro"] if x in available), available[0])
    except: target = "models/gemini-1.5-flash"

    # B. 核心指令：強化「點數加碼」與「uniopen 優先權」
    prompt = f"""
    今天是 {today_str}。請針對以下 7 張卡片分析今日最優策略：
    永豐幣倍、中信uniopen、國泰CUBE、富邦Costco、富邦Momo、富邦J卡、台新Richart。

    【核心邏輯強化 - 嚴格執行】
    1. 家樂福/7-11：中信 uniopen 綁定「家樂福 Pay」或「icash Pay」為首選，分析其 6-10% OPENPOINT 回饋與點數整合優勢，必須優於國泰 CUBE (3%)。
    2. 星巴克：週一首選 uniopen 實體卡「買一送一」，次選 icash Pay 加碼。
    3. 全聯：搜尋今日有無「全支付」或「PX Pay」點數加碼（如平日滿額贈點）。
    4. 蝦皮：搜尋今日「週三/週一銀行日」特定折扣碼與數位加碼。
    5. 點數加碼特區：針對每個通路，必須搜尋並列出「當期點數加碼活動」。

    【格式規範】
    · 標題：<b>今日最佳策略分析 ({today_str})</b>
    · 嚴禁 HTML Header 標籤 (H1~H3)。僅限用 <b> 與 <i>。
    · 內容結構：通路名稱加粗 -> 最優支付 -> 推薦卡片 -> 當期點數加碼/分析。
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
