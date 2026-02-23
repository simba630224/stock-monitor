import os, requests, json
from datetime import datetime, timedelta, timezone

# --- 設定 ---
API_KEY = os.environ.get("GOOGLE_API_KEY")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_report():
    # A. 時區與日期校準 (UTC+8)
    tz_tw = timezone(timedelta(hours=8))
    today_str = datetime.now(tz_tw).strftime("%Y-%m-%d (%A)")

    # B. 終極解決 404：自動獲取「您這把 Key 能用」的模型
    try:
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
        m_list = requests.get(list_url).json()
        # 尋找支援 generateContent 的模型，優先級：1.5-flash > 1.5-pro > gemini-pro
        available = [m['name'] for m in m_list.get('models', []) if 'generateContent' in m['supportedGenerationMethods']]
        target = next((x for x in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"] if x in available), available[0] if available else None)
        if not target: return "❌ 您的 API Key 目前無可用模型權限。"
    except:
        target = "models/gemini-1.5-flash" # 保底

    # C. 指令強化 (星巴克、大江、uniopen 比較)
    prompt = f"""
    今天是 {today_str}。請分析以下 7 張卡片今日在桃園中壢與全台的最優策略。
    卡片：永豐幣倍、中信uniopen、國泰CUBE、富邦Costco、富邦Momo、富邦J卡、台新Richart。
    
    【分析重點】
    1. 星巴克週一專場：中信 uniopen 享買一送一(實體)，與 icash Pay 16% 點數回饋(注意2月額滿狀況)比較，給出今日最優選。
    2. 統一集團：確認 uniopen 在 7-11、家樂福的點數回饋率，並比較 icash Pay 加碼活動。
    3. 中壢大江：賀歲慶(1800現抵180)搭配 LINE Pay 支付之效益。
    
    格式：僅限用 <b> 與 <i> 標籤。標題加粗，清單用「·」並換行。
    """

    # D. 呼叫生成
    url = f"https://generativelanguage.googleapis.com/v1beta/{target}:generateContent?key={API_KEY}"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        return res['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"⚠️ 生成失敗，API 回傳：{json.dumps(res) if 'res' in locals() else str(e)}"

def send_tg(msg):
    if not (TG_TOKEN and TG_CHAT_ID): return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"})

if __name__ == "__main__":
    report = get_report()
    send_tg(report)
