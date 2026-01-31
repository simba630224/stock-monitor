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

# --- 1. 寫死在程式碼中的投資組合資料 (來自 portfolio.csv 與 portfolio_us.csv) ---
# 台股資料 (TW)
PORTFOLIO_TW = [
    {'Ticker': '006208', 'Shares': 1100 + 5000}, # 合併集保與富邦借
    {'Ticker': '00692', 'Shares': 3974 + 15000}, # 合併集保與富邦借
    {'Ticker': '00850', 'Shares': 7300},
    {'Ticker': '00923', 'Shares': 4000 + 17000},
    {'Ticker': '0056', 'Shares': 546 + 6000},
    {'Ticker': '00878', 'Shares': 9271 + 31000},
    {'Ticker': '00919', 'Shares': 20418},
    {'Ticker': '00713', 'Shares': 1125 + 8000},
    {'Ticker': '00772B', 'Shares': 933 + 14000},
    {'Ticker': '00751B', 'Shares': 10600},
    {'Ticker': '00720B', 'Shares': 6006},
    {'Ticker': '00937B', 'Shares': 14801},
    {'Ticker': '00687B', 'Shares': 5123},
    {'Ticker': '00679B', 'Shares': 6000},
    {'Ticker': '00712', 'Shares': 797 + 797},
    {'Ticker': '00830', 'Shares': 163 + 7000},
    {'Ticker': '00646', 'Shares': 844 + 7000},
    {'Ticker': '00757', 'Shares': 2475},
    {'Ticker': '00662', 'Shares': 766 + 1000},
    {'Ticker': '00922', 'Shares': 11266 + 3000},
    {'Ticker': '00719B', 'Shares': 1084 + 4000},
    {'Ticker': '00717', 'Shares': 2000},
    {'Ticker': '1216', 'Shares': 1919},
    {'Ticker': '00725B', 'Shares': 1121},
    {'Ticker': '0050', 'Shares': 2507},
    {'Ticker': '2412', 'Shares': 19614},
    {'Ticker': '009811', 'Shares': 906 + 906 + 7000}, # 合併多筆
    {'Ticker': '2454', 'Shares': 19},
    {'Ticker': '2330', 'Shares': 32},
    {'Ticker': '00981A', 'Shares': 1794},
    {'Ticker': '009812', 'Shares': 6262},
    {'Ticker': '009813', 'Shares': 7574},
    {'Ticker': '009800', 'Shares': 4000 + 1000},
    {'Ticker': '00697B', 'Shares': 600},
    {'Ticker': '00695B', 'Shares': 6000},
]

# 美股資料 (US)
PORTFOLIO_US = [
    {'Ticker': 'AOR', 'Shares': 0.19},
    {'Ticker': 'BND', 'Shares': 100 + 39.47 + 15 + 100.66},
    {'Ticker': 'BNDW', 'Shares': 37.6},
    {'Ticker': 'IEF', 'Shares': 19.8},
    {'Ticker': 'VT', 'Shares': 228.4 + 86.19 + 76.7 + 75.5},
    {'Ticker': 'VTI', 'Shares': 8.65},
    {'Ticker': 'QQQ', 'Shares': 11.17 + 12.8 + 2.6 + 10.78},
    {'Ticker': 'BNDX', 'Shares': 35.28},
    {'Ticker': 'NVDA', 'Shares': 10 + 1},
    {'Ticker': 'VNQ', 'Shares': 8 + 21.1 + 19.24},
    {'Ticker': 'VOO', 'Shares': 10 + 5.3},
    {'Ticker': 'VXUS', 'Shares': 12},
    {'Ticker': 'META', 'Shares': 2},
    {'Ticker': 'MSFT', 'Shares': 4.5},
    {'Ticker': 'IXN', 'Shares': 5.63},
    {'Ticker': 'VWRA.L', 'Shares': 20},
]

# --- 2. 輔助函式 ---

def get_yf_ticker_tw(ticker):
    """轉換台股代號為 Yahoo Finance 格式"""
    ticker = str(ticker).strip()
    # 債券 ETF 通常為上櫃 (.TWO)，一般判斷規則：
    # 4碼數字 -> .TW
    # 5碼/6碼且結尾B -> .TWO (大部分債券ETF)
    # 00開頭 ETF -> 大多 .TW, 但少數債券型為 .TWO
    # 這裡使用簡單規則：若結尾是B則.TWO，否則.TW (符合大多數情況)
    if re.match(r'^\d+B$', ticker):
        return f"{ticker}.TWO"
    return f"{ticker}.TW"

def classify_asset(ticker, market):
    """資產分類邏輯 (整合 v11 規則)"""
    ticker = str(ticker).strip().upper()
    
    # 全球 ETF
    if ticker in ['VT', 'VWRA.L', '009812', '009812.TW']: return '全球ETF'
    
    if market == 'TW':
        if ticker.endswith('B'): return '債券ETF'
        # 台股 ETF 判斷
        if ticker.startswith('00'):
            overseas = ['00646', '00757', '00662', '00830', '009811', '00712', '00717', '009800', '009813', '00981A']
            if ticker in overseas: return '美股ETF與個股' # 或海外
            
            market_cap = ['0050', '006208', '00692', '00922', '00923', '00850', '00981A']
            if ticker in market_cap: return '台股市值型ETF'
            
            high_div = ['0056', '00878', '00919', '00713']
            if ticker in high_div: return '台股高股息型ETF'
            
            return '台股其他ETF'
        # 台股個股
        return '台股個股'
    
    elif market == 'US':
        if ticker in ['BND', 'BNDW', 'BNDX', 'IEF', 'TLT', 'SHY']: return '債券ETF'
        return '美股ETF與個股'
    
    return '其他'

def get_data(ticker):
    """取得最新股價與 2026 股息"""
    try:
        stock = yf.Ticker(ticker)
        # 取得最新股價 (使用 history 較穩定)
        hist = stock.history(period="5d")
        if hist.empty:
            price = 0
        else:
            price = hist['Close'].iloc[-1]
            
        # 取得 2026 股息
        div_2026 = 0.0
        try:
            dividends = stock.dividends
            if not dividends.empty:
                # 篩選 2026 年的股息
                current_year = 2026 # 根據需求指定 2026
                # 注意時區問題，先轉為無時區或統一時區
                divs_2026 = dividends[dividends.index.year == current_year]
                div_2026 = divs_2026.sum()
        except:
            div_2026 = 0.0
            
        return price, div_2026
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return 0, 0

def get_usdtwd():
    """取得美金匯率"""
    try:
        hist = yf.Ticker("TWD=X").history(period="5d")
        return hist['Close'].iloc[-1]
    except:
        return 32.5 # 預設值

def send_telegram_notify(msg):
    """傳送 Telegram 訊息"""
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("❌ 錯誤：找不到 TELEGRAM 設定")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML"
    }
    requests.post(url, data=payload)

# --- 3. 主程式邏輯 ---

def main():
    print("🚀 開始執行投資組合計算...")
    
    # 取得匯率
    usdtwd = get_usdtwd()
    print(f"匯率: {usdtwd:.2f}")

    total_market_value = 0
    total_dividends_2026 = 0
    asset_allocation = {} # {Asset_Type: Value}

    # 處理台股
    for item in PORTFOLIO_TW:
        ticker_raw = item['Ticker']
        shares = item['Shares']
        yf_ticker = get_yf_ticker_tw(ticker_raw)
        asset_type = classify_asset(ticker_raw, 'TW')
        
        price, div = get_data(yf_ticker)
        
        value = price * shares
        div_total = div * shares
        
        total_market_value += value
        total_dividends_2026 += div_total
        asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + value
        
        time.sleep(0.5) # 避免過快

    # 處理美股
    for item in PORTFOLIO_US:
        ticker = item['Ticker']
        shares = item['Shares']
        asset_type = classify_asset(ticker, 'US')
        
        price, div = get_data(ticker)
        
        # 美股計價需換算台幣
        value = price * shares * usdtwd
        div_total = div * shares * usdtwd
        
        total_market_value += value
        total_dividends_2026 += div_total
        asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + value

        time.sleep(0.5)

    # 整理報告內容
    today = datetime.now().strftime('%Y-%m-%d')
    
    msg = f"📅 <b>{today} 投資組合報告</b>\n\n"
    msg += f"💰 <b>總市值:</b> {total_market_value:,.0f} TWD\n"
    msg += f"💵 <b>2026 累計股息:</b> {total_dividends_2026:,.0f} TWD\n\n"
    
    msg += "📊 <b>資產配置:</b>\n"
    
    # 計算比例並排序
    sorted_allocation = sorted(asset_allocation.items(), key=lambda x: x[1], reverse=True)
    
    for asset, value in sorted_allocation:
        if total_market_value > 0:
            pct = (value / total_market_value) * 100
        else:
            pct = 0
        msg += f"- {asset}: {pct:.1f}%\n"

    print(msg)
    send_telegram_notify(msg)

if __name__ == "__main__":
    main()
