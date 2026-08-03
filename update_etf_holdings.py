import os
import time
import json
import gspread
import pandas as pd
import numpy as np
import yfinance as yf
import requests
from bs4 import BeautifulSoup
from io import StringIO
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone

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
# 2. 萬用 Pandas 表格解析引擎 (核心突破)
# ==========================================
def process_df(df):
    """利用 Pandas 矩陣特性，暴力破解任何不規則的表格結構"""
    df = df.astype(str) # 全面轉字串以利關鍵字比對
    
    # 攤平多重索引 (針對 MoneyDJ 複雜表格)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[-1]) for c in df.columns]
    
    name_idx, weight_idx = -1, -1
    data_start_row = 0
    
    # 廣泛涵蓋各大網站的詭異欄位命名
    name_keywords = ['名稱', '標的', '股票', '持股', '成分股', '發行公司']
    weight_keywords = ['權重', '比例', '比重', '佔比', '%', '佔資產']

    # 1. 檢查 DataFrame 內建表頭
    for i, col in enumerate(df.columns):
        col_str = str(col).replace(' ', '')
        if any(k in col_str for k in name_keywords):
            if name_idx == -1: name_idx = i
        if any(k in col_str for k in weight_keywords):
            if weight_idx == -1: weight_idx = i

    # 2. 若表頭沒抓到，掃描表格前 10 列尋找隱藏的標題列 (針對跨欄合併的網頁)
    if name_idx == -1 or weight_idx == -1:
        for idx, row in df.head(10).iterrows():
            n_idx, w_idx = -1, -1
            for i, val in enumerate(row):
                val_str = str(val).replace(' ', '')
                if any(k in val_str for k in name_keywords):
                    if n_idx == -1: n_idx = i
                if any(k in val_str for k in weight_keywords):
                    if w_idx == -1: w_idx = i
            if n_idx != -1 and w_idx != -1:
                name_idx, weight_idx = n_idx, w_idx
                data_start_row = idx + 1 # 資料從標題的下一行開始
                break
    
    # 3. 提取數據並清洗雜訊
    if name_idx != -1 and weight_idx != -1:
        results = []
        for idx in range(data_start_row, len(df)):
            name = str(df.iloc[idx, name_idx]).strip()
            weight_str = str(df.iloc[idx, weight_idx]).replace('%', '').replace(',', '').strip()
            
            # 排除合計、小計、空值與表頭重複
            if not name or name.lower() in ['nan', 'none', '小計', '合計', '總計', '-']:
                continue
            if any(k in name for k in ['名稱', '權重', '比例', '明細', '比重']):
                continue
                
            try:
                weight = float(weight_str)
                if 0 < weight <= 100:
                    results.append({"成分股名稱": name, "權重(%)": weight})
            except ValueError:
                continue
                
        if len(results) > 0:
            return results
    return []

def process_holdings(ticker, holdings_list):
    """綁定 ETF 代號並允許最大抓取 50 筆"""
    res = []
    for h in holdings_list[:50]:
        res.append({
            "ETF代號": ticker,
            "成分股名稱": h["成分股名稱"],
            "權重(%)": h["權重(%)"]
        })
    return res

def pad_tw_ticker(ticker):
    t = str(ticker).strip().upper().replace('.TW', '').replace('.TWO', '')
    if t.isdigit():
        if len(t) == 2: return "00" + t  
        if len(t) == 3: return "00" + t  
    else:
        if len(t) == 4 and t[0] in '123456789': return "00" + t 
    return t

# ==========================================
# 3. 各市場獨立爬蟲引擎
# ==========================================
def get_us_etf_holdings(ticker):
    """【美股專用】僅針對海外 ETF 呼叫 YFinance"""
    print(f"🔍 正在檢查美股 ETF: {ticker}")
    try:
        etf = yf.Ticker(ticker)
        funds_data = etf.get_funds_data()
        if funds_data and funds_data.top_holdings is not None and not funds_data.top_holdings.empty:
            holdings = funds_data.top_holdings.head(50) 
            result = []
            for symbol, row in holdings.iterrows():
                weight = row.get('Holding Percent', 0)
                if pd.isna(weight): weight = 0 
                result.append({"成分股名稱": row.get('Name', symbol), "權重(%)": round(weight * 100, 2)})
            print(f"✅ [美股 YFinance] 成功抓取 {ticker}，共 {len(result)} 檔")
            return process_holdings(ticker, result)
    except Exception:
        pass
    print(f"⚠️ {ticker} 系統無提供成分股明細。")
    return []

def get_tw_etf_holdings(raw_ticker):
    """【台股專用】透過 Pandas 引擎解析 CMoney 與 MoneyDJ"""
    clean_ticker = pad_tw_ticker(raw_ticker)
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 引擎列表：CMoney 優先 (資料最全)，MoneyDJ 備援 (包含 .TW 與 .TWO 雙盲測)
    urls_to_try = [
        (f"https://www.cmoney.tw/etf/tw/{clean_ticker}/fundholding", "CMoney"),
        (f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW", "MoneyDJ (.TW)"),
        (f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TWO", "MoneyDJ (.TWO)")
    ]
    
    for url, source_name in urls_to_try:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            
            # 核心突破：直接將網頁餵給 Pandas，自動找出所有表格
            dfs = pd.read_html(StringIO(res.text))
            
            # 掃描網頁上的每一個表格，只要有符合格式的就抓
            for df in dfs:
                holdings = process_df(df)
                if holdings:
                    holdings = sorted(holdings, key=lambda x: x['權重(%)'], reverse=True)
                    print(f"✅ [來源: {source_name}] 成功抓取 {clean_ticker}，共 {len(holdings)} 檔 (突破 Top 10)")
                    time.sleep(1)
                    return process_holdings(clean_ticker, holdings)
        except Exception:
            pass

    # 終極備援：Yahoo 股市 (僅能抓 Top 10，作為最後防線)
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            list_items = soup.find_all('li')
            holdings = []
            for item in list_items:
                divs = item.find_all('div')
                if len(divs) >= 2:
                    name = divs[0].text.strip()
                    if not name or name in ['持股名稱', '股票名稱', '標的'] or len(name) > 30: continue
                    for d in divs[1:]:
                        txt = d.text.strip()
                        if '%' in txt and len(txt) < 15:
                            try:
                                weight = float(txt.replace('%', '').replace(',', ''))
                                if 0 < weight <= 100:
                                    holdings.append({"成分股名稱": name.split(' ')[0], "權重(%)": weight})
                                    break 
                            except ValueError:
                                pass
            if holdings:
                unique_holdings = list({v['成分股名稱']:v for v in holdings}.values())
                unique_holdings = sorted(unique_holdings, key=lambda x: x['權重(%)'], reverse=True)
                print(f"✅ [來源: Yahoo] 成功抓取 {clean_ticker}，共 {len(unique_holdings)} 檔 (備援)")
                time.sleep(1)
                return process_holdings(clean_ticker, unique_holdings)
        except Exception:
            pass
            
    print(f"⚠️ {clean_ticker} 各大網站無提供明細 (可能為剛上市、資料空窗，或為未持有個股的連結型基金)。")
    time.sleep(1)
    return []

# ==========================================
# 4. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (Pandas 矩陣暴力解析版)...")
    
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
        clean_ticker = pad_tw_ticker(raw_ticker)
        
        if clean_ticker.startswith('00') and not clean_ticker.endswith('B'):
            holdings = get_tw_etf_holdings(clean_ticker)
            if holdings:
                all_holdings.extend(holdings)

    # 處理美股
    for row in us_records:
        ticker = str(row.get('Ticker', '')).strip().upper()
        if not ticker: continue
        holdings = get_us_etf_holdings(ticker)
        if holdings:
            all_holdings.extend(holdings)

    if not all_holdings:
        print("⚠️ 最終未取得任何 ETF 的持股資料。")
        return

    df_holdings = pd.DataFrame(all_holdings)
    cols_order = ['ETF代號', '成分股名稱', '權重(%)']
    df_holdings = df_holdings[cols_order]
    
    df_holdings.replace([np.inf, -np.inf], np.nan, inplace=True)
    df_holdings = df_holdings.fillna(0)
    
    tz_tw = timezone(timedelta(hours=8))
    current_date = datetime.now(tz_tw)
    sheet_title = current_date.strftime("%Y_%m_Top50") # 表格動態擴增至 Top 50 命名
    
    try:
        db_sheet = client.open_by_url(HOLDINGS_SHEET_URL)
        try:
            ws = db_sheet.worksheet(sheet_title)
            print(f"📝 找到當月工作表 {sheet_title}，準備更新資料...")
        except gspread.exceptions.WorksheetNotFound:
            print(f"✨ 建立新的月份工作表: {sheet_title}")
            ws = db_sheet.add_worksheet(title=sheet_title, rows="2000", cols="10")
            
        ws.clear()
        ws.update([df_holdings.columns.values.tolist()] + df_holdings.values.tolist())
        print(f"✅ 成功將所有 ETF 持股寫入 Google Sheets ({sheet_title})！")
    except Exception as e:
        print(f"❌ 寫入 ETF_Holdings_DB 失敗: {e}")

if __name__ == "__main__":
    main()
