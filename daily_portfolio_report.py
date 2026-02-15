import os
import requests
import yfinance as yf
import pandas as pd
import numpy as np
import re
import time
from datetime import datetime, date

# =======================================================
# 每日定時投資組合報告 (GitHub Actions + Telegram)
# =======================================================

# --- 1. 寫死在程式碼中的投資組合資料 ---
PORTFOLIO_TW = [
    {'Ticker': '0050', 'Shares': 2548},
    {'Ticker': '0056', 'Shares': 546 + 6000},
    {'Ticker': '006208', 'Shares': 6000},
    {'Ticker': '00646', 'Shares': 2300 + 7000},
    {'Ticker': '00662', 'Shares': 823 + 1000},
    {'Ticker': '00679B', 'Shares': 4000 + 10000},
    {'Ticker': '00687B', 'Shares': 229 + 4000},
    {'Ticker': '00692', 'Shares': 2000 + 15000},
    {'Ticker': '00695B', 'Shares': 6000},
    {'Ticker': '00697B', 'Shares': 1200},
    {'Ticker': '00712', 'Shares': 4797},
    {'Ticker': '00713', 'Shares': 558 + 9000},
    {'Ticker': '00717', 'Shares': 2000},
    {'Ticker': '00719B', 'Shares': 5181},
    {'Ticker': '00720B', 'Shares': 5006},
    {'Ticker': '00725B', 'Shares': 1121},
    {'Ticker': '00751B', 'Shares': 4600},
    {'Ticker': '00757', 'Shares': 501 + 2000},
    {'Ticker': '00772B', 'Shares': 1600 + 14000},
    {'Ticker': '00830', 'Shares': 217 + 7000},
    {'Ticker': '00850', 'Shares': 3000},
    {'Ticker': '00878', 'Shares': 10400 + 31000},
    {'Ticker': '00919', 'Shares': 22227},
    {'Ticker': '00922', 'Shares': 15370},
    {'Ticker': '00923', 'Shares': 6000 + 17000},
    {'Ticker': '00937B', 'Shares': 17997},
    {'Ticker': '009800', 'Shares': 4000 + 1000},
    {'Ticker': '009811', 'Shares': 906 + 1161 + 7000},
    {'Ticker': '009812', 'Shares': 10262},
    {'Ticker': '009813', 'Shares': 18574},
    {'Ticker': '00981A', 'Shares': 1957},
    {'Ticker': '1216', 'Shares': 919 + 1000},
    {'Ticker': '2330', 'Shares': 32},
    {'Ticker': '2412', 'Shares': 19614},
    {'Ticker': '2454', 'Shares': 19},
]

PORTFOLIO_US = [
    {'Ticker': 'AOR', 'Shares': 0.19},
    {'Ticker': 'BND', 'Shares': 100.0 + 39.47 + 15.0 + 100.89},
    {'Ticker': 'BNDW', 'Shares': 37.6},
    {'Ticker': 'BNDX', 'Shares': 35.28},
    {'Ticker': 'IEF', 'Shares': 19.85},
    {'Ticker': 'META', 'Shares': 2.0},
    {'Ticker': 'MSFT', 'Shares': 4.5},
    {'Ticker': 'NVDA', 'Shares': 10.0 + 1.0},
    {'Ticker': 'QQQ', 'Shares': 11.17 + 12.8 + 2.6 + 10.78},
    {'Ticker': 'VNQ', 'Shares': 8.0 + 22.76 + 19.24},
    {'Ticker': 'VOO', 'Shares': 10.0 + 5.3},
    {'Ticker': 'VT', 'Shares': 230.48 + 86.19 + 76.78 + 75.5},
    {'Ticker': 'VTI', 'Shares': 8.65},
    {'Ticker': 'VWRA.L', 'Shares': 38.0},
    {'Ticker': 'VXUS', 'Shares': 12.0},
]

# --- 2. 輔助函式 ---

def get_yf_ticker_tw(ticker):
    ticker = str(ticker).strip()
    if re.match(r'^\d+B$', ticker):
        return f"{ticker}.TWO"
    return f"{ticker}.TW"

def classify_asset(ticker, market):
    ticker = str(ticker).strip().upper()
    if ticker in ['VT', 'VWRA.L', '009812', '009812.TW']: return '全球ETF'
    if market == 'TW':
        if ticker.endswith('B'): return '債券ETF'
        if ticker.startswith('00'):
            overseas = ['00646', '00757', '00662', '00830', '009811', '00712', '00717', '009800', '009813', '00981A']
            if ticker in overseas: return '美股ETF與個股'
            market_cap = ['0050', '006208', '00692', '00922', '00923', '00850', '00981A']
            if ticker in market_cap: return '台股市值型ETF'
            high_div = ['0056', '00878', '00919', '00713']
            if ticker in high_div: return '台股高股息型ETF'
            return '台股其他ETF'
        return '台股個股'
    elif market == 'US':
        if ticker in ['BND', 'BNDW', 'BNDX', 'IEF', 'TLT', 'SHY']: return '債券ETF'
        return '美股ETF與個股'
    return '其他'

def get_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d")
        if hist.empty: return 0, 0
        
        # --- 修正 yfinance MultiIndex 問題 ---
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        
        price = hist['Close'].iloc[-1]
        div_2026 = 0.0
        try:
            dividends = stock.dividends
            if not dividends.empty:
                divs_2026 = dividends[dividends.index.year == 2026]
                div_2026 = divs_2026.sum()
        except:
            div_2026 = 0.0
        return price, div_2026
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return 0, 0

def get_usdtwd():
    try:
        hist = yf.Ticker("TWD=X").history(period="5d")
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        return hist['Close'].iloc[-1]
    except:
        return 32.5

def send_telegram_notify(msg):
    # --- 修正變數名稱以符合 YAML 設定 ---
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ 錯誤：找不到 TELEGRAM 設定")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        print(f"❌ 發送失敗: {r.text}")

def main():
    print("🚀 開始執行投資組合計算...")
    usdtwd = get_usdtwd()
    total_market_value = 0
    total_dividends_2026 = 0
    asset_allocation = {}

    for item in PORTFOLIO_TW:
        price, div = get_data(get_yf_ticker_tw(item['Ticker']))
        value = price * item['Shares']
        total_market_value += value
        total_dividends_2026 += div * item['Shares']
        atype = classify_asset(item['Ticker'], 'TW')
        asset_allocation[atype] = asset_allocation.get(atype, 0) + value
        time.sleep(0.1)

    for item in PORTFOLIO_US:
        price, div = get_data(item['Ticker'])
        value = price * item['Shares'] * usdtwd
        total_market_value += value
        total_dividends_2026 += div * item['Shares'] * usdtwd
        atype = classify_asset(item['Ticker'], 'US')
        asset_allocation[atype] = asset_allocation.get(atype, 0) + value
        time.sleep(0.1)

    today = datetime.now().strftime('%Y-%m-%d')
    msg = f"📅 <b>{today} 投資組合報告</b>\n\n"
    msg += f"💰 <b>總市值:</b> {total_market_value:,.0f} TWD\n"
    msg += f"💵 <b>2026 累計股息:</b> {total_dividends_2026:,.0f} TWD\n\n"
    msg += "📊 <b>資產配置:</b>\n"
    
    sorted_allocation = sorted(asset_allocation.items(), key=lambda x: x[1], reverse=True)
    for asset, value in sorted_allocation:
        pct = (value / total_market_value * 100) if total_market_value > 0 else 0
        msg += f"- {asset}: {pct:.1f}%\n"

    print(msg)
    send_telegram_notify(msg)

if __name__ == "__main__":
    main()
