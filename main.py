import os
import sys

# --- 深度偵錯：列出所有環境變數 ---
print("=== Python 讀取檢查 ===")
# 取得系統中所有包含 'TELE' 的變數名稱 (不含內容)
found_keys = [k for k in os.environ.keys() if 'TELE' in k]
print(f"系統中偵測到的 Telegram 相關變數名稱: {found_keys}")

# 嘗試抓取各種可能的拼寫 (相容舊版與新版)
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if TG_TOKEN:
    print(f"✅ TOKEN 讀取成功 (長度: {len(TG_TOKEN)})")
else:
    print("❌ TOKEN 讀取失敗")

if TG_CHAT_ID:
    print(f"✅ CHAT_ID 讀取成功: {TG_CHAT_ID}")
else:
    print("❌ CHAT_ID 讀取失敗")
# ----------------------------

# 接下來接原本的分析邏輯...
