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
# 請將這裡換成您實際的 Google Sheets 網址
PORTFOLIO_SHEET_URL = "您的_Portfolio_streamlit_網址"
HOLDINGS_SHEET_URL = "您的_ETF_Holdings_DB_網址"

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
            print(f"✅ 成功抓取美股 ETF: {ticker}，共 {len(result)} 檔成分股")
            return result
    except Exception as e:
        print(f"❌ 抓取 {ticker} 失敗: {e}")
    return []

def get_tw_etf_holdings(ticker):
    """
    台股 ETF 爬蟲 (嚴格驗證版，已鎖定主內容區避免誤抓)
    """
    clean_ticker = str(ticker).replace('.TW', '').replace('.TWO', '')
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    result = []

    # --- 引擎 1：嘗試 MoneyDJ ---
    try:
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res = requests.get(url_mdj, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        tables = soup.find_all('table')
        for tbl in tables:
            tbl_text = tbl.text.replace(' ', '').replace('\n', '')
            if ('名稱' in tbl_text or '股票' in tbl_text) and ('比例' in tbl_text or '權重' in tbl_text):
                for row in tbl.find_all('tr'):
                    cols = [c.text.strip() for c in row.find_all(['td', 'th'])]
                    if len(cols) >= 3:
                        name = cols[0]
                        weight_str = cols[-1].replace('%', '').strip()
                        try:
                            weight = float(weight_str)
                            if 0 < weight <= 100 and len(name) < 20 and name not in ['股票名稱', '名稱', '基金名稱']:
                                result.append({
                                    "ETF代號": clean_ticker,
                                    "成分股名稱": name,
                                    "權重(%)": weight
                                })
                        except ValueError:
                            continue
                break 
                
        if len(result) > 0:
            result = sorted(result, key=lambda x: x['權重(%)'], reverse=True)[:20]
            print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(result)} 檔成分股")
            time.sleep(1)
            return result
            
    except Exception as e:
        pass

    # --- 引擎 2：嘗試 Yahoo 股市 ---
    print(f"🔄 MoneyDJ 無資料，啟動備援機制 (Yahoo 股市)...")
    try:
        url_yahoo = f"https://tw.stock.yahoo.com/quote/{clean_ticker}.TW/holding"
        res = requests.get(url_yahoo, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        main_area = soup.find('main') or soup.find('div', id='main-0-Quote-Proxy')
        
        if main_area:
            if main_area.find(string=lambda t: t and '持股名稱' in t):
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
            print(f"⚠️ {clean_ticker} 網站無提供成分股明細 (可能尚未更新)。")

    except Exception as e:
        pass

    time.sleep(1)
    return result

# ==========================================
# 3. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (Top 20，自動排除債券 ETF)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    # 2. 處理台股 ETF (過濾出 00 開頭，並排除 B 結尾)
    for row in tw_records:
        ticker = str(row.get('Ticker', '')).strip().upper() # 轉大寫，避免使用者輸入小寫 b
        
        # 判斷是否為 00 開頭
        if ticker.startswith('00'):
            # 判斷是否為債券 ETF
            if ticker.endswith('B'):
                print(f"⏭️ 跳過債券 ETF: {ticker}")
                continue
                
            holdings = get_tw_etf_holdings(ticker)
            all_holdings.extend(holdings)

    # 3. 處理美股 ETF (此處若有債券 ETF 如 BND 仍會抓取，因 yfinance 抓得到部分)
    us_etf_list = ['VOO', 'QQQ', 'VT', 'BND', 'BNDW', 'BNDX', 'IEF', 'VNQ', 'VXUS']
    for row in us_records:
        ticker = str(row.get('Ticker', '')).strip().upper()
        if ticker in us_etf_list:
            holdings = get_us_etf_holdings(ticker)
            all_holdings.extend(holdings)

    if not all_holdings:
        print("⚠️ 未抓取到任何持股資料。")
        return

    # 4. 轉換為 DataFrame 並進行無效數據清洗
    df_holdings = pd.DataFrame(all_holdings)
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
