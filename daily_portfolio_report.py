def send_telegram_notify(msg):
    """傳送 Telegram 訊息"""
    # 這裡同時檢查 TELEGRAM_BOT_TOKEN 與 TELEGRAM_TOKEN，解決名稱不一致問題
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ 錯誤：找不到 TELEGRAM 設定 (請檢查 GitHub Secrets 是否正確)")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML"
    }
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        print(f"❌ Telegram 發送失敗: {r.text}")
