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

# ------------------------------------------
# 智能攔截器：連結型 ETF (Feeder Fund) 對應表
# 當偵測到左邊台股代號，直接去抓右邊的海外母體 ETF 持股
# ------------------------------------------
FEEDER_MAP = {
    "009812": "1306.T",  # 野村日本東證 -> NEXT FUNDS TOPIX ETF (東京證交所)
    # 若未來有類似 100% 連結國外的 ETF，也可在此無限擴充
}

# ==========================================
# 2. 終極二維矩陣表格解析器 (無視 HTML 結構陷阱)
# ==========================================
def extract_table_matrix(html_text):
    """將網頁表格完全扁平化成 2D 陣列，無懼跨欄或隱藏標籤"""
    soup = BeautifulSoup(html_text, 'html.parser')
    tables = soup.find_all('table')
    
    for tbl in tables:
        rows = tbl.find_all('tr')
        matrix = []
        for r in rows:
            cols = r.find_all(['td', 'th'])
            matrix.append([c.text.strip().replace('\n', '').replace('\r', '') for c in cols])
        
        if not matrix: continue
        
        name_idx, weight_idx = -1, -1
        data_start = -1
        
        # 掃描前 10 列尋找欄位名稱
        for i, row in enumerate(matrix[:10]):
            for j, val in enumerate(row):
                v = val.replace(' ', '')
                if any(k in v for k in ['名稱', '股票', '標的', '成分股', '發行公司']):
                    name_idx = j
                if any(k in v for k in ['權重', '比例', '比重', '佔比', '%']):
                    weight_idx = j
            
            if name_idx != -1 and weight_idx != -1:
                data_start = i + 1
                break
        
        if data_start != -1:
            holdings = []
            for row in matrix[data_start:]:
                if len(row) > max(name_idx, weight_idx):
                    name = row[name_idx].strip()
                    w_str = row[weight_idx].replace('%', '').replace(',', '').strip()
                    
                    if not name or name in ['小計', '總計', '合計', '現金', '其他'] or '名稱' in name:
                        continue
                    try:
                        weight = float(w_str)
                        if 0 < weight <= 100:
                            holdings.append({"成分股名稱": name, "權重(%)": weight})
                    except ValueError:
                        pass
            if holdings:
                return holdings
    return []

def process_holdings(ticker, holdings_list):
    res = []
    for h in holdings_list[:50]:  # 強制放寬至 Top 50
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
# 3. 跨國爬蟲引擎
# ==========================================
def get_us_etf_holdings(ticker):
    """處理美股、日股等海外 ETF 標的"""
    print(f"🔍 正在檢查海外標的: {ticker}")
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
            print(f"✅ 成功抓取海外 ETF: {ticker}，共 {len(result)} 檔")
            return process_holdings(ticker, result)
    except Exception:
        pass
    print(f"⚠️ {ticker} 系統無提供成分股明細。")
    return []

def get_tw_etf_holdings(raw_ticker):
    clean_ticker = pad_tw_ticker(raw_ticker)
    
    # 攔截器：若為 Feeder Fund，自動切換至海外抓取，並掛回原代號
    if clean_ticker in FEEDER_MAP:
        target_ticker = FEEDER_MAP[clean_ticker]
        print(f"🔄 偵測到 {clean_ticker} 為連結型基金，自動轉向抓取母體 {target_ticker}...")
        overseas_holdings = get_us_etf_holdings(target_ticker)
        # 把海外抓到的標的，全部套上台灣的 ETF 代號
        for item in overseas_holdings:
            item["ETF代號"] = clean_ticker
        return overseas_holdings
    
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    # 引擎 1：MoneyDJ (.TW 綁定)
    try:
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res = requests.get(url_mdj, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        holdings = extract_table_matrix(res.text)
        if holdings:
            holdings = sorted(holdings, key=lambda x: x['權重(%)'], reverse=True)
            print(f"✅ [來源: MoneyDJ] 成功抓取 {clean_ticker}，共 {len(holdings)} 檔")
            time.sleep(1)
            return process_holdings(clean_ticker, holdings)
    except Exception:
        pass

    # 引擎 2：CMoney (直接解析)
    try:
        url_c = f"https://www.cmoney.tw/etf/tw/{clean_ticker}/fundholding"
        res = requests.get(url_c, headers=headers, timeout=10)
        holdings = extract_table_matrix(res.text)
        if holdings:
            holdings = sorted(holdings, key=lambda x: x['權重(%)'], reverse=True)
            print(f"✅ [來源: CMoney] 成功抓取 {clean_ticker}，共 {len(holdings)} 檔")
            time.sleep(1)
            return process_holdings(clean_ticker, holdings)
    except Exception:
        pass

    # 引擎 3：Yahoo 股市 (雙後綴備援)
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
                    if not name or name in ['持股名稱', '股票名稱', '標的'] or len(name) > 30:
                        continue
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
                print(f"✅ [來源: Yahoo] 成功抓取 {clean_ticker}，共 {len(unique_holdings)} 檔")
                time.sleep(1)
                return process_holdings(clean_ticker, unique_holdings)
        except Exception:
            pass
            
    print(f"⚠️ {clean_ticker} 各大網站無提供明細 (可能為剛上市或資料空窗期)。")
    time.sleep(1)
    return []

# ==========================================
# 4. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (二維矩陣與母體連動版)...")
    
    try:
        portfolio_sheet = client.open_by_url(PORTFOLIO_SHEET_URL)
        tw_records = portfolio_sheet.worksheet("TW_Portfolio").get_all_records()
        us_records = portfolio_sheet.worksheet("US_Portfolio").get_all_records()
    except Exception as e:
        print(f"❌ 讀取 Portfolio_streamlit 失敗: {e}")
        return

    all_holdings = []

    # 處理台股清單
    for row in tw_records:
        raw_ticker = str(row.get('Ticker', '')).strip().upper()
        if not raw_ticker: continue
        clean_ticker = pad_tw_ticker(raw_ticker)
        
        if clean_ticker.startswith('00') and not clean_ticker.endswith('B'):
            holdings = get_tw_etf_holdings(clean_ticker)
            if holdings:
                all_holdings.extend(holdings)

    # 處理美股清單
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
