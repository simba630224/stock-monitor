import os
import requests
import yfinance as yf
import pandas as pd
import numpy as np
import re
import time
import io
import matplotlib
# 設定 matplotlib 為背景繪圖模式，避免 GitHub Actions 報錯
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# =======================================================
# 每日定時投資組合報告 + 匯率分析走勢圖 (GitHub Actions + Telegram)
# =======================================================

# --- 1. 寫死在程式碼中的投資組合資料 ---

PORTFOLIO_TW = [
    {'Ticker': '0050', 'Shares': 4000},
    {'Ticker': '0056', 'Shares': 8000},
    {'Ticker': '006208', 'Shares': 6000},
    {'Ticker': '00646', 'Shares': 100 + 11000},
    {'Ticker': '00662', 'Shares': 379 + 2000},
    {'Ticker': '00679B', 'Shares': 10000},
    {'Ticker': '00687B', 'Shares': 4438},
    {'Ticker': '00692', 'Shares': 2000 + 15000},
    {'Ticker': '00697B', 'Shares': 2262},
    {'Ticker': '00712', 'Shares': 2918 + 7000},
    {'Ticker': '00713', 'Shares': 1200 + 13000},
    {'Ticker': '00717', 'Shares': 2000},
    {'Ticker': '00719B', 'Shares': 7000},
    {'Ticker': '00751B', 'Shares': 1000},
    {'Ticker': '00757', 'Shares': 324 + 3000},
    {'Ticker': '00772B', 'Shares': 100 + 18000},
    {'Ticker': '00830', 'Shares': 695 + 7000},
    {'Ticker': '00878', 'Shares': 3000 + 46000},
    {'Ticker': '00919', 'Shares': 3116+29000},
    {'Ticker': '00922', 'Shares': 20600+0},
    {'Ticker': '00923', 'Shares': 22000+5000},
    {'Ticker': '00937B', 'Shares': 3665 + 19000},
    {'Ticker': '009800', 'Shares': 13000 + 1000},
    {'Ticker': '009811', 'Shares': 2427},
    {'Ticker': '009812', 'Shares': 4023 + 18000},
    {'Ticker': '009813', 'Shares': 29446 + 11000},
    {'Ticker': '009815', 'Shares': 6000+9000},
    {'Ticker': '00981A', 'Shares': 4000+2000},
    {'Ticker': '00988A', 'Shares': 417 + 9000},
    {'Ticker': '1216', 'Shares':2000},
    {'Ticker': '2317', 'Shares': 154},
    {'Ticker': '2330', 'Shares': 38},
    {'Ticker': '2412', 'Shares': 12000},
    {'Ticker': '2454', 'Shares': 1},
]

PORTFOLIO_US = [
    {'Ticker': 'AOR', 'Shares': 0.19},
    {'Ticker': 'BND', 'Shares': 51.47},
    {'Ticker': 'BNDW', 'Shares': 37.6},
    {'Ticker': 'META', 'Shares': 2.0},
    {'Ticker': 'NVDA', 'Shares': 1.0},
    {'Ticker': 'QQQ', 'Shares': 12.8 + 2.6 + 15.79},
    {'Ticker': 'VNQ', 'Shares': 8.0 + 27.62 + 19.39},
    {'Ticker': 'VOO', 'Shares': 10.0 + 5.31},
    {'Ticker': 'VT', 'Shares': 202.49 + 86.19 + 76.78 + 95.63},
    {'Ticker': 'VWRA.L', 'Shares': 170.0},
    {'Ticker': 'CSPX.L', 'Shares': 9.0},
    {'Ticker': 'VXUS', 'Shares': 24.0},
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
        # 【修正點】：將抓取區間從 5d 放寬到 1y，確保能讀取到今年完整的除息紀錄
        hist = stock.history(period="1y")
        
        # 【防呆機制】：過濾掉 nan 的數據，抓取最新的一筆有效收盤價
        price = 0.0
        if not hist.empty:
            valid_closes = hist['Close'].dropna()
            if not valid_closes.empty:
                price = float(valid_closes.iloc[-1])
        
        # 【修正點】：直接從 1y 的歷史紀錄表裡面抓取 Dividends 欄位，避開 yfinance 快取 Bug
        div_2026 = 0.0
        if not hist.empty and 'Dividends' in hist.columns:
            divs = hist['Dividends']
            # 篩選出 2026 年的配息紀錄
            divs_2026 = divs[divs.index.year == 2026]
            div_sum = divs_2026.sum()
            if not pd.isna(div_sum): 
                div_2026 = float(div_sum)
                
        return price, div_2026
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return 0.0, 0.0

def get_usdtwd():
    try:
        hist = yf.Ticker("TWD=X").history(period="5d")
        # 【防呆機制】：過濾匯率的空值
        if not hist.empty:
            valid_closes = hist['Close'].dropna()
            if not valid_closes.empty:
                return float(valid_closes.iloc[-1])
        return 32.5
    except: 
        return 32.5

# --- 3. Telegram 傳送函式 ---

def send_telegram_notify(msg):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}
    requests.post(url, data=payload)

def send_telegram_photo(caption, photo_buffer):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    photo_buffer.seek(0)
    files = {'photo': ('fx_chart.png', photo_buffer, 'image/png')}
    payload = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    requests.post(url, data=payload, files=files)

# --- 4. 匯率分析與繪圖功能 ---

def analyze_and_plot_fx(fx_ticker="TWD=X"):
    print("📈 開始繪製匯率走勢圖...")
    try:
        data = yf.Ticker(fx_ticker).history(period="1y")
        if data.empty: return None, "無法取得匯率資料"
        
        # 避免畫圖時遇到 nan 導致錯誤
        data = data.dropna(subset=['Close'])
        
        data['MA20'] = data['Close'].rolling(window=20).mean()
        data['MA60'] = data['Close'].rolling(window=60).mean()
        
        curr_price = data['Close'].iloc[-1]
        ma20_val = data['MA20'].iloc[-1] if not pd.isna(data['MA20'].iloc[-1]) else curr_price
        ma60_val = data['MA60'].iloc[-1] if not pd.isna(data['MA60'].iloc[-1]) else curr_price
        
        plt.figure(figsize=(10, 5))
        plt.plot(data.index, data['Close'], label='USD/TWD', color='black', linewidth=1.5)
        plt.plot(data.index, data['MA20'], label='MA20 (月線)', color='blue', linestyle='--')
        plt.plot(data.index, data['MA60'], label='MA60 (季線)', color='red', linestyle='-.')
        
        plt.title('USD/TWD Exchange Rate (1 Year)', fontsize=14)
        plt.grid(True, linestyle=':', alpha=0.6)
        plt.legend(loc='upper left')
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        plt.close()
        
        status = []
        if curr_price > ma20_val: status.append("站上月線")
        else: status.append("跌破月線")
        if curr_price > ma60_val: status.append("站上季線")
        else: status.append("跌破季線")
            
        msg = f"💱 <b>USD/TWD 匯率分析</b>\n"
        msg += f"現價: <b>{curr_price:.3f}</b>\n"
        msg += f"MA20: {ma20_val:.3f}\n"
        msg += f"MA60: {ma60_val:.3f}\n"
        msg += f"⚠️ 狀態: {' / '.join(status)}"
        
        return buf, msg
    except Exception as e:
        print(f"匯率繪圖失敗: {e}")
        return None, f"匯率分析失敗: {e}"

# --- 5. 主程式邏輯 ---

def main():
    print("🚀 開始執行投資組合計算...")
    usdtwd = get_usdtwd()
    print(f"💵 取得目前匯率: {usdtwd}")
    
    total_market_value = 0
    total_dividends_2026 = 0
    asset_allocation = {}

    # 處理台股
    for item in PORTFOLIO_TW:
        ticker_raw = item['Ticker']
        shares = item['Shares']
        yf_ticker = get_yf_ticker_tw(ticker_raw)
        asset_type = classify_asset(ticker_raw, 'TW')
        
        price, div = get_data(yf_ticker)
        value = price * shares
        div_total = div * shares
        
        # 避免任何突發的 nan 污染加總
        if pd.notna(value): 
            total_market_value += value
            asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + value
        if pd.notna(div_total): 
            total_dividends_2026 += div_total
            
        time.sleep(0.3)

    # 處理美股
    for item in PORTFOLIO_US:
        ticker = item['Ticker']
        shares = item['Shares']
        asset_type = classify_asset(ticker, 'US')
        
        price, div = get_data(ticker)
        value = price * shares * usdtwd
        div_total = div * shares * usdtwd
        
        if pd.notna(value):
            total_market_value += value
            asset_allocation[asset_type] = asset_allocation.get(asset_type, 0) + value
        if pd.notna(div_total):
            total_dividends_2026 += div_total
            
        time.sleep(0.3)

    # 1. 傳送投資組合報告 (文字)
    today = datetime.now().strftime('%Y-%m-%d')
    msg_portfolio = f"📅 <b>{today} 投資組合報告</b>\n\n"
    msg_portfolio += f"💰 <b>總市值:</b> {total_market_value:,.0f} TWD\n"
    msg_portfolio += f"💵 <b>2026 累計股息:</b> {total_dividends_2026:,.0f} TWD\n\n"
    msg_portfolio += "📊 <b>資產配置:</b>\n"
    
    sorted_allocation = sorted(asset_allocation.items(), key=lambda x: x[1], reverse=True)
    for asset, value in sorted_allocation:
        pct = (value / total_market_value) * 100 if total_market_value > 0 else 0
        msg_portfolio += f"- {asset}: {pct:.1f}%\n"

    print("發送投資組合報告...")
    send_telegram_notify(msg_portfolio)

    # 2. 傳送匯率分析報告 (圖片 + 文字)
    buf, msg_fx = analyze_and_plot_fx("TWD=X")
    if buf:
        print("發送匯率圖表...")
        send_telegram_photo(msg_fx, buf)
    else:
        send_telegram_notify(msg_fx)

if __name__ == "__main__":
    main()
