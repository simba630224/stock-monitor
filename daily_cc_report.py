import os
import requests
import json
from datetime import datetime, timedelta, timezone

# --- 1. 環境變數 ---
# 這裡建議維持讀取環境變數，但您可以暫時在括號內填入字串測試：
# api_key = "您的金鑰" (僅供手動測試，不要推送到 GitHub)
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

def get_daily_strategy():
    if not api_key:
        return "❌ 錯誤：找不到 API Key，請檢查 GitHub Secrets 設定。"

    tz_taipei = timezone(timedelta(hours=8))
    today = datetime.now(tz_taipei).strftime("%Y-%m-%d (%A)")
    
    # 嘗試使用最穩定的 v1 版本路徑
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    prompt_text = f"今天是 {today}。請分析 2026 年信用卡(永豐幣倍、中信uniopen、國泰CUBE、富邦Costco、富邦Momo、富邦J卡、台新Richart)在桃園中壢的最優策略。特別比較星巴克與統一集團通路。格式用 HTML <b> 與 <i>。"

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        res_json = response.json()
        
        # 檢查是否有 candidates 欄位
        if 'candidates' in res_json:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        elif 'error' in res_json:
            # 如果 API 報錯，直接回傳錯誤原因
            return f"❌ API 報錯：{res_json['error'].get('message', '未知錯誤')}"
        else:
            return f"❌ API 回傳異常格式：{json.dumps(res_json)}"
            
    except Exception as e:
        return f"執行異常: {str(e)}"

def send_telegram_notify(msg):
    if not (telegram_token and telegram_chat_id): return
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    requests.post(url, data={"chat_id": telegram_chat_id, "text": msg, "parse_mode": "HTML"})

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
