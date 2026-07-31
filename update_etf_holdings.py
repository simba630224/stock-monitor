import os
import time
import json
import math
import gspread
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 1. 設定與環境變數
# ==========================================
# 請將這裡換成您實際的 Google Sheets 網址
PORTFOLIO_SHEET_URL = "https://docs.google.com/spreadsheets/d/16EgWvmGUPfOrDKGiefWCovNQNYf-E4RAVDGu7zx1BI4/edit?gid=0#gid=0"
HOLDINGS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/edit?gid=1970038349#gid=1970038349"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv("GCP_CREDENTIALS") 

if not creds_json:
    raise ValueError("找不到 GCP_CREDENTIALS，請確認 GitHub Secrets 設定。")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ==========================================
# 2. 爬蟲核心函式
# ==========================================

def get_us_etf_holdings(ticker):
    """使用 yfinance 抓取美股 ETF 持股"""
    print(f"🔍 正在抓取美股 ETF: {ticker}")
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        if funds_data and funds_data.top_holdings is not None:
            # 盡量抓 20 筆，但 yfinance 很多 ETF 上限只有 10 筆
            holdings = funds_data.top_holdings.head(20)
            result = []
            for symbol, row in holdings.iterrows():
                weight = row.get('Holding Percent', 0)
                # 避開 NaN 無效數值
                if pd.isna(weight): weight = 0 
                
                result.append({
                    "ETF代號": ticker,
                    "成分股代號": symbol,
                    "成分股名稱": row.get('Name', symbol),
                    "權重(%)": round(weight * 100, 2)
                })
            print(f"✅ 成功抓取美股 ETF: {ticker}，共 {len(result)} 檔成分股")
            return result
    except Exception as e:
        print(f"❌ 抓取 {ticker} 失敗: {e}")
    return []

def get_tw_etf_holdings(ticker):
    """
    台股 ETF 爬蟲 (雙引擎比對，自動取資料較多的一方)
    """
    clean_ticker = str(ticker).replace('.TW', '').replace('.TWO', '')
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    result_mdj = []
    result_yahoo = []

    # --- 引擎 1: 嘗試 MoneyDJ ---
    try:
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res = requests.get(url_mdj, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        tables = soup.find_all('table')
        for tbl in tables:
            if '權重' in tbl.text or '比例' in tbl.text or '持股' in tbl.text:
                for row in tbl.find_all('tr'):
                    cols = [c.text.strip() for c in row.find_all(['td', 'th'])]
                    if len(cols) >= 3:
                        name = cols[0]
                        weight_str = cols[-1].replace('%', '').strip()
                        try:
                            weight = float(weight_str)
                            if weight > 0 and name not in ['股票名稱', '名稱', '基金名稱']:
                                result_mdj.append({
                                    "ETF代號": clean_ticker,
                                    "成分股名稱": name,
                                    "權重(%)": weight
                                })
                        except ValueError:
                            continue
                break 
    except Exception as e:
        pass

    # --- 引擎 2: 嘗試 Yahoo 股市 ---
    try:
        url_yahoo = f"https://tw.stock.yahoo.com/quote/{clean_ticker}.TW/holding"
        res = requests.get(url_yahoo, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        list_items = soup.find_all('li', class_=lambda x: x and 'List(n)' in x)
        for item in list_items:
            text_blocks = item.find_all('div')
            if len(text_blocks) >= 2:
                name = text_blocks[0].text.strip()
                weight_block = item.find(string=lambda t: t and '%' in t)
                if weight_block:
                    weight_str = weight_block.replace('%', '').strip()
                    try:
                        weight = float(weight_str)
                        if weight > 0 and len(name) > 0 and name != '持股名稱':
                            result_yahoo.append({
                                "ETF代號": clean_ticker,
                                "成分股名稱": name.split(' ')[0], 
                                "權重(%)": weight
                            })
                    except ValueError:
                        pass
    except Exception as e:
        pass

    # --- 整理與比對 ---
    # 選擇抓到比較多資料的引擎 (對於債券 ETF，Yahoo 通常能抓到真正的成分，而 MoneyDJ 只顯示大分類)
    best_result = result_mdj if len(result_mdj) >= len(result_yahoo) else result_yahoo
    source = "MoneyDJ" if best_result == result_mdj else "Yahoo"
    
    if len(best_result) > 0:
        unique_result = {v['成分股名稱']:v for v in best_result}.values() # 去重複
        best_result = sorted(list(unique_result), key=lambda x: x['權重(%)'], reverse=True)[:20]
        print(f"✅ [採用來源: {source}] 成功抓取 {clean_ticker}，共 {len(best_result)} 檔成分股")
    else:
        print(f"⚠️ {clean_ticker} 無法取得持股資料。")
        
    time.sleep(1) # 禮貌性延遲
    return best_result

# ==========================================
# 3. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (Top 20)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    for row in tw_records:
        ticker = str(row.get('Ticker', ''))
        if ticker.startswith('00'): 
            holdings = get_tw_etf_holdings(ticker)
            all_holdings.extend(holdings)

    us_etf_list = ['VOO', 'QQQ', 'VT', 'BND', 'BNDW', 'BNDX', 'IEF', 'VNQ', 'VXUS']
    for row in us_records:
        ticker = str(row.get('Ticker', '')).upper()
        if ticker in us_etf_list:
            holdings = get_us_etf_holdings(ticker)
            all_holdings.extend(holdings)

    if not all_holdings:
        print("⚠️ 未抓取到任何持股資料。")
        return

    # 4. 轉換為 DataFrame 並進行關鍵的「無效數據清洗」
    df_holdings = pd.DataFrame(all_holdings)
    
    # 【修復 JSON 報錯關鍵】
    # 1. 將所有的 NaN (空值) 替換為 0 或空字串
    df_holdings.replace([np.inf, -np.inf], np.nan, inplace=True)
    df_holdings = df_holdings.fillna(0)
    
    try:
        db_sheet = client.open_by_url(HOLDINGS_SHEET_URL)
        
        try:
            ws = db_sheet.worksheet("Top20_Holdings")
        except gspread.exceptions.WorksheetNotFound:
            ws = db_sheet.add_worksheet(title="Top20_Holdings", rows="2000", cols="10")
            
        ws.clear()
        ws.update([df_holdings.columns.values.tolist()] + df_holdings.values.tolist())
        print("✅ 成功將所有 ETF 持股寫入 Google Sheets！")
        
    except Exception as e:
        print(f"❌ 寫入 ETF_Holdings_DB 失敗: {e}")

if __name__ == "__main__":
    main()
