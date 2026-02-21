import os
import requests
import json
from datetime import datetime

# --- 1. 環境變數檢查與 Log ---
api_key = os.environ.get("GOOGLE_API_KEY")
telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

print(f"--- 系統檢查 ---")
print(f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"GOOGLE_API_KEY 是否存在: {'Yes' if api_key else 'No'}")
print(f"TELEGRAM_BOT_TOKEN 是否存在: {'Yes' if telegram_token else 'No'}")
print(f"TELEGRAM_CHAT_ID 是否存在: {'Yes' if telegram_chat_id else 'No'}")

# --- 2. 獲取 Gemini 策略分析 ---
def get_daily_strategy():
    if not api_key:
        return "ERROR: 缺少 API Key"

    # A. 偵測可用模型
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    print(f"\n--- 步驟 1: 偵測可用模型 ---")
    try:
        m_resp = requests.get(list_url)
        print(f"模型列表請求狀態: {m_resp.status_code}")
        m_data = m_resp.json()
        models = [m['name'] for m in m_data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        print(f"可用模型數量: {len(models)}")
        
        target_model = None
        for m_id in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]:
            if m_id in models:
                target_model = m_id
                break
        if not target_model:
            target_model = models[0] if models else "models/gemini-1.5-flash"
        print(f"最終選定模型: {target_model}")
    except Exception as e:
        print(f"偵測模型發生異常: {str(e)}")
        target_model = "models/gemini-1.5-flash"

    # B. 請求內容生成
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    print(f"\n--- 步驟 2: 向 Gemini 請求攻略 ({today}) ---")
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    
    prompt_text = f"""
    今天是 {today}。請針對以下 7 張信用卡，提供全台今日最優刷卡策略：
    永豐幣倍卡、中信uniopen、國泰CUBE JCB卡、富邦Costco、富邦Momo、富邦JCB/J卡、台新Richart 卡。
    
    分析重點：
    1. 量販超市：全聯(週末1300送650點)、家樂福(週末2000享9折)。
    2. 百貨：中壢大江(賀歲慶現抵活動)。
    3. 餐飲交通：星巴克、中油加油。
    
    請註明：最優支付方式與 CUBE/Richart 的方案切換建議。
    格式要求：使用 HTML 標籤(<b>, <i>, <u>)，結構清晰美觀。
    """

    payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        print(f"Gemini 請求狀態碼: {response.status_code}")
        if response.status_code != 200:
            print(f"Gemini 錯誤內容: {response.text}")
            return f"Gemini 呼叫失敗，代碼 {response.status_code}"
            
        data = response.json()
        result = data['candidates'][0]['content']['parts'][0]['text']
        print(f"Gemini 成功生成內容 (長度: {len(result)})")
        return result
    except Exception as e:
        print(f"Gemini 請求異常: {str(e)}")
        return f"Gemini 執行異常: {str(e)}"

# --- 3. Telegram 傳送函式 (含回饋 Log) ---
def send_telegram_notify(msg):
    print(f"\n--- 步驟 3: 傳送 Telegram 訊息 ---")
    if not telegram_token or not telegram_chat_id:
        print("跳過傳送: 缺少 Token 或 Chat ID")
        return

    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id": telegram_chat_id, 
        "text": msg, 
        "parse_mode": "HTML"
    }
    
    try:
        r = requests.post(url, data=payload)
        print(f"Telegram 請求狀態碼: {r.status_code}")
        if r.status_code != 200:
            print(f"Telegram 錯誤訊息: {r.text}")
            # 如果是 HTML 語法錯誤，嘗試發送純文字版本作為保險
            if "can't parse entities" in r.text:
                print("HTML 解析錯誤，嘗試以純文字重新傳送...")
                payload["parse_mode"] = ""
                requests.post(url, data=payload)
        else:
            print("Telegram 訊息已成功送出！")
    except Exception as e:
        print(f"Telegram 網路請求異常: {str(e)}")

if __name__ == "__main__":
    report = get_daily_strategy()
    send_telegram_notify(report)
    print(f"\n--- 腳本執行結束 ---")
