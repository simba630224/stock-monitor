import os
import time
import json
import gspread
import pandas as pd
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 1. 設定與環境變數
# ==========================================
# 請將這裡換成您實際的 Google Sheets 網址
PORTFOLIO_SHEET_URL = "streamlit-bot@portfolio-dashboard-498512.iam.gserviceaccount.com"
HOLDINGS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/edit?gid=0#gid=0"

# Google Sheets API 授權
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv("GCP_CREDENTIALS") # 從 GitHub Secrets 讀取

if not creds_json:
    raise ValueError("找不到 GCP_CREDENTIALS，請確認 GitHub Secrets 設定。")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ==========================================
# 2. 爬蟲核心函式
# ==========================================

def get_us_etf_holdings(ticker):
    """使用 yfinance 抓取美股 ETF Top 10 持股"""
    print(f"🔍 正在抓取美股 ETF: {ticker}")
    try:
        etf = yf.Ticker(ticker)
        # yfinance 取得基金資料
        funds_data = etf.get_funds_data()
        if funds_data and funds_data.top_holdings is not None:
            holdings = funds_data.top_holdings.head(10)
            result = []
            for symbol, row in holdings.iterrows():
                result.append({
                    "ETF代號": ticker,
                    "成分股代號": symbol,
                    "成分股名稱": row.get('Name', symbol),
                    "權重(%)": round(row.get('Holding Percent', 0) * 100, 2)
                })
            return result
    except Exception as e:
        print(f"❌ 抓取 {ticker} 失敗: {e}")
    return []

def get_tw_etf_holdings(ticker):
    """
    爬取台股 ETF Top 10 持股 (以 MoneyDJ 為例)
    注意：若網站改版可能需配合修正爬蟲邏輯
    """
    clean_ticker = str(ticker).replace('.TW', '').replace('.TWO', '')
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    # 目標網址 (MoneyDJ ETF 持股頁面)
    url = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    result = []
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 尋找持股表格 (通常帶有 class 't01')
        table = soup.find('table', {'class': 't01'})
        if not table:
            return result
            
        rows = table.find_all('tr')[1:] # 略過標題列
        
        for row in rows[:10]: # 只取前 10 大
            cols = row.find_all('td')
            if len(cols) >= 3:
                name = cols[0].text.strip()
                weight_str = cols[2].text.strip().replace('%', '')
                try:
                    weight = float(weight_str)
                    result.append({
                        "ETF代號": clean_ticker,
                        "成分股代號": "-", # 若需精確代號需進一步解析
                        "成分股名稱": name,
                        "權重(%)": weight
                    })
                except:
                    pass
    except Exception as e:
        print(f"❌ 抓取 {clean_ticker} 失敗: {e}")
    
    time.sleep(2) # 避免請求過快被擋
    return result

# ==========================================
# 3. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業...")
    
    # 1. 讀取現有投資組合
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    # 2. 處理台股 ETF (過濾出 00 開頭的 ETF)
    for row in tw_records:
        ticker = str(row.get('Ticker', ''))
        if ticker.startswith('00'): 
            holdings = get_tw_etf_holdings(ticker)
            all_holdings.extend(holdings)

    # 3. 處理美股 ETF (過濾掉個股，您可以自行定義美股 ETF 清單)
    us_etf_list = ['VOO', 'QQQ', 'VT', 'BND', 'BNDW', 'BNDX', 'IEF', 'VNQ', 'VXUS']
    for row in us_records:
        ticker = str(row.get('Ticker', '')).upper()
        if ticker in us_etf_list:
            holdings = get_us_etf_holdings(ticker)
            all_holdings.extend(holdings)

    if not all_holdings:
        print("⚠️ 未抓取到任何持股資料。")
        return

    # 4. 轉換為 DataFrame 並寫入新的 Google Sheet
    df_holdings = pd.DataFrame(all_holdings)
    
    try:
        db_sheet = client.open_by_url(HOLDINGS_SHEET_URL)
        
        # 檢查工作表是否存在，不存在則建立
        try:
            ws = db_sheet.worksheet("Top10_Holdings")
        except gspread.exceptions.WorksheetNotFound:
            ws = db_sheet.add_worksheet(title="Top10_Holdings", rows="1000", cols="10")
            
        # 清空舊資料並寫入新資料
        ws.clear()
        ws.update([df_holdings.columns.values.tolist()] + df_holdings.values.tolist())
        print("✅ 成功將所有 ETF 持股寫入 Google Sheets！")
        
    except Exception as e:
        print(f"❌ 寫入 ETF_Holdings_DB 失敗: {e}")

if __name__ == "__main__":
    main()
