import os
import time
import json
import gspread
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import re
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
# 2. 深度資料清洗與驗證演算法 (解決雜訊問題)
# ==========================================
def clean_and_validate_holding(raw_name, raw_weight):
    """
    專門過濾 MoneyDJ 混在成分股欄位中的「產業分類」與「資產類別」
    並清洗名稱上的雜訊 (如 "1.台積電" -> "台積電", "國巨*" -> "國巨")
    """
    name = str(raw_name).strip().replace('\n', '').replace('\r', '')
    
    # 移除開頭的數字排序 (如 "1.", "10.")
    name = re.sub(r'^\d+\.', '', name).strip()
    # 移除結尾的星號 (如 "國巨*")
    name = re.sub(r'\*+$', '', name).strip()
    
    # 1. 拒絕包含特定字眼的資產分類
    bad_keywords = ['股票', '債券', '現金', '期貨', '選擇權', '基金', '合計', '小計', '總計', '資產', '其他', '行業', '存款', '附買回', '流動準備']
    if not name or any(k in name for k in bad_keywords):
        return None, None
        
    # 2. 拒絕產業分類 (如 "半導體業", "金融保險")
    if name.endswith('業') and len(name) >= 3:
        # 允許少數真的以"業"結尾的公司 (如 統一實業)
        if name not in ['統一實業', '大成實業']:
            return None, None
            
    industry_names = ['金融保險', '生技醫療', '通信網路', '觀光餐旅', '電子零組件', '半導體', '電腦及週邊設備', '光電', '航運', '鋼鐵', '塑膠', '紡織纖維', '電機機械', '電器電纜', '化學工業', '建材營造', '貿易百貨', '油電燃氣', '橡膠', '造紙', '玻璃陶瓷', '水泥']
    if name in industry_names:
        return None, None
        
    # 3. 驗證並轉換權重數字
    w_str = str(raw_weight).replace('%', '').replace(',', '').strip()
    try:
        weight = float(w_str)
        if 0 < weight <= 100:
            return name, weight
    except ValueError:
        pass
        
    return None, None

def process_holdings(ticker, holdings_list):
    """綁定 ETF 代號，去除重複，並允許最大抓取 50 筆"""
    unique_dict = {}
    for h in holdings_list:
        name = h["成分股名稱"]
        if name not in unique_dict:
            unique_dict[name] = h
            
    res = list(unique_dict.values())
    res = sorted(res, key=lambda x: x['權重(%)'], reverse=True)[:50]
    
    final_res = []
    for h in res:
        final_res.append({
            "ETF代號": ticker,
            "成分股名稱": h["成分股名稱"],
            "權重(%)": h["權重(%)"]
        })
    return final_res

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
    clean_ticker = pad_tw_ticker(raw_ticker)
    print(f"🔍 正在抓取台股 ETF: {clean_ticker}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
    }
    
    results = []

    # ========================================================
    # 引擎 1：MoneyDJ (雙軌解析法，專治各種不規則表格與 009815)
    # ========================================================
    try:
        url_mdj = f"https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid={clean_ticker}.TW"
        res = requests.get(url_mdj, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # [軌道 A] 嚴格解析法 (專攻 0050 等混合產業分類的表格)
        for tr in soup.find_all('tr'):
            tds = tr.find_all(['td', 'th'])
            if len(tds) >= 2:
                for i in range(len(tds) - 1):
                    col1 = tds[i].text.strip()
                    # 嚴格尋找開頭是數字+小數點的格式 (如 "1.台積電")
                    if re.match(r'^\d+\.', col1):
                        col2 = tds[i+1].text.strip()
                        name, weight = clean_and_validate_holding(col1, col2)
                        if name and weight:
                            results.append({"成分股名稱": name, "權重(%)": weight})
                        break # 換下一列
                        
        if results:
            print(f"✅ [MoneyDJ 嚴格解析] 成功抓取 {clean_ticker}，共 {len(results)} 檔純淨資料")
            time.sleep(1)
            return process_holdings(clean_ticker, results)
            
        # [軌道 B] 寬鬆 Pandas 解析法 (當軌道 A 失敗時啟用，專攻 009815 這種海外無排序 ETF)
        dfs = pd.read_html(StringIO(res.text))
        for df in dfs:
            df = df.astype(str)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [str(c[-1]) for c in df.columns]
                
            name_idx, weight_idx = -1, -1
            data_start_row = 0
            name_kws = ['名稱', '標的', '股票', '持股', '成分股']
            weight_kws = ['權重', '比例', '比重', '佔比', '%']
            
            for i, col in enumerate(df.columns):
                if any(k in str(col) for k in name_kws): name_idx = i
                if any(k in str(col) for k in weight_kws): weight_idx = i
                
            if name_idx == -1 or weight_idx == -1:
                for idx, row in df.head(10).iterrows():
                    n_i, w_i = -1, -1
                    for i, val in enumerate(row):
                        if any(k in str(val) for k in name_kws): n_i = i
                        if any(k in str(val) for k in weight_kws): w_i = i
                    if n_i != -1 and w_i != -1:
                        name_idx, weight_idx = n_i, w_i
                        data_start_row = idx + 1
                        break
                        
            if name_idx != -1 and weight_idx != -1:
                for idx in range(data_start_row, len(df)):
                    name, weight = clean_and_validate_holding(df.iloc[idx, name_idx], df.iloc[idx, weight_idx])
                    if name and weight:
                        results.append({"成分股名稱": name, "權重(%)": weight})
                        
        if results:
            print(f"✅ [MoneyDJ 寬鬆解析] 成功抓取 {clean_ticker}，共 {len(results)} 檔純淨資料")
            time.sleep(1)
            return process_holdings(clean_ticker, results)
    except Exception:
        pass

    # ========================================================
    # 引擎 2：Yahoo 股市 (終極備援，含 .TW 與 .TWO)
    # ========================================================
    for suffix in ['.TW', '.TWO']:
        try:
            url_y = f"https://tw.stock.yahoo.com/quote/{clean_ticker}{suffix}/holding"
            res = requests.get(url_y, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            for item in soup.find_all('li'):
                divs = item.find_all('div')
                if len(divs) >= 2:
                    raw_n = divs[0].text.strip()
                    if len(raw_n) > 30: continue
                    for d in divs[1:]:
                        if '%' in d.text:
                            name, weight = clean_and_validate_holding(raw_n.split(' ')[0], d.text)
                            if name and weight:
                                results.append({"成分股名稱": name, "權重(%)": weight})
                                break 
            if results:
                print(f"✅ [Yahoo 備援] 成功抓取 {clean_ticker}，共 {len(results)} 檔純淨資料")
                time.sleep(1)
                return process_holdings(clean_ticker, results)
        except Exception:
            pass
            
    print(f"⚠️ {clean_ticker} 查無明細 (可能為剛上市，或資料庫空窗)。")
    time.sleep(1)
    return []

# ==========================================
# 4. 主程式邏輯
# ==========================================
def main():
    print("🚀 開始執行 ETF 持股更新作業 (防雜訊與新股相容升級版)...")
    
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
    sheet_title = current_date.strftime("%Y_%m_Top50")
    
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
