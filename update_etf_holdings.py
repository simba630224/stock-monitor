import os
import time
import json
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
PORTFOLIO_SHEET_URL = "https://docs.google.com/spreadsheets/d/16EgWvmGUPfOrDKGiefWCovNQNYf-E4RAVDGu7zx1BI4/edit?gid=818275503#gid=818275503"
HOLDINGS_SHEET_URL = "https://docs.google.com/spreadsheets/d/1_crBmjMxgm9qpYeycg_TnLStt3phN6vM4XILmD9x0Yc/edit?gid=1748501668#gid=1748501668"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv("GCP_CREDENTIALS") 

if not creds_json:
    raise ValueError("找不到 GCP_CREDENTIALS，請確認 GitHub Secrets 設定。")

creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ==========================================
# 2. 爬蟲核心函式與小工具
# ==========================================

def pad_tw_ticker(ticker):
    """
    【修復 Google Sheets 吞掉 0 的陷阱】
    將 '50' 轉回 '0050'，'981A' 轉回 '00981A'
    """
    t = str(ticker).strip().upper().replace('.TW', '').replace('.TWO', '')
    if t.isdigit():
        if len(t) == 2: return "00" + t  # 例如: 50 -> 0050
        if len(t) == 3: return "00" + t  # 例如: 878 -> 00878
    else:
        # 含英文字母的特規 ETF (如 981A, 988A)
        if len(t) == 4 and t[0] in '123456789': return "00" + t 
    return t

def get_us_etf_holdings(ticker):
    print(f"🔍 正在檢查海外標的: {ticker}")
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        
        if funds_data and funds_data.top_holdings is not None and not funds_data.top_holdings.empty:
            holdings = funds_data.top_holdings.head(20)
            result = []
            for symbol, row in holdings.iterrows():
                weight = row.get('Holding Percent', 0)
                if pd.isna(weight): weight = 0 
                
                result.append({
                    "ETF代號": ticker,
                    "成分股代號": symbol,
                    "成分股名稱": row.get('Name', symbol),
                    "權重(%)": round(weight * 100, 2)
                })
            print(f"✅ 成功抓取海外 ETF: {ticker}，共 {len(result)} 檔成分股")
            return result
        else:
            print(f"⚠️ {ticker} 系統無提供成分股明細 (可能為非美系 UCITS 基金或無資料)。")
            return []
    except Exception as e:
        pass
    return []

def get_tw_etf_holdings(raw_ticker):
    """
    台股 ETF 爬蟲 (動態表頭定位版 - 解決抓不到名稱的問題)
    """
    clean_ticker = pad_tw_ticker(raw_ticker)
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    result = []

    # --- 引擎 1：MoneyDJ (動態欄位對齊法) ---
    try:
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res = requests.get(url_mdj, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        tables = soup.find_all('table')
        for tbl in tables:
            header_row = tbl.find('tr')
            if not header_row: continue
            
            # 1. 抓出這張表所有的標題名稱
            th_cells = header_row.find_all(['th', 'td'])
            h_text = [c.text.strip().replace(' ', '').replace('\n', '') for c in th_cells]
            
            # 2. 動態尋找「名稱」、「代號」、「權重」到底在第幾個欄位
            name_idx, weight_idx, ticker_idx = -1, -1, -1
            
            for i, h in enumerate(h_text):
                if '名稱' in h or '股票' in h or '標的' in h:
                    if name_idx == -1: name_idx = i
                if '權重' in h or '比例' in h or '持股' in h:
                    if weight_idx == -1: weight_idx = i
                if '代號' in h or '代碼' in h:
                    if ticker_idx == -1: ticker_idx = i
                    
            # 3. 只要確認表裡有「名稱」與「權重」，就開始抓資料！
            if name_idx != -1 and weight_idx != -1:
                data_rows = tbl.find_all('tr')[1:]
                for row in data_rows:
                    cols = row.find_all(['td', 'th'])
                    
                    if len(cols) > max(name_idx, weight_idx):
                        name = cols[name_idx].text.strip()
                        weight_str = cols[weight_idx].text.replace('%', '').replace(',', '').strip()
                        
                        t_code = "-"
                        if ticker_idx != -1 and len(cols) > ticker_idx:
                            t_code = cols[ticker_idx].text.strip()
                            
                        try:
                            weight = float(weight_str)
                            # 防呆：確保不是表頭重複，且數字合理
                            if 0 < weight <= 100 and name and '名稱' not in name:
                                result.append({
                                    "ETF代號": clean_ticker,
                                    "成分股代號": t_code,
                                    "成分股名稱": name,
                                    "權重(%)": weight
                                })
                        except ValueError:
                            continue
                break # 抓完目標表單就跳出
                
        if len(result) > 0:
            result = sorted(result, key=lambda x: x['權重(%)'], reverse=True)[:20]
            print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(result)} 檔成分股")
            time.sleep(1)
            return result
    except Exception as e:
        pass

    # --- 引擎 2：Yahoo 股市 (嚴格備援) ---
    print(f"🔄 MoneyDJ 無資料，嘗試備援機制 (Yahoo)...")
    try:
        url_yahoo = f"https://tw.stock.yahoo.com/quote/{clean_ticker}.TW/holding"
        res = requests.get(url_yahoo, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        main_area = soup.find('main') or soup.find('div', id='main-0-Quote-Proxy')
        if main_area and main_area.find(string=lambda t: t and '持股名稱' in t):
            list_items = main_area.find_all('li', class_=lambda x: x and 'List(n)' in x)
            for item in list_items:
                text_blocks = item.find_all('div')
                if len(text_blocks) >= 2:
                    name = text_blocks[0].text.strip()
                    weight_block = item.find(string=lambda t: t and '%' in t)
                    if weight_block:
                        weight_str = weight_block.replace('%', '').strip()
                        try:
                            weight = float(weight_str)
                            if 0 < weight <= 100 and name != '持股名稱':
                                 result.append({
                                    "ETF代號": clean_ticker,
                                    "成分股代號": "-",
                                    "成分股名稱": name.split(' ')[0], 
                                    "權重(%)": weight
                                })
                        except ValueError:
                            pass

        if len(result) > 0:
            unique_result = {v['成分股名稱']:v for v in result}.values()
            result = sorted(list(unique_result), key=lambda x: x['權重(%)'], reverse=True)[:20]
            print(f"✅ [來源: Yahoo] 成功抓取 {clean_ticker}，共 {len(result)} 檔成分股")
        else:
            print(f"⚠️ {clean_ticker} 網站無提供成分股明細。")
    except Exception as e:
        pass

    time.sleep(1)
    return result

# ==========================================
# 3. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (動態表頭與防呆版)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"❌ 讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    # 處理台股
    for row in tw_records:
        raw_ticker = str(row.get('Ticker', '')).strip().upper()
        if not raw_ticker: continue
        
        # 使用智慧補零還原真實代號
        clean_ticker = pad_tw_ticker(raw_ticker)
        
        # 只要開頭是 00 或者是台股標的，就檢查是否為債券
        if clean_ticker.startswith('00'):
            if clean_ticker.endswith('B'):
                print(f"⏭️ 判定為債券 ETF，跳過: {clean_ticker}")
                continue
                
            holdings = get_tw_etf_holdings(clean_ticker)
            if holdings:
                all_holdings.extend(holdings)

    # 處理海外標的
    for row in us_records:
        ticker = str(row.get('Ticker', '')).strip().upper()
        if not ticker: continue
        
        holdings = get_us_etf_holdings(ticker)
        if holdings:
            all_holdings.extend(holdings)

    if not all_holdings:
        print("⚠️ 最終未取得任何 ETF 的持股資料。")
        return

    # 寫入 Google Sheets
    df_holdings = pd.DataFrame(all_holdings)
    # 重新排列欄位順序，讓畫面更整齊
    cols_order = ['ETF代號', '成分股代號', '成分股名稱', '權重(%)']
    df_holdings = df_holdings[cols_order]
    
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
